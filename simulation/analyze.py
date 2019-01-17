import networkx as nx


class Logger:
    def __init__(self):
        self.events = []

    def log(self, event):
        self.events.append(event)


class Event:
    def __init__(self, time):
        self.time = time


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
        super().__init__(time)
        self.requester_id = requester_id
        self.queried_id = queried_id
        if status not in ('pending', 'own_id', 'known', 'querying'):
            raise Exception('Status must be one of pending, own_id, known, or'
                            ' querying.')
        self.status = status
        self.completed = status in ('own_id', 'known')


class QuerySent(Event):
    """Event representing a query being sent."""
    def __init__(self, time, sender_id, recipient_id, queried_id):
        super().__init__(time)
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.queried_id = queried_id


class QueryReceived(Event):
    """Event representing a query being received."""
    def __init__(self, time, sender_id, recipient_id, queried_id, status):
        """
        :param status: The status of the query. Must be one of
            * 'own_id': Query for the ID of the recipient. Trivial to answer.
            * 'known': Query for an ID known to the recipient.
            * 'pending': A further query for a relevant ID or prefix is already
                  pending.
            * 'querying': A further query must be sent in order to answer this
                  query.
        """
        super().__init__(time)
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.queried_id = queried_id
        if status not in ('own_id', 'known', 'pending', 'querying'):
            raise Exception('Status must be one of own_id, known, pending, or'
                            ' querying.')
        self.status = status


class ResponseSent(Event):
    """Event representing a response being sent."""
    def __init__(self, time, sender_id, recipient_id, queried_peer_id,
                 queried_ids):
        """
        :param queried_peer_id: The ID of the peer that is the result of the
            query. May be None if the query was unsuccessful.
        :param queried_ids: A set containing all IDs or prefixes for which
            queried_id is a response. I.e., all elements of this set are a
            prefix of queried_id.
        """
        super().__init__(time)
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.queried_peer_id = queried_peer_id
        self.queried_ids = queried_ids


class ResponseReceived(Event):
    """Event representing a response being received."""
    def __init__(self, time, sender_id, recipient_id, queried_peer_id,
                 queried_ids, status):
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
        super().__init__(time)
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


class Timeout(Event):
    def __init__(self, time, sender_id, recipient_id, queried_id, status):
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
        super().__init__(time)
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.queried_id = queried_id
        if status not in ('failure_ultimate', 'failure_retry'):
            raise Exception('Status must be one of failure_ultimate or'
                            ' failure_retry.')
        self.status = status


def print_info_process(env, peers, sync_groups, all_query_groups, peer_graph):
    while True:
        yield env.timeout(10)
        print_info(peers, sync_groups, all_query_groups, peer_graph)


def print_info(peers, sync_groups, all_query_groups, peer_graph):
    print()
    print('sync groups (prefix: {peers}):')
    for pr, sg in sorted(sync_groups.items(), key=lambda t: t[0].uint):
        print('{}: {{{}}}'.format(pr.bin,
                                  ', '.join(str(p.peer_id) for p in sg)))
    print()
    print('query_groups (peer: reputation):')
    for query_group in all_query_groups:
        print('{{{}}}'.format(', '.join(
            str(p.peer_id) + ': ' + '{:.1f}'.format(r)
            for p, r in sorted(query_group.items(), key=lambda t: t[1],
                               reverse=True))))
    print()
    print('missing subprefix coverage per peer:')
    any_missing = False
    for peer in sorted(peers.values(), key=lambda p: p.peer_id.uint):
        if any(n == 0 for n in peer.subprefixes().values()):
            any_missing = True
            missing = set(sp for sp, c in peer.subprefixes().items() if c == 0)
            print('{}: missing prefixes {{{}}}'
                  .format(peer.peer_id, ', '.join((i.bin for i in missing))))
    if not any_missing:
        print('none')
    print()
    print('strongly connected components:')
    from networkx import strongly_connected_components as scc
    for i, comp in enumerate((peer_graph.subgraph(c)
                              for c in scc(peer_graph))):
        print('component {}: {} nodes, diameter {}, degree histogram: {}'
              .format(i, nx.number_of_nodes(comp), nx.diameter(comp),
                      nx.degree_histogram(comp)))
    print()
