import peer as p
import analyze as an
import util
import simpy
import bitstring as bs
import random

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


def decay_reputation(env, all_query_groups, logger):
    while True:
        yield env.timeout(DECAY_TIMESTEP)
        decay = DECAY_PER_TIME_UNIT * DECAY_TIMESTEP
        logger.log(an.ReputationDecay(env.now, decay))
        for query_group in all_query_groups.values():
            for query_peer_info in query_group.infos():
                rep = max(0, query_peer_info.reputation - decay)
                query_peer_info.reputation = rep


if __name__ == '__main__':
    random.seed(a=0, version=2)
    env = simpy.Environment()
    logger = an.Logger()
    peers = {}
    sync_groups = {}
    all_query_groups = {}
    network = util.Network(env)
    for i in range(64):
        while True:
            peer_id_uint = random.randrange(2 ** p.Peer.ID_LENGTH)
            peer_id = bs.Bits(uint=peer_id_uint, length=p.Peer.ID_LENGTH)
            if peer_id not in peers:
                peer = p.Peer(env, logger, network, peer_id, all_query_groups)
                peers[peer_id] = peer
                sync_groups.setdefault(peer_id[:p.Peer.PREFIX_LENGTH],
                                       set()).add(peer)
                env.process(request_generator(env, peers, peer))
                logger.log(an.PeerAdd(env.now, peer.peer_id, peer.prefix,
                                      None))
                logger.log(an.UncoveredSubprefixes(
                    env.now, peer.peer_id, set(peer.uncovered_subprefixes()),
                    None))
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

    an.print_info(logger, 0)
    env.process(an.print_info_process(env, logger))
    print('scheduling queries for missing subprefixes')
    for peer in peers.values():
        peer.find_missing_query_peers()
    print()
    print('starting simulation')
    env.process(decay_reputation(env, all_query_groups, logger))
    env.run(until=10)
    logger.dump('log')
