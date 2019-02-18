import peer as p
import analyze as an
import util
from util import SortedIterSet
import simpy
import bitstring as bs
import random
import signal
import sys
from collections import OrderedDict


# Patch in a less-than for the Bits class, which is necessary for ordered dicts
# and sets.
bs.Bits.__lt__ = util.bits_lt


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


def decay_reputation(env, all_query_groups, peers, logger, settings):
    decay = settings['decay_per_time_unit'] * settings['decay_timestep']

    def update_query_peer_info(query_peer_info):
        rep = max(0, query_peer_info.reputation - decay)
        query_peer_info.reputation = rep

    while True:
        yield env.timeout(settings['decay_timestep'])
        logger.log(an.ReputationDecay(env.now, decay))
        for query_group in all_query_groups.values():
            for query_peer_info in query_group.infos():
                update_query_peer_info(query_peer_info)
        for peer in peers.values():
            for query_group in peer.query_groups.values():
                for query_peer_info in query_group.infos():
                    update_query_peer_info(query_peer_info)


def write_log(logger, file_name):
    print()
    print('writing log to "{}"'.format(file_name))
    logger.dump(file_name)


def terminate(progress_proc, logger, file_name):
    def handler(_, _2):
        progress_proc.interrupt()
        write_log(logger, file_name)
        sys.exit(0)
    return handler


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Provide a settings file.')
        exit(1)
    settings = util.read_settings(sys.argv[1])
    random.seed(a=settings['rng_seed'], version=2)
    env = simpy.Environment()
    logger = an.Logger(settings)
    peers = OrderedDict()
    sync_groups = OrderedDict()
    all_query_groups = OrderedDict()
    network = util.Network(env, settings)
    for i in range(settings['num_peers']):
        while True:
            peer_id_uint = random.randrange(2 ** settings['id_length'])  
            peer_id = bs.Bits(uint=peer_id_uint, length=settings['id_length'])  
            if peer_id not in peers:
                peer = p.Peer(env, logger, network, peer_id, all_query_groups,
                              settings)
                peers[peer_id] = peer
                sync_groups.setdefault(peer_id[:settings['prefix_length']],
                                       SortedIterSet()).add(peer)
                env.process(request_generator(env, peers, peer))
                logger.log(an.PeerAdd(env.now, peer.peer_id, peer.prefix,
                                      None))
                logger.log(an.UncoveredSubprefixes(
                    env.now, peer.peer_id,
                    SortedIterSet(peer.uncovered_subprefixes()), None))
                break
    for sync_group in sync_groups.values():
        for peer in sync_group:
            for other_peer in sync_group:
                peer.introduce(other_peer.info())
    for peer in peers.values():
        for other_peer in random.sample(list(peers.values()),
                                        settings['num_random_introductions']):
            peer.introduce(other_peer.info())

    print('scheduling queries for missing subprefixes')
    for peer in peers.values():
        peer.find_missing_query_peers()
    until = float('inf')
    if len(sys.argv) > 2:
        until = float(sys.argv[2])
    file_name = settings['log_file_name']
    progress_proc = env.process(util.progress_process(env, 1))
    signal.signal(signal.SIGINT, terminate(progress_proc, logger, file_name))
    print()
    print('running simulation until {}'.format(until))
    env.process(decay_reputation(env, all_query_groups, peers, logger,
                                 settings))
    env.run(until)
    write_log(logger, file_name)
