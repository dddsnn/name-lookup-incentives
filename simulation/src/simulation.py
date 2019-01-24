import peer as p
import analyze as an
import util
import simpy
import bitstring as bs
import random
import networkx as nx

SUCCESSFUL_QUERY_REWARD = 1
FAILED_QUERY_PENALTY = -2
TIMEOUT_QUERY_PENALTY = -2
DECAY_TIMESTEP = 1
DECAY_PER_TIME_UNIT = 0.1


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
            for query_peer_info in query_group.infos():
                query_peer_info.reputation = max(0, query_peer_info.reputation
                                                 - decay)


if __name__ == '__main__':
    random.seed(a=0, version=2)
    env = simpy.Environment()
    logger = an.Logger()
    peers = {}
    sync_groups = {}
    all_query_groups = set()
    peer_graph = nx.DiGraph()
    network = util.Network(env)
    for i in range(64):
        while True:
            peer_id_uint = random.randrange(2 ** p.Peer.ID_LENGTH)
            peer_id = bs.Bits(uint=peer_id_uint, length=p.Peer.ID_LENGTH)
            if peer_id not in peers:
                peer = p.Peer(env, logger, network, peer_id, all_query_groups,
                              peer_graph)
                peers[peer_id] = peer
                sync_groups.setdefault(peer_id[:p.Peer.PREFIX_LENGTH],
                                       set()).add(peer)
                env.process(request_generator(env, peers, peer))
                break
    for sync_group in sync_groups.values():
        for peer in sync_group:
            for other_peer in sync_group:
                peer.introduce(p.PeerInfo(other_peer.peer_id,
                                          other_peer.prefix,
                                          other_peer.address))
    for peer in peers.values():
        for other_peer in random.sample(list(peers.values()), 8):
            peer.introduce(p.PeerInfo(other_peer.peer_id, other_peer.prefix,
                                      other_peer.address))

    an.print_info(peers, sync_groups, all_query_groups, peer_graph)
    env.process(an.print_info_process(env, peers, sync_groups,
                                      all_query_groups,
                                      peer_graph))
    print('scheduling queries for missing subprefixes')
    for peer in peers.values():
        peer.find_missing_query_peers()
    print()
    print('starting simulation')
    env.process(decay_reputation(env, all_query_groups))
    env.run(until=10)
    logger.dump('log')
