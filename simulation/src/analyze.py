import networkx as nx
import pickle
import matplotlib.pyplot as plt
import numpy as np
from math import sqrt, ceil


class Logger:
    # TODO Make snapshots of the data occasionally so the entire event list
    # doesn't have to be processed when querying global information.
    def __init__(self):
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
            pickle.dump(self.events, file)

    @staticmethod
    def load(file_name):
        with open(file_name, 'rb') as file:
            events = pickle.load(file)
            logger = Logger()
            logger.events = events
            return logger

    def make_out_events(self):
        """
        Connect events in a forward direction.

        Goes through the event list and sets each event's out_event_ids
        according to its existing in_event_id.
        """
        for event in self.events:
            event.out_even_ids = set()
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
        groups = Replay(self.events, {}, query_groups_event_processor).at(time)

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
        replay = Replay(self.events, {}, query_groups_event_processor)
        replay.step_until(time)
        reputations = {}
        for query_group_id, query_group in replay.data.items():
            if peer_id in query_group:
                reputations[query_group_id] = query_group[peer_id]
        return reputations

    def plot_average_reputation_until(self, until_time):
        """Plot average reputation over time until some point."""
        reputations = {}
        replay = Replay(self.events, {}, query_groups_event_processor)
        current_time = 0

        def append_step():
            for query_group_id, query_group in replay.data.items():
                total_reputation = sum(query_group.values())
                num_peers = len(query_group)
                reputation_per_peer = total_reputation / num_peers
                record = reputations.setdefault(query_group_id, ([], []))
                time_list = record[0]
                rep_list = record[1]
                if rep_list and rep_list[-1] == reputation_per_peer:
                    # Value hasn't changed, no need to record it.
                    continue
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
        replay = Replay(self.events, {}, query_groups_event_processor)
        current_time = 0
        percentile_tuple = (5, 25, 50, 75, 95)

        def append_step():
            for query_group_id, query_group in replay.data.items():
                percentiles = np.percentile(list(query_group.values()),
                                            percentile_tuple)
                record = reputations.setdefault(query_group_id, ([], []))
                time_list = record[0]
                rep_list = record[1]
                if len(rep_list) > 0 and np.array_equal(rep_list[-1],
                                                        percentiles):
                    # Value hasn't changed, no need to record it.
                    continue
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
            data_sets.append(('Query group {} ({} peers)'
                              .format(query_group_id,
                                      len(replay.data[query_group_id])),
                              data_set))

        def axes_modifier(axes):
            # TODO Unhardcode reputation thresholds.
            axes.axhline(10, linestyle='--', color='k', alpha=0.2)
            axes.axhline(15, linestyle='--', color='k', alpha=0.2)
        plot_steps('Reputation percentiles in query groups', 'Time',
                   'Reputation', data_sets, max_edge_length, axes_modifier)

    def plot_response_statuses_until(self, until_time, bin_size=10):
        """Plot response statuses over time until some point."""
        replay = Replay(self.events, {}, response_status_event_processor)
        replay.step_until(until_time)
        for category in ('success', 'failure_retry', 'failure_ultimate',
                         'timeout_failure_retry', 'timeout_failure_ultimate',
                         'late_success', 'late_failure', 'unmatched',
                         'wrong_responder'):
            replay.data.setdefault(category, [])

        bins = np.arange(0, replay.current_time + bin_size, bin_size)
        plt.title('Response statuses')
        plt.hist((np.array(replay.data['success']),
                  np.array(replay.data['failure_retry']),
                  np.array(replay.data['failure_ultimate']),
                  np.array(replay.data['timeout_failure_retry']),
                  np.array(replay.data['timeout_failure_ultimate']),
                  np.array(replay.data['late_success']),
                  np.array(replay.data['late_failure']),
                  np.array(replay.data['unmatched']),
                  np.array(replay.data['wrong_responder'])),
                 bins, label=('success', 'retry failure', 'ultimate failure',
                              'retry timeout', 'ultimate timeout',
                              'late success', 'late failure', 'unmatched',
                              'wrong responder'),
                 histtype='barstacked')
        plt.legend()
        plt.show()


def plot_steps(title, xlabel, ylabel, data_sets, max_edge_length=3,
               axes_modifier=None):
    """
    Plot step graphs of data sets.

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
        data for one plot within the graph. It is a list of tuples of the form
        (x, y, label), where x is a numpy ndarray containing x values,
        similarly for y, and label is a label for the plot.
    :param max_edge_length: Maximum number of graphs to lay out along each
        edge of a figure. A figure will have no more than max_edge_length**2
        graphs.
    :param axes_modifier: A function taking one parameter to which each axes
        object is passed.
    """
    edge_length = ceil(sqrt(len(data_sets)))
    if edge_length > max_edge_length:
        edge_length = max_edge_length
    num_figures = ceil(len(data_sets) / edge_length ** 2)
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
                axes.step(plot_data[0], plot_data[1], label=plot_data[2],
                          where='post')
            if axes_idx == 0:
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


def query_groups_event_processor(data, event):
    """
    Process an event to build query groups.

    The data that is built is a dictionary mapping query group ID to
    dictionaries representing query groups. These map peer ID to the peer's
    reputation. The initial value must be an empty dictionary.
    """
    if isinstance(event, QueryGroupAdd):
        query_group = data.setdefault(event.query_group_id, {})
        if event.peer_id not in query_group:
            query_group[event.peer_id] = 0
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
                query_group = data.setdefault(event.query_group_id, {})
            new_rep = max(0, query_group.setdefault(event.peer_id, 0)
                          + event.reputation_diff)
            query_group[event.peer_id] = new_rep
    elif isinstance(event, ReputationDecay):
        for query_group in data.values():
            for query_peer_id, reputation in query_group.items():
                new_rep = max(0, reputation - event.decay)
                query_group[query_peer_id] = new_rep


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
    :meth:`analyze.ResponseReceived.__init__`, as well as
    'timeout_failure_ultimate' and 'timeout_failure_retry' with meanings
    analogous to the status parameter in :meth:`analyze.Timeout.__init__`.

    The initial value must be an empty dictionary.
    """
    if isinstance(event, ResponseReceived):
        data.setdefault(event.status, []).append(event.time)
    elif isinstance(event, Timeout):
        data.setdefault('timeout_' + event.status, []).append(event.time)


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
        excluded = set(EmptyClass.__dict__.keys())
        attrs = ((attr, value) for (attr, value)
                 in sorted(self.__dict__.items()) if attr not in excluded)
        return '{}: {{{}}}'.format(type(self).__name__, ', '.join(
            '{}: {}'.format(attr, value) for (attr, value) in attrs))

    def previous_events(self, event_list):
        """
        List events leading to this one.

        Follows the in_event_id pointers that are indexes into the given event
         and builds a list of all events that caused this one, beginning with
        the earliest one. Does not include this event.
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
            * 'pending': A query has already been sent matching the queried ID.
            * 'own_id': Request for the ID of the requesting peer, can be
                  answered trivially.
            * 'known': Request for which the answer is known (e.g. because the
                  peer is responsible for a prefix of the queried ID).
            * 'querying': A query will be sent to resolve the request.
        """
        super().__init__(time, None)
        self.requester_id = requester_id
        self.queried_id = queried_id
        if status not in ('pending', 'own_id', 'known', 'querying'):
            raise Exception('Status must be one of pending, own_id, known, or'
                            ' querying.')
        self.status = status
        self.completed = status in ('own_id', 'known')


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
            * 'pending': A further query for a relevant ID or prefix is already
                  pending.
            * 'querying': A further query must be sent in order to answer this
                  query.
        """
        super().__init__(time, in_event_id)
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.queried_id = queried_id
        if status not in ('own_id', 'known', 'pending', 'querying'):
            raise Exception('Status must be one of own_id, known, pending, or'
                            ' querying.')
        self.status = status


# TODO Include the queried peer's address.
class ResponseSent(Event):
    """Event representing a response being sent."""
    def __init__(self, time, sender_id, recipient_id, queried_peer_id,
                 queried_ids, in_event_id):
        """
        :param queried_peer_id: The ID of the peer that is the result of the
            query. May be None if the query was unsuccessful.
        :param queried_ids: A set containing all IDs or prefixes for which
            queried_id is a response. I.e., all elements of this set are a
            prefix of queried_id.
        """
        super().__init__(time, in_event_id)
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.queried_peer_id = queried_peer_id
        self.queried_ids = queried_ids


# TODO Include the queried peer's address.
class ResponseReceived(Event):
    """Event representing a response being received."""
    def __init__(self, time, sender_id, recipient_id, queried_peer_id,
                 queried_ids, status, in_event_id):
        """
        :param queried_peer_id: See :meth:`analyze.ResponseSent.__init__`.
        :param queried_ids: See :meth:`analyze.ResponseSent.__init__`.
        :param status: Status of the response. Must be one of
            * 'unmatched': There is no known query the peer has sent and still
                  knows about that matches this response.
            * 'wrong_responder': The response matches a previously sent query,
                 but the sender isn't the peer that was queried.
            * 'success': Query successful.
            * 'failure_ultimate': The responding peer cannot resolve the query,
                  and there are no other peers to query.
            * 'failure_retry': The responding peer cannot resolve the query,
                  but there are other peers that can be queried that may be
                  able.
            * 'late_success': The query was successful, but was already
                  previously successfully resolved (by another peer).
            * 'late_failure': The query failed, but was already previously
                  successfully resolved (by another peer).
        """
        super().__init__(time, in_event_id)
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.queried_peer_id = queried_peer_id
        self.queried_ids = queried_ids
        if status not in ('unmatched', 'wrong_responder', 'success',
                          'failure_ultimate', 'failure_retry', 'late_success',
                          'late_failure'):
            raise Exception('Status must be one of unmatched, wrong_responder,'
                            ' success, failure_ultimate, failure_retry,'
                            ' late_success, or late_failure.')
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
    def __init__(self, time, sender_id, recipient_id, queried_id, status,
                 in_event_id):
        """
        :param sender_id: ID of the peer that sent the request that timed out.
        :param recipient_id: ID of the peer to which the request, which timed
            out, was sent.
        :param status: Status of the timeout. Must be one of
            * 'failure_ultimate': There are no other peers the sender can
                  query.
            * 'failure_retry': The sender knows other peers to whom he can send
                  the query.
        """
        super().__init__(time, in_event_id)
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.queried_id = queried_id
        if status not in ('failure_ultimate', 'failure_retry'):
            raise Exception('Status must be one of failure_ultimate or'
                            ' failure_retry.')
        self.status = status


class PeerAdd(Event):
    """Event representing a peer being."""
    def __init__(self, time, peer_id, prefix, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_id = peer_id
        self.prefix = prefix


class PeerRemove(Event):
    """Event representing a peer being."""
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


class UncoveredSubprefixes(Event):
    """Event representing set of subprefixes not being covered for a peer."""
    def __init__(self, time, peer_id, subprefixes, in_event_id):
        super().__init__(time, in_event_id)
        self.peer_id = peer_id
        self.subprefixes = subprefixes


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
