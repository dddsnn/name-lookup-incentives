import simpy
import bitstring as bs
import random
import networkx as nx

TRANSMISSION_DELAY = 0.1
SUCCESSFUL_QUERY_REWARD = 1
FAILED_QUERY_PENALTY = -2
TIMEOUT_QUERY_PENALTY = -2
DECAY_TIMESTEP = 1
DECAY_PER_TIME_UNIT = 0.1

class QueryGroup:
    def __init__(self, members):
        self._members = {m: 0 for m in members}

    def __len__(self):
        return self._members.__len__()

    def __getitem__(self, key):
        return self._members.__getitem__(key)

    def __setitem__(self, key, value):
        return self._members.__setitem__(key, value)

    def __delitem__(self, key):
        return self._members.__delitem__(key)

    def __iter__(self):
        return self._members.__iter__()

    def __contains__(self, key):
        return self._members.__contains__(key)

    def members(self):
        return self._members.keys()

    def items(self):
        return self._members.items()

    def update(self, *args):
        return self._members.update(*args)

class Peer:
    ID_LENGTH = 16
    PREFIX_LENGTH = 4
    MIN_DESIRED_QUERY_PEERS = 2
    MAX_DESIRED_GROUP_SIZE = 16
    QUERY_TIMEOUT = 2
    COMPLETED_QUERY_RETENTION_TIME = 100

    def __init__(self, env, peer_id, all_query_groups, peer_graph):
        self.env = env
        self.peer_id = peer_id
        self.all_query_groups = all_query_groups
        self.peer_graph = peer_graph
        self.prefix = self.peer_id[:Peer.PREFIX_LENGTH]
        self.query_groups = set()
        self.sync_peers = {}
        self.pending_queries = {}
        self.completed_queries = {}

        # Add self-loop to the peer graph so that networkx considers the node
        # for this peer a component.
        self.peer_graph.add_edge(self, self)

    def knows(self, peer):
        return (peer.peer_id == self.peer_id or peer.peer_id in self.sync_peers
                or peer.peer_id in
                    (i for g in peer.query_groups for i in g.members()))

    def join_group_with(self, peer):
        # TODO Instead of just adding self or others to groups, send join
        # requests or invites.
        # Attempt to join one of the peer's groups.
        for query_group in peer.query_groups:
            # TODO Pick the most useful out of these groups, not just any.
            if len(query_group) < Peer.MAX_DESIRED_GROUP_SIZE:
                query_group[self] = 0
                self.query_groups.add(query_group)
                return
        # Attempt to add the peer to one of my groups.
        for query_group in self.query_groups:
            # TODO Pick the most useful out of these groups, not just any.
            if len(query_group) < Peer.MAX_DESIRED_GROUP_SIZE:
                query_group[peer] = 0
                peer.query_groups.add(query_group)
                return
        # Create a new query group.
        query_group = QueryGroup((self, peer))
        self.all_query_groups.add(query_group)
        self.query_groups.add(query_group)
        peer.query_groups.add(query_group)

    def find_missing_query_peers(self):
        """
        Find peers to cover prefixes for which there are no known peers.

        It's not enough in this case to simply query for a prefix, because there
        may not be any known peer closer to it. Instead, all peers are queried
        by calling act_query() directly with query_all set to True. This way,
        sync peers will be queried as well.
        """
        for subprefix in (sp for sp, c in self.subprefixes().items() if c == 0):
            self.act_query(self, subprefix, True)

    def introduce(self, peer):
        if self.knows(peer):
            return
        if peer.peer_id.startswith(self.prefix):
            self.sync_peers[peer.peer_id] = peer
            self.peer_graph.add_edge(self, peer)
            return
        for sp, count in self.subprefixes().items():
            if (peer.prefix.startswith(sp)
                    and count < Peer.MIN_DESIRED_QUERY_PEERS):
                self.join_group_with(peer)
                self.peer_graph.add_edge(self, peer)

    def subprefixes(self):
        """
        Map each subprefix to the number of known peers serving it.

        A subprefix is a k-bit bitstring with k > 0, k <= len(self.prefix), in
        which the first k-1 bits are equal to the first k-1 bits in self.prefix,
        and the k-th bit is inverted.

        The dictionary that is returned maps each of the possible
        len(self.prefix) such subprefixes to the number of peers this peer knows
        who can serve it.
        """
        # TODO Cache.
        subprefixes = {}
        for i in range(len(self.prefix)):
            subprefixes[self.prefix[:i] + ~(self.prefix[i:i+1])] = set()
        for query_peer in self.known_query_peers():
            for sp in subprefixes.keys():
                if query_peer.prefix.startswith(sp):
                    subprefixes[sp].add(query_peer)
        return {sp: len(qps) for (sp, qps) in subprefixes.items()}

    def handle_request(self, queried_id):
        print('{:.2f}: {}: request for {} - '.format(self.env.now, self.peer_id,
                                                     queried_id), end='')
        for pending_queried_id in self.pending_queries:
            if pending_queried_id.startswith(queried_id):
                print('request for matching ID {} is already pending'
                      .format(pending_queried_id))
                return
        if queried_id == self.peer_id:
            print('request for own ID')
            return
        for sync_peer_id in self.sync_peers:
            if sync_peer_id.startswith(queried_id):
                # TODO Actually send query in case queried_id is a prefix. This
                # behavior is useless for the purpose of finding more sync
                # peers.
                print('found matching ID {} in sync peers'.format(sync_peer_id))
                return
        print('sending query')
        self.recv_query(self, queried_id)

    def send_query(self, queried_id, pending_query):
        """
        Send a query for an ID.

        Takes the first element of pending_query.peers_to_query as recipient,
        therefore this list must not be empty. Also starts a timeout process and
        stores it in pending_query.timeout_proc.
        """
        peer_to_query = pending_query.peers_to_query.pop(0)
        timeout_proc = self.env.process(self.query_timeout(peer_to_query,
                                                           queried_id))
        pending_query.timeout_proc = timeout_proc
        pending_query.queries_sent[peer_to_query] = self.env.now
        self.env.schedule(SendQuery(self.env, self, peer_to_query, queried_id),
                          delay=TRANSMISSION_DELAY)

    def send_response(self, recipient, queried_ids, queried_peer, delay=0):
        if recipient != self:
            delay += TRANSMISSION_DELAY
        self.env.schedule(SendResponse(self.env, self, recipient, queried_ids,
                                       queried_peer), delay=delay)

    def recv_query(self, querying_peer, queried_id):
        # TODO In case of a query for a partial ID, randomize which peer is
        # returned.
        if self.peer_id.startswith(queried_id):
            self.act_query_self(querying_peer, queried_id)
            return
        for sync_peer_id, sync_peer in self.sync_peers.items():
            if sync_peer_id.startswith(queried_id):
                self.act_query_sync(querying_peer, queried_id, sync_peer)
                return
        for pending_query_id, pending_query in self.pending_queries.items():
            if pending_query_id.startswith(queried_id):
                # There already is a query for a fitting ID in progress, just
                # note to also send a resonse to this querying peer.
                pending_query.querying_peers.setdefault(querying_peer,
                    set()).add(queried_id)
                return
        self.act_query(querying_peer, queried_id)

    def recv_response(self, responding_peer, queried_ids, queried_peer):
        for queried_id in queried_ids:
            pending_query = self.pending_queries.get(queried_id)
            if pending_query is not None:
                break
        for qid in queried_ids:
            # Only one of the queried IDs for which we receive a response should
            # have a pending query on record (namely the longest one). The other
            # IDs should be part of that record, but not the key for it.
            assert qid == queried_id or qid not in self.pending_queries
        if pending_query is None:
            self.check_completed_queries(responding_peer, queried_id,
                                         queried_peer)
            return
        if responding_peer not in pending_query.queries_sent:
            self.check_completed_queries(responding_peer, queried_id,
                                         queried_peer)
            return
        pending_query.timeout_proc.interrupt()
        time_sent = pending_query.queries_sent.pop(responding_peer)
        time_taken = self.env.now - time_sent
        if queried_peer is not None:
            self.act_response_success(pending_query, responding_peer,
                                      queried_id, queried_peer, time_taken)
            self.pending_queries.pop(queried_id, None)
            self.archive_completed_query(pending_query, queried_id)
            self.introduce(queried_peer)
            return
        if len(pending_query.peers_to_query) == 0:
            self.act_response_failure(pending_query, responding_peer,
                                      queried_id, time_taken)
            self.pending_queries.pop(queried_id, None)
            self.archive_completed_query(pending_query, queried_id)
            return
        self.act_response_retry(pending_query, responding_peer, queried_id)

    def check_completed_queries(self, responding_peer, queried_id,
                                queried_peer):
        completed_queries = self.completed_queries.get(queried_id)
        if completed_queries is None:
            return
        for i, pending_query in enumerate(completed_queries):
            pending_query.queries_sent.pop(responding_peer, None)
            if pending_query is None:
                continue
            if queried_peer is not None:
                self.act_rep_success(responding_peer)
            else:
                self.act_rep_failure(responding_peer)
            break
        else:
            return
        if len(pending_query.queries_sent) == 0:
            completed_queries.pop(i)
        if len(completed_queries) == 0:
            self.completed_queries.pop(queried_id, None)

    def archive_completed_query(self, pending_query, queried_id):
        if len(pending_query.queries_sent) == 0:
            return
        completed_queries = self.completed_queries.get(queried_id)
        if completed_queries is not None:
            completed_queries.append(pending_query)
        else:
            self.completed_queries[queried_id] = [pending_query]
        self.env.process(self.remove_completed_query(pending_query, queried_id))

    def remove_completed_query(self, pending_query, queried_id):
        yield env.timeout(Peer.COMPLETED_QUERY_RETENTION_TIME)
        completed_queries = self.completed_queries.get(queried_id)
        if completed_queries is None:
            return
        try:
            completed_queries.remove(pending_query)
        except ValueError:
            pass
        if len(completed_queries) == 0:
            self.completed_queries.pop(queried_id, None)

    def query_timeout(self, recipient, queried_id):
        timeout = Peer.QUERY_TIMEOUT + self.act_expect_delay(recipient)
        try:
            yield self.env.timeout(timeout)
        except simpy.Interrupt as e:
            return
        pending_query = self.pending_queries.get(queried_id)
        if pending_query is None:
            return
        if len(pending_query.peers_to_query) == 0:
            self.act_timeout_failure(pending_query, recipient, queried_id)
            self.pending_queries.pop(queried_id, None)
            self.archive_completed_query(pending_query, queried_id)
            return
        self.act_timeout_retry(pending_query, recipient, queried_id)

    def peer_query_groups(self, peer):
        """Iterate query groups that contain a peer."""
        # TODO Maintain a map of all peers so we don't have to iterate over all
        # groups.
        return (g for g in self.query_groups if peer in g.members())

    def known_query_peers(self):
        """
        Iterate known query peers.

        Not guaranteed to be unique, will contain peers multiple times if they
        share multiple query groups.
        """
        return (p for g in self.query_groups for p in g.members())

    def select_peers_to_query(self, queried_id):
        """
        List peers to send a query to.

        Creates a list containing all peers that should be queried for the given
        ID. These are all known peers who are closer to that ID, i.e. whose
        bit_overlap() is larger than for this peer.

        The list is sorted by the overlap, with the largest, i.e. the closest to
        the ID (and thus most useful) first.
        """
        own_overlap = bit_overlap(self.prefix, queried_id)
        peers_to_query = []
        for query_peer in set(self.known_query_peers()):
            # TODO Range queries for performance.
            if bit_overlap(query_peer.prefix, queried_id) > own_overlap:
                peers_to_query.append(query_peer)
        # TODO Instead of sorting for the longest prefix match, use a heap to
        # begin with.
        # TODO Also consider reputation in the query group when selecting a peer
        # to query.
        peers_to_query.sort(key=lambda p: bit_overlap(p.prefix, queried_id),
                            reverse=True)
        return peers_to_query

    def act_query_self(self, querying_peer, queried_id):
        self.act_query_self_default(querying_peer, queried_id)

    def act_query_sync(self, querying_peer, queried_id, sync_peer):
        self.act_query_sync_default(querying_peer, queried_id, sync_peer)

    def act_query(self, querying_peer, queried_id, query_all=False):
        self.act_query_default(querying_peer, queried_id, query_all)

    def act_response_success(self, pending_query, responding_peer, queried_id,
                             queried_peer, time_taken):
        self.act_response_success_default(pending_query, responding_peer,
                                          queried_id, queried_peer, time_taken)

    def act_response_failure(self, pending_query, responding_peer, queried_id,
                             time_taken):
        self.act_response_failure_default(pending_query, responding_peer,
                                          queried_id, time_taken)

    def act_response_retry(self, pending_query, responding_peer, queried_id):
        self.act_response_retry_default(pending_query, responding_peer,
                                        queried_id)

    def act_timeout_failure(self, pending_query, recipient, queried_id):
        self.act_timeout_failure_default(pending_query, recipient, queried_id)

    def act_timeout_retry(self, pending_query, recipient, queried_id):
        self.act_timeout_retry_default(pending_query, recipient, queried_id)

    def act_rep_success(self, peer):
        self.act_rep_success_default(peer)

    def act_rep_failure(self, peer):
        self.act_rep_failure_default(peer)

    def act_rep_timeout(self, peer):
        self.act_rep_timeout_default(peer)

    def act_decide_delay(self, querying_peer):
        return self.act_decide_delay_default(querying_peer)

    def act_expect_delay(self, peer_to_query):
        return self.act_expect_delay_default(peer_to_query)

    def act_query_self_default(self, querying_peer, queried_id):
        delay = self.act_decide_delay(querying_peer)
        self.send_response(querying_peer, set((queried_id,)), self, delay=delay)

    def act_query_sync_default(self, querying_peer, queried_id, sync_peer):
        delay = self.act_decide_delay(querying_peer)
        self.send_response(querying_peer, set((queried_id,)), sync_peer,
                           delay=delay)

    def act_query_default(self, querying_peer, queried_id, query_all=False):
        """
        Act when a query is necessary.

        This method implements the "good" default behavior. A list of peers is
        created that will be queried and sorted based on how close they are to
        the queried ID. A PendingQuery is created with these peers and used to
        send a query.

        By default, the peers that will be queried are only ones whose prefix
        has a larger overlap with the queried ID than this peer, i.e. who are
        closer to the target ID. However, if query_all is True, all known peers,
        including sync peers, will be queried.
        """
        if query_all:
            peers_to_query = (list(self.known_query_peers())
                             + list(self.sync_peers.values()))
            peers_to_query.sort(key=lambda p: bit_overlap(p.prefix, queried_id),
                                reverse=True)
        else:
            peers_to_query = self.select_peers_to_query(queried_id)
        if len(peers_to_query) == 0:
            print(('{:.2f}: {}: query for {} impossible, no known peer closer'
                   ' to it')
                  .format(self.env.now, self.peer_id, queried_id))
            return
        pending_query = PendingQuery(self.env.now, querying_peer, queried_id,
                                     peers_to_query)
        self.pending_queries[queried_id] = pending_query
        self.send_query(queried_id, pending_query)
        # TODO Send queries to multiple peers at once.

    def act_response_success_default(self, pending_query, responding_peer,
                                     queried_id, queried_peer, time_taken):
        queried_ids = pending_query.querying_peers.pop(self, None)
        total_time = self.env.now - pending_query.start_time
        if queried_ids is not None:
            print(('{:.2f}: {}: successful response for query for {} from'
                   ' {} after {:.2f}, total time {:.2f}')
                  .format(self.env.now, self.peer_id,
                          format_ids(queried_id, queried_ids),
                          responding_peer.peer_id, time_taken, total_time))
        for querying_peer, queried_ids in pending_query.querying_peers.items():
            delay = max(self.act_decide_delay(querying_peer) - total_time, 0)
            self.send_response(querying_peer, queried_ids, queried_peer,
                               delay=delay)
        self.act_rep_success(responding_peer)

    def act_response_failure_default(self, pending_query, responding_peer,
                                     queried_id, time_taken):
        queried_ids = pending_query.querying_peers.get(self)
        total_time = self.env.now - pending_query.start_time
        if queried_ids is not None:
            queried_ids = pending_query.querying_peers[self]
            print(('{:.2f}: {}: unsuccessful query for {} last sent to {}:'
                   ' unsuccessful response from last known peer after {:.2f},'
                   ' total time {:.2f}')
                  .format(self.env.now, self.peer_id,
                          format_ids(queried_id, queried_ids),
                          responding_peer.peer_id, time_taken, total_time))
        for querying_peer, queried_ids in pending_query.querying_peers.items():
            delay = max(self.act_decide_delay(querying_peer) - total_time, 0)
            self.send_response(querying_peer, queried_ids, None, delay=delay)
        self.act_rep_failure(responding_peer)

    def act_response_retry_default(self, pending_query, responding_peer,
                                   queried_id):
        queried_ids = pending_query.querying_peers.get(self)
        if queried_ids is not None:
            queried_ids = pending_query.querying_peers[self]
            print(('{:.2f}: {}: unsuccessful response for query for {} from {},'
                   ' trying next peer')
                  .format(self.env.now, self.peer_id, format_ids(queried_id,
                                                                 queried_ids),
                          responding_peer.peer_id))
        self.send_query(queried_id, pending_query)
        self.act_rep_failure(responding_peer)

    def act_timeout_failure_default(self, pending_query, recipient, queried_id):
        queried_ids = pending_query.querying_peers.get(self)
        total_time = self.env.now - pending_query.start_time
        if queried_ids is not None:
            queried_ids = pending_query.querying_peers[self]
            print(('{:.2f}: {}: unsuccessful query for {} last sent to {}:'
                   ' last known peer timed out, total time {:.2f}')
                  .format(self.env.now, self.peer_id,
                          format_ids(queried_id, queried_ids),
                          recipient.peer_id, total_time))
        for querying_peer, queried_ids in pending_query.querying_peers.items():
            delay = max(self.act_decide_delay(querying_peer) - total_time, 0)
            self.send_response(querying_peer, queried_ids, None, delay=delay)
        self.act_rep_timeout(recipient)

    def act_timeout_retry_default(self, pending_query, recipient, queried_id):
        queried_ids = pending_query.querying_peers.get(self)
        if queried_ids is not None:
            queried_ids = pending_query.querying_peers[self]
            print('{:.2f}: {}: timed out response for query for {} sent to {},'
                  ' trying next peer'
                  .format(self.env.now, self.peer_id,
                          format_ids(queried_id, queried_ids),
                          recipient.peer_id))
        self.send_query(queried_id, pending_query)
        self.act_rep_timeout(recipient)

    def act_rep_success_default(self, peer):
        for query_group in self.peer_query_groups(peer):
            rep = max(query_group[peer] + SUCCESSFUL_QUERY_REWARD, 0)
            query_group[peer] = rep

    def act_rep_failure_default(self, peer):
        for query_group in self.peer_query_groups(peer):
            rep = max(query_group[peer] + FAILED_QUERY_PENALTY, 0)
            query_group[peer] = rep

    def act_rep_timeout_default(self, peer):
        for query_group in self.peer_query_groups(peer):
            rep = max(query_group[peer] + TIMEOUT_QUERY_PENALTY, 0)
            query_group[peer] = rep

    def act_decide_delay_default(self, querying_peer):
        # TODO Handle the case if querying_peer is not in a query group. That
        # can happen if a sync peer is sending out a prefix query to all known
        # peers in order to complete his subprefix connectivity. Currently, when
        # computing max_rep, the default=0 treats queries from sync_peers as
        # though they are to be maximally penalized. Obviously, there needs to
        # be a reputation mechanism for sync peers that this method honors once
        # the sync group management is actually handled by the peers via
        # messages.
        max_rep = max((g[querying_peer]
                      for g in self.peer_query_groups(querying_peer)),
                      default=0)
        return min(max(10 - max_rep, 0), 10)

    def act_expect_delay_default(self, peer_to_query):
        # TODO Handle the case where peer_to_query is a sync_peer. See comment
        # in act_decide_delay_default().
        max_rep = max((g[self]
                       for g in self.peer_query_groups(peer_to_query)),
                      default=0)
        return min(max(10 - max_rep, 0), 10)

class PendingQuery:
    def __init__(self, start_time, querying_peer, queried_id, peers_to_query,
                 timeout_proc=None):
        self.start_time = start_time
        self.querying_peers = {querying_peer: set((queried_id,))}
        self.timeout_proc = timeout_proc
        self.peers_to_query = peers_to_query
        self.queries_sent = {}

class SendQuery(simpy.events.Event):
    def __init__(self, env, sender, recipient, queried_id):
        super().__init__(env)
        self.ok = True
        self.sender = sender
        self.recipient = recipient
        self.queried_id = queried_id
        self.callbacks.append(SendQuery.action)

    def action(self):
        self.recipient.recv_query(self.sender, self.queried_id)

class SendResponse(simpy.events.Event):
    def __init__(self, env, sender, recipient, queried_ids, queried_peer):
        super().__init__(env)
        self.ok = True
        self.sender = sender
        self.recipient = recipient
        self.queried_ids = queried_ids
        self.queried_peer = queried_peer
        self.callbacks.append(SendResponse.action)

    def action(self):
        self.recipient.recv_response(self.sender, self.queried_ids,
                                     self.queried_peer)

def bit_overlap(a, b):
    """Calculate the number of bits at the start that are the same."""
    m = min(len(a), len(b))
    return len(next((a[:m] ^ b[:m]).split('0b1', count=1)))

def request_generator(env, peers, peer):
    while True:
        if len(peers) <= 1:
            break
        while True:
            query_peer_id = random.sample(peers.keys(), 1)[0]
            if query_peer_id != peer.peer_id:
                break
        peer.handle_request(query_peer_id)
        yield env.timeout(1)

def decay_reputation(env, all_query_groups):
    while True:
        yield env.timeout(DECAY_TIMESTEP)
        decay = DECAY_PER_TIME_UNIT * DECAY_TIMESTEP
        for query_group in all_query_groups:
            query_group.update(
                {p: max(0, r - decay) for p, r in query_group.items()}
            )

def format_ids(queried_id, queried_ids):
    """Pretty-print an ID and set of prefixes."""
    s = str(queried_id)
    if len(queried_ids) > 1:
        s += ' ({' + ', '.join((str(qid) for qid in queried_ids)) + '})'
    return s

def print_info_process(env, peers, sync_groups, all_query_groups):
    while True:
        yield env.timeout(10)
        print_info(peers, sync_groups, all_query_groups)

def print_info(peers, sync_groups, all_query_groups):
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
            for p, r in sorted(query_group.items(), key=lambda t:t[1],
                               reverse=True)))
        )
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
    for i, comp in enumerate((peer_graph.subgraph(c) for c in scc(peer_graph))):
        print('component {}: {} nodes, diameter {}, degree histogram: {}'
              .format(i, nx.number_of_nodes(comp), nx.diameter(comp),
                       nx.degree_histogram(comp)))
    print()

if __name__ == '__main__':
    random.seed(a=0, version=2)
    env = simpy.Environment()
    peers = {}
    sync_groups = {}
    all_query_groups = set()
    peer_graph = nx.DiGraph()
    for i in range(64):
        while True:
            peer_id_uint = random.randrange(2 ** Peer.ID_LENGTH)
            peer_id = bs.Bits(uint=peer_id_uint, length = Peer.ID_LENGTH)
            if peer_id not in peers:
                peer = Peer(env, peer_id, all_query_groups, peer_graph)
                peers[peer_id] = peer
                sync_groups.setdefault(peer_id[:Peer.PREFIX_LENGTH],
                                       set()).add(peer)
                env.process(request_generator(env, peers, peer))
                break
    for sync_group in sync_groups.values():
        for peer in sync_group:
            for other_peer in sync_group:
                peer.introduce(other_peer)
    for peer in peers.values():
        for other_peer in random.sample(list(peers.values()), 8):
            peer.introduce(other_peer)

    print_info(peers, sync_groups, all_query_groups)
    env.process(print_info_process(env, peers, sync_groups, all_query_groups))
    print('scheduling queries for missing subprefixes')
    for peer in peers.values():
        peer.find_missing_query_peers()
    print()
    print('starting simulation')
    env.process(decay_reputation(env, all_query_groups))
    env.run(until=float('inf'))
