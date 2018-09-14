import simpy
import bitstring as bs
import random

class Peer:
    ID_LENGTH = 16
    MAX_QUERY_PEERS = 8

    def __init__(self, env, peer_id):
        self.env = env
        self.peer_id = peer_id
        self.prefix = self.peer_id[:2]
        self.query_peers = {}
        self.sync_peers = {}

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

    def handle_request(self, query_id):
        print('{}:{}: request for {} - '.format(self.env.now, self.peer_id,
                                             query_id), end='')
        if query_id in self.sync_peers:
            peer = self.sync_peers[query_id]
            print('found in sync peers')
            return
        for (prefix, query_peers) in self.query_peers.items():
            # TODO Find the longest matching prefix, not just any.
            if query_id.startswith(prefix):
                for query_peer in query_peers:
                    print('querying {} ... '.format(query_peer.peer_id), end='')
                    peer = query_peer.query(query_id)
                    if peer is None:
                        print('failed')
                    else:
                        print('success')
                        break
                break
        else:
            print('no known peer with prefix matching {}'.format(query_id))

    def query(self, query_id):
        # TODO
        return None

def request_generator(peers, peer):
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
                env.process(request_generator(peers, peer))
                break
    for peer in peers.values():
        for other_peer in peers.values():
            peer.introduce(other_peer)
    env.run(until=float('inf'))
