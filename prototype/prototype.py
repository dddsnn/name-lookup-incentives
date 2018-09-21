import simpy
import bitstring as bs
import random

TRANSMISSION_DELAY = 0.1

class Peer:
    ID_LENGTH = 16
    MAX_QUERY_PEERS = 8
    QUERY_TIMEOUT = 2

    def __init__(self, env, peer_id):
        self.env = env
        self.peer_id = peer_id
        self.prefix = self.peer_id[:2]
        self.query_peers = {}
        self.sync_peers = {}
        self.pending_queries = {}

    def introduce(self, peer):
        if peer.peer_id == self.peer_id:
            return
        if peer.peer_id.startswith(self.prefix):
            self.sync_peers[peer.peer_id] = peer
            return
        for i in range(min(len(self.prefix), len(peer.prefix))):
            if self.prefix[i] != peer.prefix[i]:
                subprefix = peer.prefix[:i+1]
                if peer.prefix in self.query_peers:
                    existing_peers = self.query_peers[subprefix]
                    if len(existing_peers) < Peer.MAX_QUERY_PEERS:
                        existing_peers.append(peer)
                else:
                    self.query_peers[subprefix] = [peer]
                break

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

    def recv_query(self, querying_peer, queried_id):
        if queried_id == self.peer_id:
            self.env.schedule(SendResponse(self.env, self, querying_peer,
                                           queried_id, self),
                                           delay=TRANSMISSION_DELAY)
            return
        if queried_id in self.sync_peers:
            queried_peer = self.sync_peers[queried_id]
            self.env.schedule(SendResponse(self.env, self, querying_peer,
                                           queried_id, queried_peer),
                                           delay=TRANSMISSION_DELAY)
            return
        if queried_id in self.pending_queries:
            # There already is a query for the ID in progress, just note to also
            # send a resonse to this querying peer.
            self.pending_queries[queried_id].querying_peers.add(querying_peer)
            return
        peers_to_query = []
        for (prefix, query_peers) in self.query_peers.items():
            # TODO Start with the longest matching prefix, not just any.
            if queried_id.startswith(prefix):
                peers_to_query.extend(query_peers)
        if len(peers_to_query) == 0:
            print(('{:.2f}: {}: query for {} impossible, no known peer closer'
                   ' to it')
                  .format(self.env.now, self.peer_id, queried_id))
            return
        peer_to_query = peers_to_query.pop(0)
        timeout_proc = self.env.process(self.query_timeout(peer_to_query,
                                                           queried_id))
        self.pending_queries[queried_id] = PendingQuery(self.env.now,
                                                        querying_peer,
                                                        timeout_proc)
        self.env.schedule(SendQuery(self.env, self, peer_to_query, queried_id),
                          delay=TRANSMISSION_DELAY)
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
                self.env.schedule(SendResponse(self.env, self, querying_peer,
                                               queried_id, queried_peer),
                                               delay=TRANSMISSION_DELAY)
            self.pending_queries.pop(queried_id, None)
            return
        if len(pending_query.query_peers) == 0:
            self.pending_queries.pop(queried_id, None)
            print(('{:.2f}: {}: query for {} sent to {} unsuccessful: last'
                   ' known peer didn\'t have the record')
                  .format(self.env.now, self.peer_id, queried_id,
                          responsing_peer.peer_id))
            return
        print(('{:.2f}: {}: unsuccessful response for query for {} from {},'
               ' trying next peer')
              .format(self.env.now, self.peer_id, queried_id,
                      responding_peer.peer_id))
        peer_to_query = pending_query.query_peers.pop(0)
        timeout_proc = self.env.process(self.query_timeout(peer_to_query,
                                                           queried_id))
        pending_query.timeout_proc = timeout_proc
        self.env.schedule(SendQuery(self.env, self, peer_to_query, queried_id),
                          delay=TRANSMISSION_DELAY)

    def query_timeout(self, recipient, queried_id):
        try:
            yield self.env.timeout(Peer.QUERY_TIMEOUT)
        except simpy.Interrupt as e:
            return
        pending_query = self.pending_queries.get(queried_id)
        if pending_query is None:
            return
        if len(pending_query.query_peers) == 0:
            self.pending_queries.pop(queried_id, None)
            print(('{:.2f}: {}: query for {} sent to {} unsuccessful: last'
                   ' known peer timed out')
                  .format(self.env.now, self.peer_id, queried_id,
                          recipient.peer_id))
            return
        print('{:.2f}: {}: query for {} sent to {} timed out, trying next peer'
              .format(self.env.now, self.peer_id, queried_id,
                      recipient.peer_id))
        peer_to_query = pending_query.query_peers.pop(0)
        timeout_proc = self.env.process(self.query_timeout(peer_to_query,
                                                           queried_id))
        pending_query.timeout_proc = timeout_proc
        self.env.schedule(SendQuery(self.env, self, peer_to_query, queried_id),
                          delay=TRANSMISSION_DELAY)

class PendingQuery:
    def __init__(self, start_time, querying_peer, timeout_proc):
        self.start_time = start_time
        self.querying_peers = set((querying_peer,))
        self.timeout_proc = timeout_proc
        self.query_peers = []

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
