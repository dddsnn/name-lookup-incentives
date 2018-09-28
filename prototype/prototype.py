import simpy
import bitstring as bs
import random

TRANSMISSION_DELAY = 0.1

class QueryGroup:
    def __init__(self, members):
        self.members = set(members)

class Peer:
    ID_LENGTH = 16
    PREFIX_LENGTH = 2
    MIN_DESIRED_QUERY_PEERS = 2
    MAX_DESIRED_GROUP_SIZE = 16
    QUERY_TIMEOUT = 2

    def __init__(self, env, peer_id):
        self.env = env
        self.peer_id = peer_id
        self.prefix = self.peer_id[:Peer.PREFIX_LENGTH]
        self.query_groups = set()
        self.sync_peers = {}
        self.pending_queries = {}

    # TODO Method to evaluate if there is at least one peer for every subprefix
    # in the query groups. If not, query for peers with those prefixes (requires
    # queries for partial IDs).

    def knows(self, peer):
        return (peer.peer_id == self.peer_id or peer.peer_id in self.sync_peers
                or peer.peer_id in
                    (i for g in peer.query_groups for i in g.members))

    def join_group_with(self, peer):
        # TODO Instead of just adding self or others to groups, send join
        # requests or invites.
        if len(peer.query_groups) > 0:
            # TODO Pick the most useful out of these groups, not just any.
            for query_group in peer.query_groups:
                if len(query_group.members) < Peer.MAX_DESIRED_GROUP_SIZE:
                    query_group.members.add(self)
                    self.query_groups.add(query_group)
                    break
        else:
            query_group = QueryGroup((self, peer))
            self.query_groups.add(query_group)
            peer.query_groups.add(query_group)

    def introduce(self, peer):
        if self.knows(peer):
            return
        if peer.peer_id.startswith(self.prefix):
            self.sync_peers[peer.peer_id] = peer
            return
        for sp, count in self.subprefixes().items():
            if (peer.prefix.startswith(sp)
                    and count < Peer.MIN_DESIRED_QUERY_PEERS):
                self.join_group_with(peer)

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
        for query_peer in (p for g in self.query_groups for p in g.members):
            for sp in subprefixes.keys():
                if query_peer.prefix.startswith(sp):
                    subprefixes[sp].add(query_peer)
        return {sp: len(qps) for (sp, qps) in subprefixes.items()}

    def handle_request(self, queried_id):
        print('{:.2f}: {}: request for {} - '.format(self.env.now, self.peer_id,
                                                     queried_id), end='')
        if queried_id in self.pending_queries:
            print('request for this ID is already pending')
            return
        if queried_id == self.peer_id:
            print('request for own ID')
            return
        if queried_id in self.sync_peers:
            print('found in sync peers')
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
        self.env.schedule(SendQuery(self.env, self, peer_to_query, queried_id),
                          delay=TRANSMISSION_DELAY)

    def send_response(self, recipient, queried_id, queried_peer):
        self.env.schedule(SendResponse(self.env, self, recipient, queried_id,
                                       queried_peer), delay=TRANSMISSION_DELAY)

    def recv_query(self, querying_peer, queried_id):
        if queried_id == self.peer_id:
            self.send_response(querying_peer, queried_id, self)
            return
        if queried_id in self.sync_peers:
            queried_peer = self.sync_peers[queried_id]
            self.send_response(querying_peer, queried_id, queried_peer)
            return
        if queried_id in self.pending_queries:
            # There already is a query for the ID in progress, just note to also
            # send a resonse to this querying peer.
            self.pending_queries[queried_id].querying_peers.add(querying_peer)
            return
        own_overlap = bit_overlap(self.prefix, queried_id)
        peers_to_query = []
        for query_peer in (qp for qg in self.query_groups for qp in qg.members):
            # TODO Range queries for performance.
            if bit_overlap(query_peer.prefix, queried_id) > own_overlap:
                peers_to_query.append(query_peer)
        # TODO Instead of sorting for the longest prefix match, use a heap to
        # begin with.
        peers_to_query.sort(key=lambda p: bit_overlap(p.prefix, queried_id),
                            reverse=True)
        if len(peers_to_query) == 0:
            print(('{:.2f}: {}: query for {} impossible, no known peer closer'
                   ' to it')
                  .format(self.env.now, self.peer_id, queried_id))
            return
        pending_query = PendingQuery(self.env.now, querying_peer,
                                     peers_to_query)
        self.pending_queries[queried_id] = pending_query
        self.send_query(queried_id, pending_query)
        # TODO Send queries to multiple peers at once.

    def recv_response(self, responding_peer, queried_id, queried_peer):
        # TODO Check that the response is coming from the peer to whom the query
        # was sent in the first place. This is important later on, when the
        # correct peer needs to be credited.
        pending_query = self.pending_queries.get(queried_id)
        if pending_query is None:
            return
        pending_query.timeout_proc.interrupt()
        if queried_peer is not None:
            if self in pending_query.querying_peers:
                pending_query.querying_peers.remove(self)
                print(('{:.2f}: {}: successful response for query for {} from'
                       ' {} after {:.2f}')
                      .format(self.env.now, self.peer_id, queried_id,
                              responding_peer.peer_id,
                              self.env.now - pending_query.start_time))
            for querying_peer in pending_query.querying_peers:
                self.send_response(querying_peer, queried_id, queried_peer)
            self.pending_queries.pop(queried_id, None)
            return
        if len(pending_query.peers_to_query) == 0:
            print(('{:.2f}: {}: query for {} sent to {} unsuccessful: last'
                   ' known peer didn\'t have the record')
                  .format(self.env.now, self.peer_id, queried_id,
                          responsing_peer.peer_id))
            for querying_peer in pending_query.querying_peers:
                self.send_response(querying_peer, queried_id, None)
            self.pending_queries.pop(queried_id, None)
            return
        print(('{:.2f}: {}: unsuccessful response for query for {} from {},'
               ' trying next peer')
              .format(self.env.now, self.peer_id, queried_id,
                      responding_peer.peer_id))
        self.send_query(queried_id, pending_query)

    def query_timeout(self, recipient, queried_id):
        try:
            yield self.env.timeout(Peer.QUERY_TIMEOUT)
        except simpy.Interrupt as e:
            return
        pending_query = self.pending_queries.get(queried_id)
        if pending_query is None:
            return
        if len(pending_query.peers_to_query) == 0:
            print(('{:.2f}: {}: query for {} sent to {} unsuccessful: last'
                   ' known peer timed out')
                  .format(self.env.now, self.peer_id, queried_id,
                          recipient.peer_id))
            for querying_peer in pending_query.querying_peers:
                self.send_response(querying_peer, queried_id, None)
            self.pending_queries.pop(queried_id, None)
            return
        print('{:.2f}: {}: query for {} sent to {} timed out, trying next peer'
              .format(self.env.now, self.peer_id, queried_id,
                      recipient.peer_id))
        self.send_query(queried_id, pending_query)

class PendingQuery:
    def __init__(self, start_time, querying_peer, peers_to_query,
                 timeout_proc=None):
        self.start_time = start_time
        self.querying_peers = set((querying_peer,))
        self.timeout_proc = timeout_proc
        self.peers_to_query = peers_to_query

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
    def __init__(self, env, sender, recipient, queried_id, queried_peer):
        super().__init__(env)
        self.ok = True
        self.sender = sender
        self.recipient = recipient
        self.queried_id = queried_id
        self.queried_peer = queried_peer
        self.callbacks.append(SendResponse.action)

    def action(self):
        self.recipient.recv_response(self.sender, self.queried_id,
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

if __name__ == '__main__':
    random.seed(a=0, version=2)
    env = simpy.Environment()
    peers = {}
    for i in range(10):
        while True:
            peer_id_uint = random.randrange(2 ** Peer.ID_LENGTH)
            peer_id = bs.Bits(uint=peer_id_uint, length = Peer.ID_LENGTH)
            if peer_id not in peers:
                peer = Peer(env, peer_id)
                peers[peer_id] = peer
                env.process(request_generator(env, peers, peer))
                break
    for peer in peers.values():
        for other_peer in peers.values():
            peer.introduce(other_peer)
    env.run(until=float('inf'))
