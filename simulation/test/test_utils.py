import util
from peer import QueryGroup, query_group_id_iter, Peer, PeerBehavior
import os
import bitstring as bs
from copy import deepcopy
import simpy
import analyze
import random
import unittest.mock


bs.Bits.__lt__ = util.bits_lt


class TestHelper:
    def __init__(self):
        file_name = os.path.join(os.getcwd(), '../default.settings')
        self.settings = util.read_settings(file_name)

    def create_query_group(self, all_query_groups, *peers):
        query_group = QueryGroup(next(query_group_id_iter),
                                 (p.info() for p in peers),
                                 self.settings['initial_reputation'])
        all_query_groups[query_group.query_group_id] = query_group
        for peer in peers:
            peer.query_groups[query_group.query_group_id]\
                = deepcopy(query_group)
        return query_group.query_group_id


class PeerFactory:
    def __init__(self, all_query_groups, settings):
        self.settings = settings
        self.all_query_groups = all_query_groups
        self.env = simpy.Environment()
        self.logger = analyze.Logger(self.settings)
        self.network = util.Network(self.env, self.settings)
        self.all_peer_ids = set()

    def id_with_prefix(self, prefix_str):
        while True:
            prefix = bs.Bits(bin=prefix_str)
            suffix_length = self.settings['id_length'] - len(prefix)
            suffix = bs.Bits(uint=random.randrange(2 ** suffix_length),
                             length=suffix_length)
            peer_id = prefix + suffix
            if peer_id not in self.all_peer_ids:
                self.all_peer_ids.add(peer_id)
                return peer_id

    def peer_with_prefix(self, prefix_str):
        peer_id = self.id_with_prefix(prefix_str)
        return Peer(self.env, self.logger, self.network, peer_id,
                    self.all_query_groups, self.settings)

    def mock_peer_and_behavior_with_prefix(self, prefix_str):
        peer = self.peer_with_prefix(prefix_str)
        mock_peer = unittest.mock.Mock(spec=Peer, wraps=peer)
        mock_peer.env = peer.env
        mock_peer.sync_peers = peer.sync_peers
        mock_peer.query_groups = peer.query_groups
        mock_peer.peer_id = peer.peer_id
        mock_peer.prefix = peer.prefix
        mock_peer.settings = peer.settings
        behavior = PeerBehavior(mock_peer)
        return mock_peer, behavior


class PendingQueryMatcher:
    def __init__(self, querying_peer_id, queried_id, peers_to_query):
        self.querying_peer_id = querying_peer_id
        self.queried_id = queried_id
        self.peers_to_query = peers_to_query

    def __eq__(self, other):
        return (len(other.querying_peers) == 1
                and other.querying_peers[self.querying_peer_id]
                == set((self.queried_id,))
                and self.peers_to_query == other.peers_to_query)


def pending_query(querying_peer_id, queried_id, peers_to_query):
    return PendingQueryMatcher(querying_peer_id, queried_id, peers_to_query)
