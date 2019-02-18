import unittest
import test_helper
import util
import peer
import analyze
import bitstring as bs
import simpy
from peer import QueryGroup
from copy import deepcopy
from collections import OrderedDict


class TestReputationUpdate(unittest.TestCase):
    def setUp(self):
        self.settings = test_helper.get_settings()
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
        self.peer_a.join_group_with(self.peer_b.info())
        self.peer_a.join_group_with(self.peer_c.info())

    def test_recv_updates_reputation(self):
        query_group = next(iter(self.peer_a.query_groups.values()))
        self.assertEqual(query_group[self.peer_b_id].reputation, 0)
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, 5,
                                           0, None)
        self.assertEqual(query_group[self.peer_b_id].reputation, 5)

    def test_recv_doesnt_allow_negative_reputation(self):
        query_group = next(iter(self.peer_a.query_groups.values()))
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, 5,
                                           0, None)
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, -7,
                                           0, None)
        self.assertEqual(query_group[self.peer_b_id].reputation, 0)

    def test_recv_rolls_back_and_repplys_younger_updates(self):
        query_group = next(iter(self.peer_a.query_groups.values()))
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, 3,
                                           0, None)
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, -7,
                                           2, None)
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, 5,
                                           1, None)
        self.assertEqual(query_group[self.peer_b_id].reputation, 1)

    def test_recv_updates_in_multiple_groups(self):
        query_group_2 = QueryGroup(next(peer.query_group_id_iter), (
            (self.peer_a_id, self.peer_a.prefix, self.peer_a.address),
            (self.peer_b_id, self.peer_b.prefix, self.peer_b.address),
            (self.peer_c_id, self.peer_c.prefix, self.peer_c.address)))
        self.peer_a.query_groups[query_group_2.query_group_id]\
            = deepcopy(query_group_2)
        self.peer_b.query_groups[query_group_2.query_group_id]\
            = deepcopy(query_group_2)
        self.peer_c.query_groups[query_group_2.query_group_id]\
            = deepcopy(query_group_2)
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, 3,
                                           0, None)
        for query_group in self.peer_a.query_groups.values():
            self.assertEqual(query_group[self.peer_b_id].reputation, 3)

    def test_recv_only_updates_in_groups_shared_by_sender_and_subject(self):
        query_group_2 = QueryGroup(next(peer.query_group_id_iter), (
            (self.peer_a_id, self.peer_a.prefix, self.peer_a.address),
            (self.peer_b_id, self.peer_b.prefix, self.peer_b.address)))
        self.peer_a.query_groups[query_group_2.query_group_id]\
            = deepcopy(query_group_2)
        self.peer_b.query_groups[query_group_2.query_group_id]\
            = deepcopy(query_group_2)
        self.peer_a.recv_reputation_update(self.peer_c_id, self.peer_b_id, 3,
                                           0, None)
        query_group = self.peer_a.query_groups[query_group_2.query_group_id]
        self.assertEqual(query_group[self.peer_b_id].reputation, 0)

    def test_send_updates_for_all(self):
        query_group_2 = QueryGroup(next(peer.query_group_id_iter), (
            (self.peer_a_id, self.peer_a.prefix, self.peer_a.address),
            (self.peer_b_id, self.peer_b.prefix, self.peer_b.address)))
        self.peer_a.query_groups[query_group_2.query_group_id]\
            = deepcopy(query_group_2)
        self.peer_b.query_groups[query_group_2.query_group_id]\
            = deepcopy(query_group_2)
        self.all_query_groups[query_group_2.query_group_id]\
            = deepcopy(query_group_2)
        self.peer_a.send_reputation_update(self.peer_b.peer_id, 3, None)
        self.env.run()
        for query_group in self.peer_a.query_groups.values():
            self.assertEqual(query_group[self.peer_b_id].reputation, 3)
        for query_group in self.peer_b.query_groups.values():
            self.assertEqual(query_group[self.peer_b_id].reputation, 3)


class TestQueryGroups(unittest.TestCase):
    def setUp(self):
        self.settings = test_helper.get_settings()
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
        query_group = QueryGroup(next(peer.query_group_id_iter), (
            (self.peer_a_id, self.peer_a.prefix, self.peer_a.address),))
        self.all_query_groups[query_group.query_group_id]\
            = deepcopy(query_group)
        self.peer_a.query_groups[query_group.query_group_id]\
            = deepcopy(query_group)
        self.peer_b.join_group_with(self.peer_a.info())
        self.assertTrue(query_group.query_group_id in self.peer_b.query_groups)
        self.assertTrue(self.peer_b_id in self.peer_a.query_groups[
            query_group.query_group_id])

    def test_then_tries_to_add_other_to_own_group(self):
        query_group = QueryGroup(next(peer.query_group_id_iter), (
            (self.peer_b_id, self.peer_b.prefix, self.peer_b.address),))
        self.all_query_groups[query_group.query_group_id]\
            = deepcopy(query_group)
        self.peer_b.query_groups[query_group.query_group_id]\
            = deepcopy(query_group)
        self.peer_b.join_group_with(self.peer_a.info())
        self.assertTrue(query_group.query_group_id in self.peer_a.query_groups)
        self.assertTrue(self.peer_a_id in self.peer_b.query_groups[
            query_group.query_group_id])

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
        query_group = QueryGroup(next(peer.query_group_id_iter), (
            (self.peer_a_id, self.peer_a.prefix, self.peer_a.address),
            (self.peer_c_id, self.peer_c.prefix, self.peer_c.address)))
        query_group_id = query_group.query_group_id
        self.peer_a.query_groups[query_group.query_group_id]\
            = deepcopy(query_group)
        self.peer_c.query_groups[query_group.query_group_id]\
            = deepcopy(query_group)
        self.all_query_groups[query_group.query_group_id]\
            = deepcopy(query_group)
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
        query_group = QueryGroup(next(peer.query_group_id_iter), (
            (self.peer_a_id, self.peer_a.prefix, self.peer_a.address),
            (self.peer_c_id, self.peer_c.prefix, self.peer_c.address)))
        query_group_id = query_group.query_group_id
        self.peer_a.query_groups[query_group.query_group_id]\
            = deepcopy(query_group)
        self.peer_c.query_groups[query_group.query_group_id]\
            = deepcopy(query_group)
        self.all_query_groups[query_group.query_group_id]\
            = deepcopy(query_group)
        self.peer_c.send_reputation_update(self.peer_a.peer_id, 3, None)
        self.env.run()
        self.assertEqual(
            self.peer_a.query_groups[query_group_id][self.peer_a_id]
            .reputation, 3)
        self.peer_a.join_group_with(self.peer_b.info())
        self.assertEqual(
            self.peer_b.query_groups[query_group_id][self.peer_a_id]
            .reputation, 3)
