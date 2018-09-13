import simpy
import bitstring as bs
import random

class Peer:
    ID_LENGTH = 16

    def __init__(self, env, peer_id):
        self.env = env
        self.peer_id = peer_id
        self.peers = {}

    def introduce(self, peer):
        if peer.peer_id == self.peer_id:
            return
        self.peers[peer.peer_id] = peer

    def handle_request(self, query_peer_id):
        print('{} at time {}: handling request for {}'.format(self.peer_id,
                                                              env.now,
                                                              query_peer_id))

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
