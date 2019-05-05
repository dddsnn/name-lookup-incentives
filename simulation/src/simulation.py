import peer as p
import analyze as an
import util
import simpy
import bitstring as bs
import random
import signal
import sys
import collections as cl
import math
import copy
import itertools as it


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


def even_sync_groups_peer_id_batches(settings):
    peer_batches = settings['peer_batches']
    total_num_peers = sum(n for _, n in peer_batches)
    if total_num_peers > 2 ** settings['id_length']:
        raise Exception('IDs are too short for the number of peers.')
    if (math.log2(total_num_peers) % 1
            or total_num_peers < 2 ** settings['prefix_length']):
        raise Exception('For even sync groups, the number of peers must be a'
                        ' power of 2 and greater or equal the number of sync'
                        ' groups.')
    all_peer_ids = []
    num_sync_groups = 2 ** settings['prefix_length']
    num_peers_per_sync_group = total_num_peers // num_sync_groups
    suffix_length = settings['id_length'] - settings['prefix_length']
    for _ in range(num_peers_per_sync_group):
        for i in range(num_sync_groups):
            prefix = bs.Bits(uint=i, length=settings['prefix_length'])
            while True:
                suffix_uint = random.randrange(2 ** suffix_length)
                suffix = bs.Bits(uint=suffix_uint, length=suffix_length)
                peer_id = prefix + suffix
                if peer_id not in all_peer_ids:
                    all_peer_ids.append(peer_id)
                    break
    peer_id_batches = []
    peer_id_iter = iter(all_peer_ids)
    for time, num_peers in peer_batches:
        peer_id_batches.append((time, it.islice(peer_id_iter, num_peers)))
    return peer_id_batches, all_peer_ids


def random_peer_id_batches(settings):
    peer_batches = settings['peer_batches']
    total_num_peers = sum(n for _, n in peer_batches)
    if total_num_peers > 2 ** settings['id_length']:
        raise Exception('IDs are too short for the number of peers.')
    if (settings['ensure_non_empty_sync_groups']
            and total_num_peers < 2 ** settings['prefix_length']):
        raise Exception('There are not enough peers for non-empty sync groups')
    peer_id_batches = []
    all_peer_ids = []
    prefixes = []
    if settings['ensure_non_empty_sync_groups']:
        prefixes = [bs.Bits(uint=i, length=settings['prefix_length'])
                    for i in range(2 ** settings['prefix_length'])]
    for time, num_peers in peer_batches:
        peer_ids = []
        for _ in range(num_peers):
            while True:
                peer_id_uint = random.randrange(2 ** settings['id_length'])
                peer_id = bs.Bits(uint=peer_id_uint,
                                  length=settings['id_length'])
                if prefixes:
                    peer_id = prefixes[0] + peer_id[settings['prefix_length']:]
                if peer_id not in all_peer_ids:
                    all_peer_ids.append(peer_id)
                    peer_ids.append(peer_id)
                    if prefixes:
                        prefixes.pop(0)
                    break
        peer_id_batches.append((time, peer_ids))
    return peer_id_batches, all_peer_ids


def add_peers(time, peer_id_batch, all_peers, env, logger, network,
              all_query_groups, all_prefixes, settings, sync_groups,
              query_group_id):
    added_peers = []
    for peer_id in peer_id_batch:
        peer = p.Peer(env, logger, network, peer_id, all_query_groups,
                      all_prefixes, settings)
        all_peers[peer_id] = peer
        added_peers.append(peer)
        prefix = peer_id[:settings['prefix_length']]
        sync_groups.setdefault(prefix, util.SortedIterSet()).add(peer)
        all_prefixes.setdefault(prefix, 0)
        all_prefixes[prefix] += 1
        env.process(request_generator(env, all_peers, peer))
        logger.log(an.PeerAdd(env.now, peer.peer_id, peer.prefix, None))
        logger.log(an.UncoveredSubprefixes(
            env.now, peer.peer_id,
            util.SortedIterSet(peer.uncovered_subprefixes()), None))
        for sync_peer in sync_groups[prefix]:
            peer.introduce(sync_peer.info())
            sync_peer.introduce(peer.info())
    if settings['force_one_group']:
        assert query_group_id is not None
        for peer in added_peers:
            query_group = all_query_groups[query_group_id]
            query_group[peer.peer_id] = p.QueryPeerInfo(
                peer.info(), settings['initial_reputation'])
            peer.query_groups[query_group_id] = copy.deepcopy(query_group)
            for qpi in query_group.infos():
                all_peers[qpi.peer_id]\
                    .query_groups[query_group_id][peer.peer_id]\
                    = p.QueryPeerInfo(peer.info(),
                                      settings['initial_reputation'])
            logger.log(an.QueryGroupAdd(time, peer.peer_id, query_group_id,
                                        None))
    else:
        assert query_group_id is None
        for peer in added_peers:
            for other_peer in random.sample(
                    list(all_peers.values()),
                    settings['num_random_introductions']):
                peer.introduce(other_peer.info())
        for peer in added_peers:
            peer.start_missing_query_peer_search()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Provide a settings file.')
        exit(1)
    settings = util.read_settings(sys.argv[1])
    random.seed(a=settings['rng_seed'], version=2)
    env = simpy.Environment()
    logger = an.Logger(settings)
    peers = cl.OrderedDict()
    sync_groups = cl.OrderedDict()
    all_query_groups = cl.OrderedDict()
    all_prefixes = util.SortedBitsTrie()
    network = util.Network(env, settings)

    if settings['force_one_group']:
        query_group_id = next(p.query_group_id_iter)
        query_group = p.QueryGroup(query_group_id, (),
                                   settings['initial_reputation'])
        all_query_groups[query_group_id] = query_group
    else:
        query_group_id = None

    if settings['even_sync_groups']:
        peer_id_batches, all_peer_ids\
            = even_sync_groups_peer_id_batches(settings)
    else:
        peer_id_batches, all_peer_ids = random_peer_id_batches(settings)
    assert len(all_peer_ids) == len(set(all_peer_ids))
    for time, peer_id_batch in peer_id_batches:
        util.do_delayed(
            env, time, add_peers, time, peer_id_batch, peers, env, logger,
            network, all_query_groups, all_prefixes, settings, sync_groups,
            query_group_id)

    until = float('inf')
    if len(sys.argv) > 2:
        until = float(sys.argv[2])
    file_name = settings['log_file_name']
    progress_proc = env.process(util.progress_process(env, 1))
    signal.signal(signal.SIGINT, terminate(progress_proc, logger, file_name))
    print('running simulation until {}'.format(until))
    env.process(decay_reputation(env, all_query_groups, peers, logger,
                                 settings))
    env.run(until)
    write_log(logger, file_name)
