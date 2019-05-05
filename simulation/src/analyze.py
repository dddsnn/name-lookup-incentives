import util
import networkx as nx
import pickle
import matplotlib.pyplot as plt
import numpy as np
import math
import itertools as it
import operator as op
import bitstring
import peer


# Patch in a less-than for the Bits class, which is necessary for ordered dicts
# and sets.
bitstring.Bits.__lt__ = util.bits_lt


class Logger:
    # OPTI Make snapshots of the data occasionally so the entire event list
    # doesn't have to be processed when querying global information.
    def __init__(self, settings):
        self.settings = settings
        self.events = []

    def log(self, event):
        """
        Log an event.

        Return the ID of the event in the event list.
        """
        if not isinstance(event, Event):
            raise Exception('Attempt to log a non-Event.')
        if self.events and event.time < self.events[-1].time:
            raise Exception('Attempt to log an event from the past.')
        self.events.append(event)
        return len(self.events) - 1

    def dump(self, file_name):
        """
        Store the event list to disk.

        First connects outgoing event IDs.
        """
        self.make_out_events()
        with open(file_name, 'w+b') as file:
            pickle.dump((self.settings, self.events), file)

    @staticmethod
    def load(file_name):
        with open(file_name, 'rb') as file:
            settings, events = pickle.load(file)
            logger = Logger(settings)
            logger.events = events
            return logger

    def make_out_events(self):
        """
        Connect events in a forward direction.

        Goes through the event list and sets each event's out_event_ids
        according to its existing in_event_id.
        """
        for event in self.events:
            event.out_event_ids = set()
        for i, event in enumerate(self.events):
            if event.in_event_id is not None:
                self.events[event.in_event_id].out_event_ids.add(i)

    def print_sync_groups_at(self, time):
        """Print information about sync groups at a point in time."""
        sync_groups = Replay(self.events, {},
                             sync_groups_event_processor).at(time)

        print('sync groups (prefix: {peers}):')
        for pr, sg in sorted(sync_groups.items(), key=lambda t: t[0].uint):
            print('{}: {{{}}}'.format(pr.bin, ', '.join(str(p) for p in sg)))

    def print_query_groups_at(self, time):
        """Print information about query groups at a point in time."""
        groups = Replay(self.events, {},
                        self.query_groups_event_processor).at(time)

        print('query_groups (peer: reputation):')
        for query_group_id, query_group in sorted(groups.items(),
                                                  key=lambda t: t[0]):
            print('{}: {{{}}}'.format(query_group_id, ', '.join(
                str(peer_id) + ': ' + '{:.1f}'.format(rep)
                for peer_id, rep in sorted(query_group.items(),
                                           key=lambda t: t[1],
                                           reverse=True))))

    def print_uncovered_subprefixes_at(self, time):
        """Print info about missing subprefix coverage at a point in time."""
        uncovered_subprefixes = Replay(
            self.events, {}, uncovered_subprefixes_event_processor).at(time)

        print('missing subprefix coverage per peer:')
        any_missing = False
        for peer_id, subprefixes in sorted(uncovered_subprefixes.items(),
                                           key=lambda t: t[0].uint):
            if subprefixes:
                any_missing = True
                print('{}: missing prefixes {{{}}}'
                      .format(peer_id,
                              ', '.join((i.bin for i in subprefixes))))
        if not any_missing:
            print('none')

    def print_strongly_connected_components_at(self, time):
        """Print info about the reachability graph at a point in time."""
        peer_graph = Replay(self.events, nx.DiGraph(),
                            reachability_graph_event_processor).at(time)

        print('strongly connected components:')
        from networkx import strongly_connected_components as scc
        for i, comp in enumerate((peer_graph.subgraph(c)
                                  for c in scc(peer_graph))):
            print('component {}: {} nodes, diameter {}, degree histogram: {}'
                  .format(i, nx.number_of_nodes(comp), nx.diameter(comp),
                          nx.degree_histogram(comp)))

    def print_global_info_at(self, time):
        """Print all global information at a point in time."""
        self.print_sync_groups_at(time)
        print()
        self.print_query_groups_at(time)
        print()
        self.print_uncovered_subprefixes_at(time)
        print()
        self.print_strongly_connected_components_at(time)

    def peer_reputations_at(self, time, peer_id):
        """
        Get a peer's reputations at a point in time.

        Returns a dictionary mapping the query group ID to the peer's
        reputation in that group.
        """
        replay = Replay(self.events, {}, self.query_groups_event_processor)
        replay.step_until(time)
        reputations = {}
        for query_group_id, query_group in replay.data.items():
            if peer_id in query_group:
                reputations[query_group_id] = query_group[peer_id]
        return reputations

    def plot_average_reputation_until(self, until_time):
        """Plot average reputation over time until some point."""
        reputations = {}
        replay = Replay(self.events, {}, self.query_groups_event_processor)
        current_time = 0

        def append_step():
            for query_group_id, query_group in replay.data.items():
                total_reputation = sum(query_group.values())
                num_peers = len(query_group)
                reputation_per_peer = total_reputation / num_peers
                record = reputations.setdefault(query_group_id, ([], []))
                time_list = record[0]
                rep_list = record[1]
                time_list.append(current_time)
                rep_list.append(reputation_per_peer)

        append_step()
        while True:
            current_time = replay.step_next()
            if current_time is None or current_time > until_time:
                break
            append_step()

        data_set = [(np.array(record[0]), np.array(record[1]),
                     query_group_id)
                    for query_group_id, record in sorted(reputations.items(),
                                                         key=lambda t: t[0])]
        plot_steps('Average reputation in query groups', 'Time', 'Reputation',
                   ((('', data_set),)))

    def plot_reputation_percentiles_until(self, until_time, max_edge_length=3):
        """Plot reputation percentiles over time until some point."""
        reputations = {}
        replay = Replay(self.events, {}, self.query_groups_event_processor)
        current_time = 0
        percentile_tuple = (5, 25, 50, 75, 95)

        def append_step():
            for query_group_id, query_group in replay.data.items():
                percentiles = np.percentile(list(query_group.values()),
                                            percentile_tuple)
                record = reputations.setdefault(query_group_id, ([], []))
                time_list = record[0]
                rep_list = record[1]
                time_list.append(current_time)
                rep_list.append(percentiles)

        append_step()
        while True:
            current_time = replay.step_next()
            if current_time is None or current_time > until_time:
                break
            append_step()

        data_sets = []
        for query_group_id, record in sorted(reputations.items(),
                                             key=lambda t: t[0]):
            time_axis = np.array(record[0])
            data_set = [(time_axis, np.array([r[i] for r in record[1]]),
                         '{}%'.format(percentile_tuple[i]))
                        for i in range(len(percentile_tuple))]
            data_sets.append(('Query group {}'.format(query_group_id),
                              data_set))

        def axes_modifier(axes):
            npr = self.settings['no_penalty_reputation']
            enough_rep = (self.settings['reputation_buffer_factor']
                          * self.settings['no_penalty_reputation'])
            axes.axhline(npr, linestyle='--', color='k', alpha=0.2)
            axes.axhline(enough_rep, linestyle='--', color='k', alpha=0.2)
        plot_steps('Reputation percentiles in query groups', 'Time',
                   'Reputation', data_sets, max_edge_length, axes_modifier)

    def plot_response_statuses_until(self, until_time, bin_size=10):
        """Plot response statuses over time until some point."""
        replay = Replay(self.events, {}, response_status_event_processor)
        replay.step_until(until_time)
        for category in ('success', 'failure', 'timeout', 'unmatched'):
            replay.data.setdefault(category, [])

        bins = np.arange(0, replay.current_time + bin_size, bin_size)
        plt.title('Response statuses')
        plt.hist((np.array(replay.data['success']),
                  np.array(replay.data['failure']),
                  np.array(replay.data['timeout']),
                  np.array(replay.data['unmatched'])),
                 bins, label=('success', 'failure', 'timeout', 'unmatched'),
                 histtype='barstacked')
        plt.xlabel('Time')
        plt.ylabel('Number of responses')
        plt.legend()
        plt.show()

    def plot_queries_at_peers_between(self, start_time, until_time,
                                      num_bins=40):
        """Plot number of queries arriving at peers in a time range."""
        replay = Replay(self.events, {}, queries_received_event_processor)
        replay.skip_before(start_time)
        replay.step_until(until_time)

        data_sets = [('', [np.array(list(replay.data.values()))])]
        plot_hists('Number of queries arriving at peers', 'Number of queries',
                   'Number of peers', data_sets, num_bins, 1)

    def plot_selection_probabilities_at(self, time, num_bins=10,
                                        max_edge_length=3):
        """
        Plot histograms of the probability a peer is selected for a query.

        For each query group, plots a histogram of the probability for each
        peer to be sent a query when a request occurs at some other member in
        the group. The query groups taken as a base are the ones that existed
        at the given time.

        To compute these probabilities within a query group for one peer, it is
        considered that a request occurs (i.e. from outside the system) at
        another peer in the group (each peer has the same probability for
        this). This peer may be able to answer the request from local
        information, and no query is sent at all. Otherwise, for the peer where
        the request arrived, the peer selection for the queried ID is computed,
        i.e. the set of peers who are the first choice for sending a query to.
        The preference is based on the overlap of prefix and the queried ID.
        All peers in the peer selection have the same maximal overlap. If the
        peer for whom the probability is computed is in this set, the
        probability is increased by 1 / (s * qg * i), where s is the number of
        peers in the selection (i.e. the peers this peer is "competing" with),
        qg is the number of other peers in the query group (to factor in the
        probability that it was the peer at which the request occurred we're
        considering), and i is the number of peer IDs in all query groups
        (since we're only looking at one specific ID in this round). This is
        done for all possible queried IDs and all other peers in the query
        group.

        The algorithm uses its knowledge of what IDs exist in the system (it
        doesn't consider queries for IDs that don't exist). It also considers
        the peer whose ID is the queried ID as a potential peer to be selected,
        even though that doesn't make sense if the purpose of the query is to
        find out the address of the peer. It assumes all peers are equally
        likely to have a request occur (i.e. no peer is more "active" than
        others), and it assumes requested IDs are equally distributed (i.e.
        none is more popular than others).

        Under these assumptions, the probability is a fair estimator for how
        useful a peer is in a query group.
        """
        replay = Replay(self.events, {}, self.query_groups_event_processor)
        replay.step_until(time)
        query_groups = {i: set(v.keys()) for i, v in replay.data.items()}

        def peer_prefix(peer_id):
            return peer_id[:self.settings['prefix_length']]

        def query_peers(peer_id):
            query_peer_ids = set(it.chain(*(g for g in query_groups.values()
                                            if peer_id in g)))
            query_peer_ids.discard(peer_id)
            return list(query_peer_ids)

        def selected_peers(selecting_peer_id, queried_id):
            """
            Return the preferred set of peers used for queries for an ID.

            The set of peers contains IDs of all those peers whose prefix has
            the highest overlap with the queried ID and who share a query group
            with the selecting peer, but not the selecting peer's ID.
            """
            selecting_prefix = peer_prefix(selecting_peer_id)
            if queried_id.startswith(selecting_prefix):
                # Selecting peer knows this ID from sync groups.
                return set()
            query_peer_ids = query_peers(selecting_peer_id)
            if not query_peer_ids:
                # Selecting peer doesn't have any query peers.
                return set()
            query_peer_ids.sort(
                key=lambda p: util.bit_overlap(peer_prefix(p), queried_id),
                reverse=True)
            first_overlap = util.bit_overlap(peer_prefix(query_peer_ids[0]),
                                             queried_id)
            selecting_overlap = util.bit_overlap(selecting_prefix, queried_id)
            if first_overlap <= selecting_overlap:
                # Peer is  closer to the queried ID than any query peer, won't
                # send a query at all.
                return set()
            return set(it.takewhile(
                lambda p: util.bit_overlap(peer_prefix(p), queried_id)
                == first_overlap,
                       query_peer_ids))

        peer_ids = set(p for g in query_groups.values() for p in g)
        peer_selection = {p: {} for p in peer_ids}
        for selecting_peer_id, selection in peer_selection.items():
            for queried_id in peer_ids:
                selection[queried_id] = selected_peers(selecting_peer_id,
                                                       queried_id)
        selection_probabilities = {}
        for query_group_id, query_group in query_groups.items():
            sp = selection_probabilities.setdefault(query_group_id, {})
            for peer_id, querying_peer_id in it.product(query_group, repeat=2):
                # Compute the probability that when a request occurs at a peer
                # in the query group, a query is sent to the peer (with ID
                # peer_id).
                sp.setdefault(peer_id, 0)
                if peer_id == querying_peer_id:
                    continue
                for queried_id in peer_ids:
                    selection = peer_selection[querying_peer_id][queried_id]
                    if peer_id not in selection:
                        continue
                    # Add the probability that the query was sent by the peer
                    # with ID querying_peer_id ((1/len(query_group))-1) and the
                    # queried ID was queried_id (1/len(peer_ids)) and the peer
                    # with ID peer_id is the one selected (1/len(selection)).
                    sp[peer_id] += 1 / (len(selection) * len(peer_ids)
                                        * (len(query_group) - 1))

        data_sets = [('Query group {}'.format(i), [np.array(list(p.values()))])
                     for i, p in selection_probabilities.items()]
        plot_hists('Peer selection probabilities by query group at time {}'
                   .format(time), 'Probability', 'Number of peers', data_sets,
                   num_bins, max_edge_length)

    def plot_query_group_sizes_until(self, until_time, max_edge_length=3):
        """Plot query group sizes over time until some point."""
        sizes = {}
        replay = Replay(self.events, {}, self.query_groups_event_processor)
        current_time = 0

        def append_step():
            for query_group_id, query_group in replay.data.items():
                size = len(query_group)
                record = sizes.setdefault(query_group_id, ([], []))
                time_list = record[0]
                size_list = record[1]
                time_list.append(current_time)
                size_list.append(size)

        append_step()
        while True:
            current_time = replay.step_next()
            if current_time is None or current_time > until_time:
                break
            append_step()

        data_sets = []
        for query_group_id, record in sorted(sizes.items(),
                                             key=lambda t: t[0]):
            time_axis = np.array(record[0])
            size_axis = np.array(record[1])
            data_set = [(time_axis, size_axis, 'Number of peers')]
            data_sets.append(('Query group {}'.format(query_group_id),
                              data_set))

        plot_steps('Query group sizes', 'Time', 'Number of peers', data_sets,
                   max_edge_length)

    def plot_peer_reputations_until(self, until_time, max_edge_length=3):
        """Plot peer reputations over time until some point."""
        reps = {}
        replay = Replay(self.events, {}, self.query_groups_event_processor)
        current_time = 0

        def append_step():
            for query_group_id, query_group in replay.data.items():
                for peer_id, rep in query_group.items():
                    peer_reps = reps.setdefault(peer_id, {})
                    record = peer_reps.setdefault(query_group_id, ([], []))
                    time_list = record[0]
                    rep_list = record[1]
                    time_list.append(current_time)
                    rep_list.append(rep)

        append_step()
        while True:
            current_time = replay.step_next()
            if current_time is None or current_time > until_time:
                break
            append_step()

        data_sets = []
        for peer_id, peer_reps in sorted(reps.items(),
                                         key=lambda t: t[0].uint):
            data_set = []
            for query_group_id, record in sorted(peer_reps.items(),
                                                 key=op.itemgetter(0)):
                time_axis = np.array(record[0])
                rep_axis = np.array(record[1])
                data_set.append((time_axis, rep_axis,
                                 'Group {}'.format(query_group_id)))
            data_sets.append(('Peer {}'.format(peer_id.hex), data_set))

        def axes_modifier(axes):
            npr = self.settings['no_penalty_reputation']
            enough_rep = (self.settings['reputation_buffer_factor']
                          * self.settings['no_penalty_reputation'])
            axes.axhline(npr, linestyle='--', color='k', alpha=0.2)
            axes.axhline(enough_rep, linestyle='--', color='k', alpha=0.2)

        plot_steps('Peer reputations', 'Time', 'Reputation', data_sets,
                   max_edge_length, axes_modifier)

    def query_groups_event_processor(self, data, event):
        """
        Process an event to build query groups.

        The data that is built is a dictionary mapping query group ID to
        dictionaries representing query groups. These map peer ID to the peer's
        reputation. The initial value must be an empty dictionary.
        """
        if isinstance(event, QueryGroupAdd):
            query_group = data.setdefault(event.query_group_id, {})
            if event.peer_id not in query_group:
                query_group[event.peer_id]\
                    = self.settings['initial_reputation']
        elif isinstance(event, QueryGroupRemove):
            query_group = data.get(event.query_group_id)
            if query_group is not None:
                query_group.pop(event.peer_id, None)
                if len(query_group) == 0:
                    data.pop(event.query_group_id, None)
        elif isinstance(event, ReputationUpdateSent):
            for query_group_id in event.query_group_ids:
                query_group = data.get(query_group_id)
                if query_group is None:
                    query_group = data.setdefault(query_group_id, {})
                new_rep = peer.calculate_reputation(
                    self.settings['reward_attenuation'],
                    query_group.setdefault(event.peer_id, 0),
                    event.reputation_diff)
                query_group[event.peer_id] = new_rep
        elif isinstance(event, ReputationDecay):
            for query_group in data.values():
                for query_peer_id, reputation in query_group.items():
                    new_rep = max(0, reputation - event.decay)
                    query_group[query_peer_id] = new_rep


def plot_steps(title, xlabel, ylabel, data_sets, max_edge_length=3,
               axes_modifier=None):
    """
    Plot a grid of step graphs.

    See plot_grid().

    :param data_sets: A list of data sets, in order. Each data set contains
        data for one graph (axes in matplotlib) and is a tuple of title (for
        the individual graph) and a list of plot data. Each plot data contains
        data for one plot within the graph. It is a list of tuples of the form
        (x, y, label), where x is a numpy ndarray containing x values,
        similarly for y, and label is a label for the plot.
    """
    def plotter(axes, plot_data):
        axes.step(plot_data[0], plot_data[1], label=plot_data[2], where='post')
    plot_grid(title, xlabel, ylabel, data_sets, plotter, max_edge_length,
              axes_modifier)


def plot_hists(title, xlabel, ylabel, data_sets, num_bins, max_edge_length=3):
    """
    Plot a grid of histograms.

    See plot_grid().

    :param data_sets: A list of data sets, in order. Each data set contains
        data for one graph (axes in matplotlib) and is a tuple of title (for
        the individual graph) and a list of plot data. Each plot data contains
        data for one plot within the graph. It is a list with one entry which
        is a numpy ndarray containing the values for the histogram.
    """
    def plotter(axes, plot_data):
        axes.hist(plot_data, num_bins)
    plot_grid(title, xlabel, ylabel, data_sets, plotter, max_edge_length)


def plot_grid(title, xlabel, ylabel, data_sets, plotter, max_edge_length=3,
              axes_modifier=None):
    """
    Plot a grid of graphs.

    Creates one or more figures (basically images in matplotlib) and fills them
    with graphs (axes in matplotlib) visualizing data from data_sets. Up to
    max_edge_length**2 graphs are in one figure (in a square grid), but no more
    than necessary.

    A legend is shown only in the first graph of each figure.

    :param title: Title for the overall figure.
    :param xlabel: Label for the x axes. Only shown in the bottom row.
    :param ylabel: Label for the y axes. Only shown in the left column.
    :param data_sets: A list of data sets, in order. Each data set contains
        data for one graph (axes in matplotlib) and is a tuple of title (for
        the individual graph) and a list of plot data. Each plot data contains
        data for one plot within the graph. It is passed to the plotter
        function.
    :param plotter: A function taking a matplotlib axes and one entry of the
        plot data list that creates the plot.
    :param max_edge_length: Maximum number of graphs to lay out along each
        edge of a figure. A figure will have no more than max_edge_length**2
        graphs.
    :param axes_modifier: A function taking one parameter to which each axes
        object is passed.
    """
    edge_length = math.ceil(math.sqrt(len(data_sets)))
    if edge_length > max_edge_length:
        edge_length = max_edge_length
    edge_length = max(1, edge_length)
    num_figures = math.ceil(len(data_sets) / edge_length ** 2)
    for figure_idx in range(num_figures):
        figure, axess = plt.subplots(edge_length, edge_length, sharex=True,
                                     sharey=True, squeeze=False)
        figure.suptitle('{} ({}/{})'.format(title, figure_idx + 1,
                                            num_figures))
        for axes_idx in range(edge_length ** 2):
            data_set_idx = axes_idx + figure_idx * edge_length ** 2
            if data_set_idx >= len(data_sets):
                break
            axes_title, data_set = data_sets[data_set_idx]
            axes = axess.flatten()[axes_idx]
            axes.set_title(axes_title)
            if axes_modifier:
                axes_modifier(axes)
            if not axes_idx % edge_length:
                axes.set_ylabel(ylabel)
            for plot_data in data_set:
                plotter(axes, plot_data)
            if axes_idx == 0 and axes.get_label():
                axes.legend()
        for axes in axess.flatten()[edge_length * (edge_length - 1):]:
            axes.set_xlabel(xlabel)
    plt.show()


def sync_groups_event_processor(data, event):
    """
    Process an event to build sync groups.

    The data that is built is a dictionary mapping the prefix of the group to a
    set of peer IDs. The initial value must be an empty dictionary.
    """
    if isinstance(event, PeerAdd):
        data.setdefault(event.prefix, set()).add(event.peer_id)
    elif isinstance(event, PeerRemove):
        if event.prefix in data:
            data[event.prefix].discard(event.peer_id)
            if len(data[event.prefix]) == 0:
                data.pop(event.prefix)


def uncovered_subprefixes_event_processor(data, event):
    """
    Process an event to build uncovered subprefixes.

    The data that is built is a dictionary mapping peer IDs to the set of
    subprefixes that aren't covered for the peer. The initial value must be an
    empty dictionary.
    """
    if isinstance(event, UncoveredSubprefixes):
        data[event.peer_id] = event.subprefixes


def reachability_graph_event_processor(data, event):
    """
    Process an event to build the peer reachability graph.

    The initial value must be an empty DiGraph.
    """
    if isinstance(event, ConnectionAdd):
        data.add_edge(event.peer_a_id, event.peer_b_id)
    elif isinstance(event, ConnectionRemove):
        try:
            data.remove_edge(event.peer_a_id, event.peer_b_id)
        except nx.NetworkXError:
            pass


def response_status_event_processor(data, event):
    """
    Process an event to build response and timeout status information.

    The data that is built is a dictionary whose values are lists with the
    timestamps of different categories of responses and timeouts. The keys are
    the allowed keys for the status parameter from
    :meth:`analyze.ResponseReceived.__init__`, as well as 'timeout'.

    The initial value must be an empty dictionary.
    """
    if isinstance(event, ResponseReceived):
        data.setdefault(event.status, []).append(event.time)
    elif isinstance(event, Timeout):
        data.setdefault('timeout', []).append(event.time)


def queries_received_event_processor(data, event):
    """
    Process an event to build the number of queries received by peers.

    The data that is built is a dictionary mapping peer IDs to the number of
    queries received by that peer.

    The initial value must be an empty dictionary.
    """
    if isinstance(event, QuerySent):
        # Use the recipient of QuerySent rather than of QueryReceived, since
        # the latter is also logged when a peer handles a request (locally).
        data.setdefault(event.recipient_id, 0)
        data[event.recipient_id] += 1


class Replay:
    """Class that allows to replay logged events."""
    def __init__(self, events, data_init, event_processor):
        """
        :param events: The event list to be replayed. Must be ordered by time.
        :param data_init: Initial value for the structure containing the data
            that can be examined.
        :param event_processor: A function accepting the data and an event that
            updates the data by that event.
        """
        self.events = events
        self.data = data_init
        self.event_processor = event_processor
        self.next_idx = 0
        self.current_time = -1

    def at(self, time):
        """Access the data at a point in time."""
        self.step_until(time)
        return self.data

    def skip_before(self, time):
        """
        Skip to the point just before a time without processing.

        Puts the replay in a state from which step_until() will process the
        event in the event list with the smallest time that is greater or
        equal than the given time parameter.
        """
        if time <= self.current_time:
            raise Exception('Attempt to move backwards.')
        self.next_idx = next((i for i, e in enumerate(self.events)
                              if e.time >= time), len(self.events))
        if self.next_idx == 0:
            self.current_time = -1
        else:
            self.current_time = self.events[self.next_idx - 1].time

    def step_until(self, time):
        """Process events up to a point in time."""
        if time < self.current_time:
            raise Exception('Attempt to move backwards.')
        while (self.next_idx < len(self.events)
               and self.events[self.next_idx].time <= time):
            event = self.events[self.next_idx]
            self.event_processor(self.data, event)
            self.next_idx += 1
            self.current_time = event.time

    def step_next(self):
        """
        Process next event(s).

        This may be more than one, if multiple events happened at the same
        time.

        Return the new current time, or None if no further events have been
        processed.
        """
        if self.next_idx >= len(self.events):
            return None
        time = self.events[self.next_idx].time
        self.step_until(time)
        return time


class EmptyClass:
    pass


class Event:
    """Superclass for all log events."""
    def __init__(self, time, in_event_id):
        """
        :param time: The time at which the event occurred,
        :param in_event_id: The ID of the event that caused this event.
        """
        self.time = time
        self.in_event_id = in_event_id
        self.out_event_ids = set()

    def __repr__(self):
        return util.generic_repr(self)

    def previous_events(self, event_list):
        """
        List events leading to this one.

        Follows the in_event_id pointers that are indexes into the given event
        list and builds a list of all events that caused this one, beginning
        with the earliest one. Does not include this event.
        """
        events = []
        current_in_id = self.in_event_id
        while current_in_id is not None:
            events.insert(0, event_list[current_in_id])
            current_in_id = events[0].in_event_id
        return events

    def following_events(self, event_list):
        """
        List events immediately following this one.

        Uses the out_event_ids pointers that are indexes into the given event
        list and builds a list of the events that immediately follow this one.
        Does now follow them recursively, so there may be more events
        following.
        """
        return [event_list[i] for i in self.out_event_ids]


class Request(Event):
    """
    Event representing a request arriving at a peer.

    A request comes from outside the system and simulates the user interacting
    with the protocol stack. This is in contrast to a query, which is an
    interaction between peers.
    """
    def __init__(self, time, requester_id, queried_id, status):
        """
        :param requester_id: ID of the peer at which the request arrives.
        :param queried_id: ID that is requested to be resolved.
        :param status: The status of the request, indicating what further
            action is taken as a response. Must be one of
            * 'own_id': Request for the ID of the requesting peer, can be
                  answered trivially.
            * 'known': Request for which the answer is known (e.g. because the
                  peer is responsible for a prefix of the queried ID).
            * 'querying': A query will be sent to resolve the request.
        """
        super().__init__(time, None)
        self.requester_id = requester_id
        self.queried_id = queried_id
        if status not in ('own_id', 'known', 'querying'):
            raise Exception('Status must be one of own_id, known, or'
                            ' querying.')
        self.status = status


class QuerySent(Event):
    """Event representing a query being sent."""
    def __init__(self, time, sender_id, recipient_id, queried_id, in_event_id):
        super().__init__(time, in_event_id)
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.queried_id = queried_id


class QueryReceived(Event):
    """Event representing a query being received."""
    def __init__(self, time, sender_id, recipient_id, queried_id, status,
                 in_event_id):
        """
        :param status: The status of the query. Must be one of
            * 'own_id': Query for the ID of the recipient. Trivial to answer.
            * 'known': Query for an ID known to the recipient.
            * 'external': Query for an ID that isn't known immediately. A
                further query must be sent in order to answer this query. This
                may not happen if the peer e.g. decides he has enough
                reputation.
        """
        super().__init__(time, in_event_id)
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.queried_id = queried_id
        if status not in ('own_id', 'known', 'external'):
            raise Exception('Status must be one of own_id, known, or external')
        self.status = status


class ResponseScheduled(Event):
    """Event representing a response being sent."""
    def __init__(self, time, send_time, sender_id, recipient_id,
                 queried_peer_info, queried_id, in_event_id):
        """
        :param send_time: The time at which the query will actually be sent (as
            opposed to time, which is when it is scheduled).
        :param queried_peer_info: The PeerInfo object containing information
            about a peer matching the queried IDs. This may be None to indicate
            that no information could be found for the queried IDs. The fields
            (ID, prefix and address) may be None to indicate that no peer
            exists matching any of the queried IDs.
        :param queried_id: The ID that was queried.
        """
        super().__init__(time, in_event_id)
        self.send_time = send_time
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.queried_peer_info = queried_peer_info
        self.queried_id = queried_id


class ResponseReceived(Event):
    """Event representing a response being received."""
    def __init__(self, time, sender_id, recipient_id, queried_peer_info,
                 queried_id, status, in_event_id):
        """
        :param queried_peer_info: See
            :meth:`analyze.ResponseScheduled.__init__`.
        :param queried_id: See :meth:`analyze.ResponseScheduled.__init__`.
        :param status: Status of the response. Must be one of
            * 'unmatched': There is no known query the peer has sent and still
                  knows about that matches this response.
            * 'success': Successful response, i.e. the sender claims to provide
                the correct information about the queried ID.
            * 'failure': The responding peer cannot resolve the query.
        """
        super().__init__(time, in_event_id)
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.queried_peer_info = queried_peer_info
        self.queried_id = queried_id
        if status not in ('unmatched', 'success', 'failure'):
            raise Exception('Status must be one of unmatched, success, or'
                            ' failure.')
        self.status = status


class ReputationUpdateSent(Event):
    """Event representing sending a reputation update."""
    def __init__(self, time, sender_id, recipient_ids, peer_id,
                 reputation_diff, query_group_ids, in_event_id):
        super().__init__(time, in_event_id)
        self.sender_id = sender_id
        self.recipient_ids = recipient_ids
        self.peer_id = peer_id
        self.reputation_diff = reputation_diff
        self.query_group_ids = query_group_ids


class ReputationUpdateReceived(Event):
    """Event representing a reputation update being received."""
    def __init__(self, time, sender_id, recipient_id, peer_id, reputation_diff,
                 in_event_id):
        super().__init__(time, in_event_id)
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.peer_id = peer_id
        self.reputation_diff = reputation_diff


class Timeout(Event):
    def __init__(self, time, sender_id, recipient_id, queried_id, in_event_id):
        """
        :param sender_id: ID of the peer that sent the request that timed out.
        :param recipient_id: ID of the peer to which the request, which timed
            out, was sent.
        """
        super().__init__(time, in_event_id)
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.queried_id = queried_id


class QueryFinalized(Event):
    """
    Event representing a query being finalized.

    A query is finalized if a response has arrived at or a timeout occurred at
    the peer the originally issued it because of a request.
    """
    def __init__(self, time, peer_id, status, in_event_id):
        """
        :param peer_id: ID of the peer the query belongs to.
        :param status: Status of the query. Must be one of
            * 'success': Query was successful
            * 'failure': Query did not return a result.
            * 'timeout': Query timed out.
            * 'pending': There's already a query going on for the same ID.
            * 'impossible': The peer didn't know any peers to send a query to.
        """
        super().__init__(time, in_event_id)
        self.peer_id = peer_id
        if status not in ('success', 'failure', 'timeout', 'pending',
                          'impossible'):
            raise Exception('Status must be one of success, failure, timeout,'
                            'pending, or impossible.')
        self.status = status


class PeerAdd(Event):
    """Event representing a peer being added to the simulation."""
    def __init__(self, time, peer_id, prefix, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_id = peer_id
        self.prefix = prefix


class PeerRemove(Event):
    """Event representing a peer being removed from the simulation."""
    def __init__(self, time, peer_id, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_id = peer_id


class QueryGroupAdd(Event):
    """Event representing a peer being added to a query group."""
    def __init__(self, time, peer_id, query_group_id, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_id = peer_id
        self.query_group_id = query_group_id


class QueryGroupRemove(Event):
    """Event representing a peer being removed from a query group."""
    def __init__(self, time, peer_id, query_group_id, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_id = peer_id
        self.query_group_id = query_group_id


class QueryGroupReevaluation(Event):
    """Event representing a peer reevaluating query group memberships."""
    def __init__(self, time, peer_id, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_id = peer_id


class UncoveredSubprefixes(Event):
    """Event representing set of subprefixes not being covered for a peer."""
    def __init__(self, time, peer_id, subprefixes, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_id = peer_id
        self.subprefixes = subprefixes


class UncoveredSubprefixSearch(Event):
    """Event representing a peer looking for better subprefix coverage."""
    def __init__(self, time, peer_id, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_id = peer_id


class ConnectionAdd(Event):
    """Event representing a peer learning about another."""
    def __init__(self, time, peer_a_id, peer_b_id, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_a_id = peer_a_id
        self.peer_b_id = peer_b_id


class ConnectionRemove(Event):
    """Event representing a peer not being able to reach another anymore."""
    def __init__(self, time, peer_a_id, peer_b_id, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_a_id = peer_a_id
        self.peer_b_id = peer_b_id


class ReputationDecay(Event):
    """Event representing global reputation decay."""
    def __init__(self, time, decay):
        super().__init__(time, None)
        self.decay = decay


class ExpectedPenalty(Event):
    """Event representing a penalty being expected in the future."""
    def __init__(self, time, peer_id, penalizing_peer_id, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_id = peer_id
        self.penalizing_peer_id = penalizing_peer_id


class UnexpectedPenaltyApplied(Event):
    """Event representing a penalty being applied that wasn't expected."""
    def __init__(self, time, peer_id, penalizing_peer_id, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_id = peer_id
        self.penalizing_peer_id = penalizing_peer_id


class ExpectedPenaltyApplied(Event):
    """Event representing a penalty being applied as expected."""
    def __init__(self, time, peer_id, penalizing_peer_id, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_id = peer_id
        self.penalizing_peer_id = penalizing_peer_id


class ExpectedPenaltyTimeout(Event):
    """Event representing a penalty that was expected timing out."""
    def __init__(self, time, peer_id, penalizing_peer_id, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_id = peer_id
        self.penalizing_peer_id = penalizing_peer_id


class QueryPeerVanished(Event):
    """Event representing a query peer not being in there for an update."""
    def __init__(self, time, peer_id, updated_peer_id, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_id = peer_id
        self.updated_peer_id = updated_peer_id
