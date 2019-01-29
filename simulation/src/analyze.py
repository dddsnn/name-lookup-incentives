import networkx as nx
import pickle


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

    def sync_groups(self, time):
        """Print information about sync groups at a point in time."""
        sync_groups = {}
        for event in self.events:
            if event.time > time:
                break
            if isinstance(event, PeerAdd):
                sync_groups.setdefault(event.prefix, set()).add(event.peer_id)
            elif isinstance(event, PeerRemove):
                if event.prefix in sync_groups:
                    sync_groups[event.prefix].discard(event.peer_id)
                    if len(sync_groups[event.prefix]) == 0:
                        sync_groups.pop(event.prefix)
            else:
                continue

        print('sync groups (prefix: {peers}):')
        for pr, sg in sorted(sync_groups.items(), key=lambda t: t[0].uint):
            print('{}: {{{}}}'.format(pr.bin, ', '.join(str(p) for p in sg)))

    def query_groups(self, time):
        """Print information about query groups at a point in time."""
        groups = {}
        for event in self.events:
            if event.time > time:
                break
            if isinstance(event, QueryGroupAdd):
                query_group = groups.setdefault(event.query_group_id, {})
                if event.peer_id not in query_group:
                    query_group[event.peer_id] = 0
            elif isinstance(event, QueryGroupRemove):
                query_group = groups.get(event.query_group_id)
                if query_group is not None:
                    query_group.pop(event.peer_id, None)
                    if len(query_group) == 0:
                        groups.pop(event.query_group_id, None)
            elif isinstance(event, ReputationUpdate):
                for query_group_id in event.query_group_ids:
                    query_group = groups.get(query_group_id)
                    if query_group is None:
                        query_group = groups.setdefault(event.query_group_id,
                                                        {})
                    new_rep = (query_group.setdefault(event.peer_id, 0)
                               + event.reputation_diff)
                    query_group[event.peer_id] = new_rep
            elif isinstance(event, ReputationDecay):
                for query_group in groups.values():
                    for query_peer_id, reputation in query_group.items():
                        new_rep = max(0, reputation - event.decay)
                        query_group[query_peer_id] = new_rep
            else:
                continue

        print('query_groups (peer: reputation):')
        for query_group in groups.values():
            print('{{{}}}'.format(', '.join(
                str(peer_id) + ': ' + '{:.1f}'.format(rep)
                for peer_id, rep in sorted(query_group.items(),
                                           key=lambda t: t[1],
                                           reverse=True))))

    def uncovered_subprefixes(self, time):
        """Print info about missing subprefix coverage at a point in time."""
        uncovered_subprefixes = {}
        for event in self.events:
            if event.time > time:
                break
            if isinstance(event, UncoveredSubprefixes):
                uncovered_subprefixes[event.peer_id] = event.subprefixes
            else:
                continue

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

    def strongly_connected_components(self, time):
        """Print info about the reachability graph at a point in time."""
        peer_graph = nx.DiGraph()
        for event in self.events:
            if event.time > time:
                break
            if isinstance(event, ConnectionAdd):
                peer_graph.add_edge(event.peer_a_id, event.peer_b_id)
            elif isinstance(event, ConnectionRemove):
                try:
                    peer_graph.remove_edge(event.peer_a_id, event.peer_b_id)
                except nx.NetworkXError:
                    pass
            else:
                continue

        print('strongly connected components:')
        from networkx import strongly_connected_components as scc
        for i, comp in enumerate((peer_graph.subgraph(c)
                                  for c in scc(peer_graph))):
            print('component {}: {} nodes, diameter {}, degree histogram: {}'
                  .format(i, nx.number_of_nodes(comp), nx.diameter(comp),
                          nx.degree_histogram(comp)))


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
    def __init__(self, time, sender_id, recipient_id, peer_id, reputation_diff,
                 query_group_ids, in_event_id):
        super().__init__(time, in_event_id)
        self.sender_id = sender_id
        self.recipient_id = recipient_id
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


class ReputationUpdate(Event):
    """Event representing sending a reputation update."""
    def __init__(self, time, peer_id, reputation_diff, query_group_ids,
                 in_event_id):
        super().__init__(time, in_event_id)
        self.peer_id = peer_id
        self.reputation_diff = reputation_diff
        self.query_group_ids = query_group_ids


class ReputationDecay(Event):
    """Event representing global reputation decay."""
    def __init__(self, time, decay):
        super().__init__(time, None)
        self.decay = decay


def print_info_process(env, logger):
    while True:
        yield env.timeout(10)
        print_info(logger, env.now)


def print_info(logger, time):
    print()
    logger.sync_groups(time)
    print()
    logger.query_groups(time)
    print()
    logger.uncovered_subprefixes(time)
    print()
    logger.strongly_connected_components(time)
    print()
