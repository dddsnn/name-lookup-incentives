import unittest
from test_utils import TestHelper, PeerFactory
import bitstring as bs


class TestReputationUpdate(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.peer_factory = PeerFactory(self.helper.settings)
        self.peer_a = self.peer_factory.peer_with_prefix('')
        self.peer_b = self.peer_factory.peer_with_prefix('')
        self.peer_c = self.peer_factory.peer_with_prefix('')

    def test_recv_updates_reputation(self):
        query_group_id = self.peer_factory.create_query_group(
            self.peer_a, self.peer_b, self.peer_c)
        query_group = self.peer_a.query_groups[query_group_id]
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 0)
        self.peer_a.recv_reputation_update(self.peer_c.peer_id,
                                           self.peer_b.peer_id, 5, 0, None)
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 5)

    def test_recv_doesnt_allow_negative_reputation(self):
        query_group_id = self.peer_factory.create_query_group(
            self.peer_a, self.peer_b, self.peer_c)
        query_group = self.peer_a.query_groups[query_group_id]
        self.peer_a.recv_reputation_update(self.peer_c.peer_id,
                                           self.peer_b.peer_id, 5, 0, None)
        self.peer_a.recv_reputation_update(self.peer_c.peer_id,
                                           self.peer_b.peer_id, -7, 0, None)
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 0)

    def test_recv_rolls_back_and_repplys_younger_updates(self):
        query_group_id = self.peer_factory.create_query_group(
            self.peer_a, self.peer_b, self.peer_c)
        query_group = self.peer_a.query_groups[query_group_id]
        self.peer_a.recv_reputation_update(self.peer_c.peer_id,
                                           self.peer_b.peer_id, 3, 0, None)
        self.peer_a.recv_reputation_update(self.peer_c.peer_id,
                                           self.peer_b.peer_id, -7, 2, None)
        self.peer_a.recv_reputation_update(self.peer_c.peer_id,
                                           self.peer_b.peer_id, 5, 1, None)
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 1)

    def test_recv_updates_in_multiple_groups(self):
        self.peer_factory.create_query_group(self.peer_a, self.peer_b,
                                             self.peer_c)
        self.peer_factory.create_query_group(self.peer_a, self.peer_b,
                                             self.peer_c)
        self.peer_a.recv_reputation_update(self.peer_c.peer_id,
                                           self.peer_b.peer_id, 3, 0, None)
        self.assertEqual(len(self.peer_a.query_groups), 2)
        for query_group in self.peer_a.query_groups.values():
            self.assertEqual(query_group[self.peer_b.peer_id].reputation, 3)

    def test_recv_only_updates_in_groups_shared_by_sender_and_subject(self):
        self.peer_factory.create_query_group(self.peer_a, self.peer_b,
                                             self.peer_c)
        query_group_2_id = self.peer_factory.create_query_group(self.peer_a,
                                                                self.peer_b)
        self.peer_a.recv_reputation_update(self.peer_c.peer_id,
                                           self.peer_b.peer_id, 3, 0, None)
        query_group = self.peer_a.query_groups[query_group_2_id]
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 0)

    def test_send_updates_for_all(self):
        self.peer_factory.create_query_group(self.peer_a, self.peer_b)
        self.peer_factory.create_query_group(self.peer_a, self.peer_b)
        self.peer_a.send_reputation_update(self.peer_b.peer_id, 3, None)
        self.peer_factory.env.run()
        self.assertEqual(len(self.peer_a.query_groups), 2)
        self.assertEqual(len(self.peer_b.query_groups), 2)
        for query_group in self.peer_a.query_groups.values():
            self.assertEqual(query_group[self.peer_b.peer_id].reputation, 3)
        for query_group in self.peer_b.query_groups.values():
            self.assertEqual(query_group[self.peer_b.peer_id].reputation, 3)


class TestQueryGroups(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.peer_factory = PeerFactory(self.helper.settings)
        self.peer_a = self.peer_factory.peer_with_prefix('')
        self.peer_b = self.peer_factory.peer_with_prefix('')
        self.peer_c = self.peer_factory.peer_with_prefix('')

    def test_first_tries_to_join_others_group(self):
        query_group_id = self.peer_factory.create_query_group(self.peer_a)
        self.peer_b.join_group_with(self.peer_a.info())
        self.assertTrue(query_group_id in self.peer_b.query_groups)
        self.assertTrue(self.peer_b.peer_id
                        in self.peer_a.query_groups[query_group_id])

    def test_then_tries_to_add_other_to_own_group(self):
        query_group_id = self.peer_factory.create_query_group(self.peer_b)
        self.peer_b.join_group_with(self.peer_a.info())
        self.assertTrue(query_group_id in self.peer_a.query_groups)
        self.assertTrue(self.peer_a.peer_id
                        in self.peer_b.query_groups[query_group_id])

    def test_otherwise_creates_new_group(self):
        self.peer_b.join_group_with(self.peer_a.info())
        self.assertEqual(len(self.peer_factory.all_query_groups), 1)
        query_group_id = next(iter(
            self.peer_factory.all_query_groups.values())).query_group_id
        self.assertTrue(self.peer_a.peer_id
                        in self.peer_a.query_groups[query_group_id])
        self.assertTrue(self.peer_b.peer_id
                        in self.peer_a.query_groups[query_group_id])
        self.assertTrue(self.peer_a.peer_id
                        in self.peer_b.query_groups[query_group_id])
        self.assertTrue(self.peer_b.peer_id
                        in self.peer_b.query_groups[query_group_id])

    def test_initializes_joining_others_to_current_state(self):
        query_group_id = self.peer_factory.create_query_group(self.peer_a,
                                                              self.peer_c)
        self.peer_c.send_reputation_update(self.peer_a.peer_id, 3, None)
        self.peer_factory.env.run()
        self.assertEqual(
            self.peer_a.query_groups[query_group_id][self.peer_a.peer_id]
            .reputation, 3)
        self.peer_b.join_group_with(self.peer_a.info())
        self.assertEqual(
            self.peer_b.query_groups[query_group_id][self.peer_a.peer_id]
            .reputation, 3)

    def test_initializes_adding_to_own_to_current_state(self):
        query_group_id = self.peer_factory.create_query_group(self.peer_a,
                                                              self.peer_c)
        self.peer_c.send_reputation_update(self.peer_a.peer_id, 3, None)
        self.peer_factory.env.run()
        self.assertEqual(
            self.peer_a.query_groups[query_group_id][self.peer_a.peer_id]
            .reputation, 3)
        self.peer_a.join_group_with(self.peer_b.info())
        self.assertEqual(
            self.peer_b.query_groups[query_group_id][self.peer_a.peer_id]
            .reputation, 3)


class TestSubprefixes(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.peer_factory = PeerFactory(self.helper.settings)

    def test_empty(self):
        self.helper.settings['prefix_length'] = 0
        peer = self.peer_factory.peer_with_prefix('')
        self.assertEqual(peer.subprefixes(), [])

    def test_ordered(self):
        self.helper.settings['prefix_length'] = 16
        peer = self.peer_factory.peer_with_prefix('')
        sp = peer.subprefixes()
        self.assertEqual(len(sp[0]), 1)
        for a, b in zip(sp[:-1], sp[1:]):
            self.assertEqual(len(a), len(b) - 1)

    def test_subprefixes(self):
        prefix = '0010100101'
        self.helper.settings['prefix_length'] = len(prefix)
        peer = self.peer_factory.peer_with_prefix(prefix)
        self.assertEqual(peer.subprefixes(), [
                         bs.Bits(bin='1'),
                         bs.Bits(bin='01'),
                         bs.Bits(bin='000'),
                         bs.Bits(bin='0011'),
                         bs.Bits(bin='00100'),
                         bs.Bits(bin='001011'),
                         bs.Bits(bin='0010101'),
                         bs.Bits(bin='00101000'),
                         bs.Bits(bin='001010011'),
                         bs.Bits(bin='0010100100')])


class TestSubprefixCoverage(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.peer_factory = PeerFactory(self.helper.settings)

    def test_with_no_query_groups(self):
        peer = self.peer_factory.peer_with_prefix('0000')
        self.assertEqual(peer.subprefix_coverage(),
                         {sp: 0 for sp in peer.subprefixes()})

    def test_with_all_peers_same_prefix(self):
        peer = self.peer_factory.peer_with_prefix('0000')
        self.peer_factory.create_query_group(
            peer,
            self.peer_factory.peer_with_prefix('0000'),
            self.peer_factory.peer_with_prefix('0000'))
        self.assertEqual(peer.subprefix_coverage(),
                         {sp: 0 for sp in peer.subprefixes()})

    def test_subprefix_coverage(self):
        peer = self.peer_factory.peer_with_prefix('0000')
        self.peer_factory.create_query_group(
            peer,
            self.peer_factory.peer_with_prefix('0001'),
            self.peer_factory.peer_with_prefix('0001'),
            self.peer_factory.peer_with_prefix('0100'),
            self.peer_factory.peer_with_prefix('0101'),
            self.peer_factory.peer_with_prefix('0110'),
            self.peer_factory.peer_with_prefix('1111'))
        self.assertEqual(peer.subprefix_coverage(), {
                         bs.Bits(bin='0001'): 2,
                         bs.Bits(bin='001'): 0,
                         bs.Bits(bin='01'): 3,
                         bs.Bits(bin='1'): 1})

    def test_doesnt_count_peers_multiple_times(self):
        peer = self.peer_factory.peer_with_prefix('0000')
        other_peer = self.peer_factory.peer_with_prefix('1111')
        self.peer_factory.create_query_group(peer, other_peer)
        self.peer_factory.create_query_group(peer, other_peer)
        self.assertEqual(peer.subprefix_coverage(), {
                         bs.Bits(bin='0001'): 0,
                         bs.Bits(bin='001'): 0,
                         bs.Bits(bin='01'): 0,
                         bs.Bits(bin='1'): 1})
