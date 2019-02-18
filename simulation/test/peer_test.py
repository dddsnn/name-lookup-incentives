import unittest
from test_helper import get_settings, create_query_group
import util
import peer
import analyze
import bitstring as bs
import simpy
from collections import OrderedDict
import random


class TestReputationUpdate(unittest.TestCase):
    def setUp(self):
        self.settings = get_settings()
        self.env = simpy.Environment()
        self.logger = analyze.Logger(self.settings)
        self.network = util.Network(self.env, self.settings)
        self.all_query_groups = OrderedDict()
        self.peer_a_id = bs.Bits(uint=0, length=16)
        self.peer_b_id = bs.Bits(uint=1, length=16)
        self.peer_c_id = bs.Bits(uint=2, length=16)
        self.peer_a = peer.Peer(self.env, self.logger, self.network,
                                self.peer_a_id, self.all_query_groups,
                                self.settings)
        self.peer_b = peer.Peer(self.env, self.logger, self.network,
                                self.peer_b_id, self.all_query_groups,
                                self.settings)
        self.peer_c = peer.Peer(self.env, self.logger, self.network,
                                self.peer_c_id, self.all_query_groups,
                                self.settings)

    def test_recv_updates_reputation(self):
        query_group_id = create_query_group(self.all_query_groups, self.peer_a,
                                            self.peer_b, self.peer_c)
        query_group = self.peer_a.query_groups[query_group_id]
        self.assertEqual(query_group[self.peer_b_id].reputation, 0)
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, 5,
                                           0, None)
        self.assertEqual(query_group[self.peer_b_id].reputation, 5)

    def test_recv_doesnt_allow_negative_reputation(self):
        query_group_id = create_query_group(self.all_query_groups, self.peer_a,
                                            self.peer_b, self.peer_c)
        query_group = self.peer_a.query_groups[query_group_id]
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, 5,
                                           0, None)
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, -7,
                                           0, None)
        self.assertEqual(query_group[self.peer_b_id].reputation, 0)

    def test_recv_rolls_back_and_repplys_younger_updates(self):
        query_group_id = create_query_group(self.all_query_groups, self.peer_a,
                                            self.peer_b, self.peer_c)
        query_group = self.peer_a.query_groups[query_group_id]
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, 3,
                                           0, None)
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, -7,
                                           2, None)
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, 5,
                                           1, None)
        self.assertEqual(query_group[self.peer_b_id].reputation, 1)

    def test_recv_updates_in_multiple_groups(self):
        create_query_group(self.all_query_groups, self.peer_a, self.peer_b,
                           self.peer_c)
        create_query_group(self.all_query_groups, self.peer_a, self.peer_b,
                           self.peer_c)
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, 3,
                                           0, None)
        self.assertEqual(len(self.peer_a.query_groups), 2)
        for query_group in self.peer_a.query_groups.values():
            self.assertEqual(query_group[self.peer_b_id].reputation, 3)

    def test_recv_only_updates_in_groups_shared_by_sender_and_subject(self):
        create_query_group(self.all_query_groups, self.peer_a, self.peer_b,
                           self.peer_c)
        query_group_2_id = create_query_group(self.all_query_groups,
                                              self.peer_a, self.peer_b)
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, 3,
                                           0, None)
        query_group = self.peer_a.query_groups[query_group_2_id]
        self.assertEqual(query_group[self.peer_b_id].reputation, 0)

    def test_send_updates_for_all(self):
        create_query_group(self.all_query_groups, self.peer_a, self.peer_b)
        create_query_group(self.all_query_groups, self.peer_a, self.peer_b)
        self.peer_a.send_reputation_update(self.peer_b.peer_id, 3, None)
        self.env.run()
        self.assertEqual(len(self.peer_a.query_groups), 2)
        self.assertEqual(len(self.peer_b.query_groups), 2)
        for query_group in self.peer_a.query_groups.values():
            self.assertEqual(query_group[self.peer_b_id].reputation, 3)
        for query_group in self.peer_b.query_groups.values():
            self.assertEqual(query_group[self.peer_b_id].reputation, 3)


class TestQueryGroups(unittest.TestCase):
    def setUp(self):
        self.settings = get_settings()
        self.env = simpy.Environment()
        self.logger = analyze.Logger(self.settings)
        self.network = util.Network(self.env, self.settings)
        self.all_query_groups = OrderedDict()
        self.peer_a_id = bs.Bits(uint=0, length=16)
        self.peer_b_id = bs.Bits(uint=1, length=16)
        self.peer_c_id = bs.Bits(uint=2, length=16)
        self.peer_a = peer.Peer(self.env, self.logger, self.network,
                                self.peer_a_id, self.all_query_groups,
                                self.settings)
        self.peer_b = peer.Peer(self.env, self.logger, self.network,
                                self.peer_b_id, self.all_query_groups,
                                self.settings)
        self.peer_c = peer.Peer(self.env, self.logger, self.network,
                                self.peer_c_id, self.all_query_groups,
                                self.settings)

    def test_first_tries_to_join_others_group(self):
        query_group_id = create_query_group(self.all_query_groups, self.peer_a)
        self.peer_b.join_group_with(self.peer_a.info())
        self.assertTrue(query_group_id in self.peer_b.query_groups)
        self.assertTrue(self.peer_b_id
                        in self.peer_a.query_groups[query_group_id])

    def test_then_tries_to_add_other_to_own_group(self):
        query_group_id = create_query_group(self.all_query_groups, self.peer_b)
        self.peer_b.join_group_with(self.peer_a.info())
        self.assertTrue(query_group_id in self.peer_a.query_groups)
        self.assertTrue(self.peer_a_id
                        in self.peer_b.query_groups[query_group_id])

    def test_otherwise_creates_new_group(self):
        self.peer_b.join_group_with(self.peer_a.info())
        self.assertEqual(len(self.all_query_groups), 1)
        query_group_id = next(iter(
            self.all_query_groups.values())).query_group_id
        self.assertTrue(self.peer_a_id
                        in self.peer_a.query_groups[query_group_id])
        self.assertTrue(self.peer_b_id
                        in self.peer_a.query_groups[query_group_id])
        self.assertTrue(self.peer_a_id
                        in self.peer_b.query_groups[query_group_id])
        self.assertTrue(self.peer_b_id
                        in self.peer_b.query_groups[query_group_id])

    def test_initializes_joining_others_to_current_state(self):
        query_group_id = create_query_group(self.all_query_groups, self.peer_a,
                                            self.peer_c)
        self.peer_c.send_reputation_update(self.peer_a.peer_id, 3, None)
        self.env.run()
        self.assertEqual(
            self.peer_a.query_groups[query_group_id][self.peer_a_id]
            .reputation, 3)
        self.peer_b.join_group_with(self.peer_a.info())
        self.assertEqual(
            self.peer_b.query_groups[query_group_id][self.peer_a_id]
            .reputation, 3)

    def test_initializes_adding_to_own_to_current_state(self):
        query_group_id = create_query_group(self.all_query_groups, self.peer_a,
                                            self.peer_c)
        self.peer_c.send_reputation_update(self.peer_a.peer_id, 3, None)
        self.env.run()
        self.assertEqual(
            self.peer_a.query_groups[query_group_id][self.peer_a_id]
            .reputation, 3)
        self.peer_a.join_group_with(self.peer_b.info())
        self.assertEqual(
            self.peer_b.query_groups[query_group_id][self.peer_a_id]
            .reputation, 3)


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
        selected = peer_a.select_peers_to_query(self.id_with_prefix('1111'))
        self.assertEqual(set(selected), set((peer_b.peer_id, peer_c.peer_id)))

    def test_doesnt_select_peers_with_smaller_or_equal_overlap(self):
        peer_a = self.peer_with_prefix('0000')
        peer_b = self.peer_with_prefix('0000')
        peer_c = self.peer_with_prefix('0011')
        peer_d = self.peer_with_prefix('1000')
        create_query_group(self.all_query_groups, peer_a, peer_b, peer_c,
                           peer_d)
        selected = peer_a.select_peers_to_query(self.id_with_prefix('0001'))
        self.assertEqual(selected, [])

    def test_only_selects_peers_once(self):
        peer_a = self.peer_with_prefix('0000')
        peer_b = self.peer_with_prefix('1111')
        create_query_group(self.all_query_groups, peer_a, peer_b)
        create_query_group(self.all_query_groups, peer_a, peer_b)
        selected = peer_a.select_peers_to_query(self.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_b.peer_id])

    def test_sorts_by_overlap_length(self):
        self.settings['query_peer_selection'] = 'overlap'
        peer_a = self.peer_with_prefix('0000')
        peer_b = self.peer_with_prefix('1000')
        peer_c = self.peer_with_prefix('1111')
        peer_d = self.peer_with_prefix('1100')
        create_query_group(self.all_query_groups, peer_a, peer_b, peer_c,
                           peer_d)
        selected = peer_a.select_peers_to_query(self.id_with_prefix('1111'))
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
        selected = peer_a.select_peers_to_query(self.id_with_prefix('1111'))
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
        selected = peer_a.select_peers_to_query(self.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_b.peer_id, peer_c.peer_id])
