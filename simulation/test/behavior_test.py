import unittest
from test_helper import get_settings, create_query_group
import util
import peer
import analyze
import bitstring as bs
import simpy
from collections import OrderedDict
import random


class TestPeerSelection(unittest.TestCase):
    def setUp(self):
        self.settings = get_settings()
        self.env = simpy.Environment()
        self.logger = analyze.Logger(self.settings)
        self.network = util.Network(self.env, self.settings)
        self.all_query_groups = OrderedDict()
        self.all_peer_ids = set()

    def id_with_prefix(self, prefix_str):
        prefix = bs.Bits(bin=prefix_str)
        suffix_length = self.settings['id_length'] - len(prefix)
        suffix = bs.Bits(uint=random.randrange(2 ** suffix_length),
                         length=suffix_length)
        return prefix + suffix

    def peer_with_prefix(self, prefix_str):
        while True:
            peer_id = self.id_with_prefix(prefix_str)
            if peer_id not in self.all_peer_ids:
                self.all_peer_ids.add(peer_id)
                break
        return peer.Peer(self.env, self.logger, self.network, peer_id,
                         self.all_query_groups, self.settings)

    def test_selects_peers(self):
        peer_a = self.peer_with_prefix('0000')
        peer_b = self.peer_with_prefix('1100')
        peer_c = self.peer_with_prefix('1000')
        create_query_group(self.all_query_groups, peer_a, peer_b, peer_c)
        selected = peer_a.behavior.select_peers_to_query(
            self.id_with_prefix('1111'))
        self.assertEqual(set(selected), set((peer_b.peer_id, peer_c.peer_id)))

    def test_doesnt_select_peers_with_smaller_or_equal_overlap(self):
        peer_a = self.peer_with_prefix('0000')
        peer_b = self.peer_with_prefix('0000')
        peer_c = self.peer_with_prefix('0011')
        peer_d = self.peer_with_prefix('1000')
        create_query_group(self.all_query_groups, peer_a, peer_b, peer_c,
                           peer_d)
        selected = peer_a.behavior.select_peers_to_query(
            self.id_with_prefix('0001'))
        self.assertEqual(selected, [])

    def test_only_selects_peers_once(self):
        peer_a = self.peer_with_prefix('0000')
        peer_b = self.peer_with_prefix('1111')
        create_query_group(self.all_query_groups, peer_a, peer_b)
        create_query_group(self.all_query_groups, peer_a, peer_b)
        selected = peer_a.behavior.select_peers_to_query(
            self.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_b.peer_id])

    def test_sorts_by_overlap_length(self):
        self.settings['query_peer_selection'] = 'overlap'
        peer_a = self.peer_with_prefix('0000')
        peer_b = self.peer_with_prefix('1000')
        peer_c = self.peer_with_prefix('1111')
        peer_d = self.peer_with_prefix('1100')
        create_query_group(self.all_query_groups, peer_a, peer_b, peer_c,
                           peer_d)
        selected = peer_a.behavior.select_peers_to_query(
            self.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_c.peer_id, peer_d.peer_id,
                                    peer_b.peer_id])

    def test_puts_high_rep_peers_to_the_back(self):
        self.settings['query_peer_selection'] = 'overlap_low_rep_first'
        peer_a = self.peer_with_prefix('0000')
        peer_b = self.peer_with_prefix('1111')
        peer_c = self.peer_with_prefix('1000')
        query_group_id = create_query_group(self.all_query_groups, peer_a,
                                            peer_b, peer_c)
        enough_rep = (self.settings['reputation_buffer_factor']
                      * self.settings['no_penalty_reputation'])
        peer_a.query_groups[query_group_id][peer_b.peer_id].reputation\
            = enough_rep + 1
        selected = peer_a.behavior.select_peers_to_query(
            self.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_c.peer_id, peer_b.peer_id])

    def test_considers_minimum_rep_in_all_shared_query_groups(self):
        self.settings['query_peer_selection'] = 'overlap_low_rep_first'
        peer_a = self.peer_with_prefix('0000')
        peer_b = self.peer_with_prefix('1111')
        peer_c = self.peer_with_prefix('1000')
        query_group_id_1 = create_query_group(self.all_query_groups, peer_a,
                                              peer_b, peer_c)
        create_query_group(self.all_query_groups, peer_a, peer_b, peer_c)
        enough_rep = (self.settings['reputation_buffer_factor']
                      * self.settings['no_penalty_reputation'])
        peer_a.query_groups[query_group_id_1][peer_b.peer_id].reputation\
            = enough_rep + 1
        selected = peer_a.behavior.select_peers_to_query(
            self.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_b.peer_id, peer_c.peer_id])
