import unittest
from unittest.mock import ANY, call
from test_utils import TestHelper, set_containing, arg_any_of
import bitstring as bs
import peer as p


class TestRecvReputationUpdate(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.peer_a = self.helper.peer_with_prefix('')
        self.peer_b = self.helper.peer_with_prefix('')
        self.peer_c = self.helper.peer_with_prefix('')
        self.peer_d = self.helper.peer_with_prefix('')

    def test_updates_reputation(self):
        query_group_id = self.helper.create_query_group(
            self.peer_a, self.peer_b, self.peer_c)
        query_group = self.peer_a.query_groups[query_group_id]
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 0)
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((query_group_id,)),
            5, 0, None)
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 5)

    def test_doesnt_allow_negative_reputation(self):
        query_group_id = self.helper.create_query_group(
            self.peer_a, self.peer_b, self.peer_c)
        query_group = self.peer_a.query_groups[query_group_id]
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((query_group_id,)),
            5, 0, None)
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((query_group_id,)),
            -7, 0, None)
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 0)

    def test_rolls_back_and_repplies_younger_updates(self):
        query_group_id = self.helper.create_query_group(
            self.peer_a, self.peer_b, self.peer_c)
        query_group = self.peer_a.query_groups[query_group_id]
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((query_group_id,)),
            3, 0, None)
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((query_group_id,)),
            -7, 2, None)
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((query_group_id,)),
            6, 1, None)
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 2)

    def test_rolls_back_and_repplies_the_same_update_multiple_times(self):
        self.helper.settings['reward_attenuation'] = {'type': 'none'}
        query_group_id = self.helper.create_query_group(
            self.peer_a, self.peer_b, self.peer_c)
        query_group = self.peer_a.query_groups[query_group_id]
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((query_group_id,)),
            3, 0, None)
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((query_group_id,)),
            -7, 3, None)
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((query_group_id,)),
            6, 1, None)
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((query_group_id,)),
            5, 2, None)
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 7)

    def test_updates_in_multiple_groups(self):
        gid1 = self.helper.create_query_group(self.peer_a, self.peer_b,
                                              self.peer_c)
        gid2 = self.helper.create_query_group(self.peer_a, self.peer_b,
                                              self.peer_c)
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((gid1, gid2)), 3, 0,
            None)
        self.assertEqual(len(self.peer_a.query_groups), 2)
        for query_group in self.peer_a.query_groups.values():
            self.assertEqual(query_group[self.peer_b.peer_id].reputation, 3)

    def test_only_updates_in_specified_groups(self):
        gid1 = self.helper.create_query_group(self.peer_a, self.peer_b,
                                              self.peer_c)
        gid2 = self.helper.create_query_group(self.peer_a, self.peer_b,
                                              self.peer_c)
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((gid1,)), 3, 0, None)
        query_group = self.peer_a.query_groups[gid2]
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 0)

    def test_updates_in_specified_groups_even_if_the_sender_isnt_in_them(self):
        gid1 = self.helper.create_query_group(self.peer_a, self.peer_b,
                                              self.peer_c)
        gid2 = self.helper.create_query_group(self.peer_a, self.peer_b)
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((gid1, gid2)), 3, 0,
            None)
        query_group_1 = self.peer_a.query_groups[gid1]
        query_group_2 = self.peer_a.query_groups[gid2]
        self.assertEqual(query_group_1[self.peer_b.peer_id].reputation, 3)
        self.assertEqual(query_group_2[self.peer_b.peer_id].reputation, 3)

    def test_updates_in_all_specified_groups_when_reapplying(self):
        gid1 = self.helper.create_query_group(self.peer_a, self.peer_b,
                                              self.peer_c)
        gid2 = self.helper.create_query_group(self.peer_a, self.peer_b,
                                              self.peer_c)
        query_group = self.peer_a.query_groups[gid2]
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((gid1, gid2)),
            3, 0, None)
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((gid1, gid2)),
            -7, 2, None)
        del self.helper.all_query_groups[gid2][self.peer_c.peer_id]
        del self.peer_a.query_groups[gid2][self.peer_c.peer_id]
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((gid1, gid2)),
            5, 1, None)
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 1)

    def test_attenuates_rewards(self):
        self.helper.settings['reward_attenuation'] = {
            'type': 'constant',
            'coefficient': 0.5,
            'lower_bound': 10,
            'upper_bound': 20
        }
        gid = self.helper.create_query_group(self.peer_a, self.peer_b,
                                             self.peer_c)
        query_group = self.peer_a.query_groups[gid]
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((gid,)), 10, 0, None)
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 10)
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((gid,)), 5, 1, None)
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 12.5)
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((gid,)), 10, 2, None)
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 17.5)

    def test_attenuates_rewards_after_rolling_back(self):
        self.helper.settings['reward_attenuation'] = {
            'type': 'constant',
            'coefficient': 0.5,
            'lower_bound': 10,
            'upper_bound': 20
        }
        query_group_id = self.helper.create_query_group(
            self.peer_a, self.peer_b, self.peer_c)
        query_group = self.peer_a.query_groups[query_group_id]
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((query_group_id,)),
            9, 0, None)
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 9)
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((query_group_id,)),
            2, 2, None)
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 10.5)
        self.peer_a.recv_reputation_update(
            self.peer_c.peer_id, self.peer_b.peer_id, set((query_group_id,)),
            6, 1, None)
        self.assertEqual(query_group[self.peer_b.peer_id].reputation, 13.5)


class TestSendReputationUpdate(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.peer_a = self.helper.peer_with_prefix('')
        self.peer_b = self.helper.peer_with_prefix('')

    def test_updates_for_all(self):
        self.helper.create_query_group(self.peer_a, self.peer_b)
        self.helper.create_query_group(self.peer_a, self.peer_b)
        self.peer_a.send_reputation_update(self.peer_b.peer_id, 3, None)
        self.helper.env.run()
        self.assertEqual(len(self.peer_a.query_groups), 2)
        self.assertEqual(len(self.peer_b.query_groups), 2)
        for query_group in self.peer_a.query_groups.values():
            self.assertEqual(query_group[self.peer_b.peer_id].reputation, 3)
        for query_group in self.peer_b.query_groups.values():
            self.assertEqual(query_group[self.peer_b.peer_id].reputation, 3)

    def test_updates_all_query_groups(self):
        gid = self.helper.create_query_group(self.peer_a, self.peer_b)
        self.peer_a.send_reputation_update(self.peer_b.peer_id, 3, None)
        aqg = self.helper.all_query_groups
        self.assertEqual(aqg[gid][self.peer_b.peer_id].reputation, 3)


class TestQueryGroups(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.peer_a = self.helper.peer_with_prefix('')
        self.peer_b = self.helper.peer_with_prefix('')
        self.peer_c = self.helper.peer_with_prefix('')

    def test_first_tries_to_join_others_group(self):
        query_group_id = self.helper.create_query_group(self.peer_a)
        self.peer_b.join_group_with(self.peer_a.info())
        self.assertTrue(query_group_id in self.peer_b.query_groups)
        self.assertTrue(self.peer_b.peer_id
                        in self.peer_a.query_groups[query_group_id])

    def test_then_tries_to_add_other_to_own_group(self):
        query_group_id = self.helper.create_query_group(self.peer_b)
        self.peer_b.join_group_with(self.peer_a.info())
        self.assertTrue(query_group_id in self.peer_a.query_groups)
        self.assertTrue(self.peer_a.peer_id
                        in self.peer_b.query_groups[query_group_id])

    def test_otherwise_creates_new_group(self):
        self.peer_b.join_group_with(self.peer_a.info())
        self.assertEqual(len(self.helper.all_query_groups), 1)
        query_group_id = next(iter(
            self.helper.all_query_groups.values())).query_group_id
        self.assertTrue(self.peer_a.peer_id
                        in self.peer_a.query_groups[query_group_id])
        self.assertTrue(self.peer_b.peer_id
                        in self.peer_a.query_groups[query_group_id])
        self.assertTrue(self.peer_a.peer_id
                        in self.peer_b.query_groups[query_group_id])
        self.assertTrue(self.peer_b.peer_id
                        in self.peer_b.query_groups[query_group_id])

    def test_initializes_joining_others_to_current_state(self):
        query_group_id = self.helper.create_query_group(self.peer_a,
                                                        self.peer_c)
        self.peer_c.send_reputation_update(self.peer_a.peer_id, 3, None)
        self.helper.env.run()
        self.assertEqual(
            self.peer_a.query_groups[query_group_id][self.peer_a.peer_id]
            .reputation, 3)
        self.peer_b.join_group_with(self.peer_a.info())
        self.assertEqual(
            self.peer_b.query_groups[query_group_id][self.peer_a.peer_id]
            .reputation, 3)

    def test_initializes_adding_to_own_to_current_state(self):
        query_group_id = self.helper.create_query_group(self.peer_a,
                                                        self.peer_c)
        self.peer_c.send_reputation_update(self.peer_a.peer_id, 3, None)
        self.helper.env.run()
        self.assertEqual(
            self.peer_a.query_groups[query_group_id][self.peer_a.peer_id]
            .reputation, 3)
        self.peer_a.join_group_with(self.peer_b.info())
        self.assertEqual(
            self.peer_b.query_groups[query_group_id][self.peer_a.peer_id]
            .reputation, 3)


class TestSubprefixes(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(p.subprefixes(bs.Bits()), [])

    def test_ordered(self):
        sp = p.subprefixes(bs.Bits('0b00001111'))
        self.assertEqual(len(sp[0]), 1)
        for a, b in zip(sp[:-1], sp[1:]):
            self.assertEqual(len(a), len(b) - 1)

    def test_subprefixes(self):
        prefix = bs.Bits('0b0010100101')
        self.assertEqual(p.subprefixes(prefix), [
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

    def test_with_no_query_groups(self):
        peer = self.helper.peer_with_prefix('0000')
        self.assertEqual(peer.subprefix_coverage(),
                         {sp: 0 for sp in peer.subprefixes()})

    def test_with_all_peers_same_prefix(self):
        peer = self.helper.peer_with_prefix('0000')
        self.helper.create_query_group(
            peer,
            self.helper.peer_with_prefix('0000'),
            self.helper.peer_with_prefix('0000'))
        self.assertEqual(peer.subprefix_coverage(),
                         {sp: 0 for sp in peer.subprefixes()})

    def test_subprefix_coverage(self):
        peer = self.helper.peer_with_prefix('0000')
        self.helper.create_query_group(
            peer,
            self.helper.peer_with_prefix('0001'),
            self.helper.peer_with_prefix('0001'),
            self.helper.peer_with_prefix('0100'),
            self.helper.peer_with_prefix('0101'),
            self.helper.peer_with_prefix('0110'),
            self.helper.peer_with_prefix('1111'))
        self.assertEqual(peer.subprefix_coverage(), {
                         bs.Bits(bin='0001'): 2,
                         bs.Bits(bin='001'): 0,
                         bs.Bits(bin='01'): 3,
                         bs.Bits(bin='1'): 1})

    def test_doesnt_count_peers_multiple_times(self):
        peer = self.helper.peer_with_prefix('0000')
        other_peer = self.helper.peer_with_prefix('1111')
        self.helper.create_query_group(peer, other_peer)
        self.helper.create_query_group(peer, other_peer)
        self.assertEqual(peer.subprefix_coverage(), {
                         bs.Bits(bin='0001'): 0,
                         bs.Bits(bin='001'): 0,
                         bs.Bits(bin='01'): 0,
                         bs.Bits(bin='1'): 1})


class TestQueryGroupSubprefixCoverage(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_with_no_query_groups(self):
        peer = self.helper.peer_with_prefix('0000')
        self.assertEqual(peer.query_group_subprefix_coverage(), {})

    def test_with_all_peers_same_prefix(self):
        peer = self.helper.peer_with_prefix('0000')

        query_group_id = self.helper.create_query_group(
            peer,
            self.helper.peer_with_prefix('0000'),
            self.helper.peer_with_prefix('0000'))
        self.assertEqual(peer.query_group_subprefix_coverage(),
                         {query_group_id: {sp: set()
                                           for sp in peer.subprefixes()}})

    def test_with_peers_in_same_query_group_and_same_prefix(self):
        peer = self.helper.peer_with_prefix('0000')
        peer_a = self.helper.peer_with_prefix('0001')
        peer_b = self.helper.peer_with_prefix('0001')

        query_group_id = self.helper.create_query_group(peer, peer_a, peer_b)
        self.assertEqual(peer.query_group_subprefix_coverage(), {
                         query_group_id: {
                             bs.Bits(bin='0001'): set_containing(
                                 peer_a.peer_id, peer_b.peer_id),
                             bs.Bits(bin='001'): set(),
                             bs.Bits(bin='01'): set(),
                             bs.Bits(bin='1'): set()}})

    def test_with_peers_in_same_query_group_and_different_prefixes(self):
        peer = self.helper.peer_with_prefix('0000')
        peer_a = self.helper.peer_with_prefix('0001')
        peer_b = self.helper.peer_with_prefix('0010')

        query_group_id = self.helper.create_query_group(peer, peer_a, peer_b)
        self.assertEqual(peer.query_group_subprefix_coverage(), {
                         query_group_id: {
                             bs.Bits(bin='0001'): set_containing(
                                 peer_a.peer_id),
                             bs.Bits(bin='001'): set_containing(
                                peer_b.peer_id),
                             bs.Bits(bin='01'): set(),
                             bs.Bits(bin='1'): set()}})

    def test_with_peers_in_different_query_groups(self):
        peer = self.helper.peer_with_prefix('0000')
        peer_a = self.helper.peer_with_prefix('0001')
        peer_b = self.helper.peer_with_prefix('0010')

        query_group_id_1 = self.helper.create_query_group(peer, peer_a)
        query_group_id_2 = self.helper.create_query_group(peer, peer_b)
        self.assertEqual(peer.query_group_subprefix_coverage(), {
                         query_group_id_1: {
                             bs.Bits(bin='0001'): set_containing(
                                peer_a.peer_id),
                             bs.Bits(bin='001'): set(),
                             bs.Bits(bin='01'): set(),
                             bs.Bits(bin='1'): set()},
                         query_group_id_2: {
                             bs.Bits(bin='0001'): set(),
                             bs.Bits(bin='001'): set_containing(
                                peer_b.peer_id),
                             bs.Bits(bin='01'): set(),
                             bs.Bits(bin='1'): set()}})

    def test_with_same_peer_in_different_query_groups(self):
        peer = self.helper.peer_with_prefix('0000')
        peer_a = self.helper.peer_with_prefix('0001')

        query_group_id_1 = self.helper.create_query_group(peer, peer_a)
        query_group_id_2 = self.helper.create_query_group(peer, peer_a)
        self.assertEqual(peer.query_group_subprefix_coverage(), {
                         query_group_id_1: {
                             bs.Bits(bin='0001'): set_containing(
                                peer_a.peer_id),
                             bs.Bits(bin='001'): set(),
                             bs.Bits(bin='01'): set(),
                             bs.Bits(bin='1'): set()},
                         query_group_id_2: {
                             bs.Bits(bin='0001'): set_containing(
                                peer_a.peer_id),
                             bs.Bits(bin='001'): set(),
                             bs.Bits(bin='01'): set(),
                             bs.Bits(bin='1'): set()}})

    def test_complex(self):
        peer = self.helper.peer_with_prefix('0000')
        peer_a = self.helper.peer_with_prefix('0001')
        peer_b = self.helper.peer_with_prefix('0001')
        peer_c = self.helper.peer_with_prefix('0100')
        peer_d = self.helper.peer_with_prefix('0101')
        peer_e = self.helper.peer_with_prefix('0110')
        peer_f = self.helper.peer_with_prefix('1111')
        query_group_id_1 = self.helper.create_query_group(
            peer, peer_a, peer_c, peer_d)
        query_group_id_2 = self.helper.create_query_group(
            peer, peer_b, peer_c, peer_e, peer_f)
        self.assertEqual(peer.query_group_subprefix_coverage(), {
                         query_group_id_1: {
                             bs.Bits(bin='0001'): set_containing(
                                peer_a.peer_id),
                             bs.Bits(bin='001'): set(),
                             bs.Bits(bin='01'): set_containing(
                                peer_c.peer_id, peer_d.peer_id),
                             bs.Bits(bin='1'): set()},
                         query_group_id_2: {
                             bs.Bits(bin='0001'): set_containing(
                                peer_b.peer_id),
                             bs.Bits(bin='001'): set(),
                             bs.Bits(bin='01'): set_containing(
                                peer_c.peer_id, peer_e.peer_id),
                             bs.Bits(bin='1'): set_containing(
                                peer_f.peer_id)}})


class TestPeerIsKnown(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_not_known(self):
        peer = self.helper.peer_with_prefix('')
        peer_id = self.helper.id_with_prefix('')
        self.assertFalse(peer.peer_is_known(peer_id))

    def test_known_query_peer(self):
        peer = self.helper.peer_with_prefix('')
        other = self.helper.peer_with_prefix('')
        peer.sync_peers[other.peer_id] = other.info()
        self.assertTrue(peer.peer_is_known(other.peer_id))

    def test_known_sync_peer(self):
        peer = self.helper.peer_with_prefix('')
        other = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer, other)
        self.assertTrue(peer.peer_is_known(other.peer_id))


class TestPendingQueryHasKnownQueryPeer(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_no_peers(self):
        peer = self.helper.peer_with_prefix('')
        pending_query = p.PendingQuery(
            0, self.helper.id_with_prefix(''), self.helper.id_with_prefix(''),
            [])
        self.assertFalse(
            peer.pending_query_has_known_query_peer(pending_query))

    def test_unknown_peer(self):
        peer = self.helper.peer_with_prefix('')
        other = self.helper.peer_with_prefix('')
        pending_query = p.PendingQuery(
            0, self.helper.id_with_prefix(''), self.helper.id_with_prefix(''),
            [other.peer_id])
        self.assertFalse(
            peer.pending_query_has_known_query_peer(pending_query))

    def test_known_peer(self):
        peer = self.helper.peer_with_prefix('')
        other = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer, other)
        pending_query = p.PendingQuery(
            0, self.helper.id_with_prefix(''), self.helper.id_with_prefix(''),
            [other.peer_id])
        self.assertTrue(peer.pending_query_has_known_query_peer(pending_query))

    def test_removes_unkown_from_front(self):
        peer = self.helper.peer_with_prefix('')
        unknown = self.helper.peer_with_prefix('')
        known = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer, known)
        pending_query = p.PendingQuery(
            0, self.helper.id_with_prefix(''), self.helper.id_with_prefix(''),
            [unknown.peer_id, known.peer_id])
        peer.pending_query_has_known_query_peer(pending_query)
        self.assertEqual(pending_query.peers_to_query, [known.peer_id])

    def test_doesnt_remove_unkown_from_back(self):
        peer = self.helper.peer_with_prefix('')
        unknown = self.helper.peer_with_prefix('')
        known = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer, known)
        pending_query = p.PendingQuery(
            0, self.helper.id_with_prefix(''), self.helper.id_with_prefix(''),
            [known.peer_id, unknown.peer_id])
        peer.pending_query_has_known_query_peer(pending_query)
        self.assertEqual(pending_query.peers_to_query,
                         [known.peer_id, unknown.peer_id])


class TestFindQueryPeersFor(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_doesnt_do_anything_when_no_query_groups(self):
        peer = self.helper.peer_with_prefix('1111')
        prefix = bs.Bits('0b0000')
        self.assertFalse(peer.find_query_peers_for(prefix, set(), 1, 0, None))
        self.assertEqual(len(peer.query_groups), 0)

    def test_doesnt_join_groups_without_covering_peers(self):
        peer = self.helper.peer_with_prefix('1111')
        prefix = bs.Bits('0b0000')
        peer_a = self.helper.peer_with_prefix('0001')
        self.helper.create_query_group(peer_a)
        self.assertFalse(peer.find_query_peers_for(prefix, set(), 1, 0, None))
        self.assertEqual(len(peer.query_groups), 0)

    def test_joins_group_with_covering_peer(self):
        peer = self.helper.peer_with_prefix('1111')
        prefix = bs.Bits('0b0000')
        peer_a = self.helper.peer_with_prefix('0000')
        query_group_id = self.helper.create_query_group(peer_a)
        self.assertTrue(peer.find_query_peers_for(prefix, set(), 1, 0, None))
        self.assertTrue(peer.peer_id in peer.query_groups[query_group_id])
        self.assertTrue(peer.peer_id
                        in self.helper.all_query_groups[query_group_id])
        self.assertTrue(peer.peer_id in peer_a.query_groups[query_group_id])

    def test_joins_multiple_groups_if_necessary(self):
        peer = self.helper.peer_with_prefix('1111')
        prefix = bs.Bits('0b0000')
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0000')
        query_group_id_1 = self.helper.create_query_group(peer_a)
        query_group_id_2 = self.helper.create_query_group(peer_b)
        self.assertTrue(peer.find_query_peers_for(prefix, set(), 2, 0, None))
        self.assertTrue(peer.peer_id in peer.query_groups[query_group_id_1])
        self.assertTrue(peer.peer_id in peer.query_groups[query_group_id_2])
        self.assertTrue(peer.peer_id
                        in self.helper.all_query_groups[query_group_id_1])
        self.assertTrue(
            peer.peer_id
            in self.helper.all_query_groups[query_group_id_2])
        self.assertTrue(peer.peer_id in peer_a.query_groups[query_group_id_1])
        self.assertTrue(peer.peer_id in peer_b.query_groups[query_group_id_2])

    def test_doesnt_join_more_groups_than_necessary(self):
        peer = self.helper.peer_with_prefix('1111')
        prefix = bs.Bits('0b0000')
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0000')
        query_group_id_1 = self.helper.create_query_group(peer_a)
        query_group_id_2 = self.helper.create_query_group(peer_b)
        self.assertTrue(peer.find_query_peers_for(prefix, set(), 1, 0, None))
        self.assertEqual(len(peer.query_groups), 1)
        self.assertTrue(
            (peer.peer_id
             in self.helper.all_query_groups[query_group_id_1])
            ^ (peer.peer_id
               in self.helper.all_query_groups[query_group_id_2]))
        self.assertTrue((peer.peer_id in peer_a.query_groups[query_group_id_1])
                        ^ (peer.peer_id
                        in peer_b.query_groups[query_group_id_2]))

    def test_ignores_groups_its_already_in(self):
        peer = self.helper.peer_with_prefix('1111')
        prefix = bs.Bits('0b0000')
        peer_a = self.helper.peer_with_prefix('0000')
        self.helper.create_query_group(peer, peer_a)
        self.assertFalse(peer.find_query_peers_for(prefix,
                                                   set((peer_a.peer_id,)), 1,
                                                   0, None))

    def test_ignores_peers_it_already_knows_in_other_groups(self):
        peer = self.helper.peer_with_prefix('1111')
        prefix = bs.Bits('0b0000')
        peer_a = self.helper.peer_with_prefix('0000')
        self.helper.create_query_group(peer, peer_a)
        query_group_id = self.helper.create_query_group(peer_a)
        self.assertFalse(peer.find_query_peers_for(prefix,
                                                   set((peer_a.peer_id,)), 1,
                                                   0, None))
        self.assertEqual(len(peer.query_groups), 1)
        self.assertFalse(query_group_id in peer.query_groups)
        self.assertFalse(peer.peer_id
                         in self.helper.all_query_groups[query_group_id])
        self.assertFalse(peer.peer_id
                         in peer_a.query_groups[query_group_id])

    def test_still_returns_false_if_not_enough_peers_found(self):
        peer = self.helper.peer_with_prefix('1111')
        prefix = bs.Bits('0b0000')
        peer_a = self.helper.peer_with_prefix('0000')
        query_group_id = self.helper.create_query_group(peer_a)
        self.assertFalse(peer.find_query_peers_for(prefix, set(), 2, 0, None))
        self.assertTrue(peer.peer_id in peer.query_groups[query_group_id])
        self.assertTrue(peer.peer_id
                        in self.helper.all_query_groups[query_group_id])
        self.assertTrue(peer.peer_id in peer_a.query_groups[query_group_id])

    def test_doesnt_join_full_groups(self):
        peer = self.helper.peer_with_prefix('1111')
        prefix = bs.Bits('0b0000')
        peers = [self.helper.peer_with_prefix('0000') for _
                 in range(self.helper.settings['max_desired_group_size'])]
        query_group_id = self.helper.create_query_group(*peers)
        self.assertFalse(peer.find_query_peers_for(prefix, set(), 1, 0, None))
        self.assertEqual(len(peer.query_groups), 0)
        self.assertFalse(peer.peer_id
                         in self.helper.all_query_groups[query_group_id])
        for p in peers:
            self.assertFalse(peer.peer_id
                             in p.query_groups[query_group_id])

    def test_doesnt_join_groups_with_lower_usefulness(self):
        peer = self.helper.peer_with_prefix('1111')
        prefix = bs.Bits('0b0000')
        peer_a = self.helper.peer_with_prefix('0000')
        query_group_id = self.helper.create_query_group(peer_a)
        self.assertFalse(peer.find_query_peers_for(prefix, set(), 1, 6, None))
        self.assertFalse(query_group_id in peer.query_groups)
        self.assertFalse(peer.peer_id
                         in self.helper.all_query_groups[query_group_id])
        self.assertFalse(peer.peer_id in peer_a.query_groups[query_group_id])


class TestLeaveQueryGroup(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_removes_group_from_own_group_dict(self):
        peer = self.helper.peer_with_prefix('')
        query_group_id = self.helper.create_query_group(peer)
        self.assertTrue(query_group_id in peer.query_groups)
        peer.leave_query_group(query_group_id, None)
        self.assertFalse(query_group_id in peer.query_groups)

    def test_removes_itself_from_query_peers_copies(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        query_group_id = self.helper.create_query_group(peer, peer_a)
        self.assertTrue(peer.peer_id in peer_a.query_groups[query_group_id])
        peer.leave_query_group(query_group_id, None)
        self.assertFalse(peer.peer_id in peer_a.query_groups[query_group_id])

    def test_removes_itself_from_all_query_groups(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        query_group_id = self.helper.create_query_group(peer, peer_a)
        self.assertTrue(peer.peer_id
                        in self.helper.all_query_groups[query_group_id])
        peer.leave_query_group(query_group_id, None)
        self.assertFalse(peer.peer_id
                         in self.helper.all_query_groups[query_group_id])

    def test_removes_group_from_history_dict(self):
        peer = self.helper.peer_with_prefix('')
        query_group_id = self.helper.create_query_group(peer)
        peer.update_query_group_history()
        self.assertTrue(query_group_id in peer.query_group_history)
        peer.leave_query_group(query_group_id, None)
        self.assertFalse(query_group_id in peer.query_group_history)


class TestMaxPeerReputation(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_no_groups(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        self.assertEqual(
            peer.max_peer_reputation(peer_a.peer_id, peer_a.peer_id), 0)
        self.assertEqual(
            peer.max_peer_reputation(peer.peer_id, peer_a.peer_id), 0)

    def test_no_shared_groups(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer, peer_a)
        self.assertEqual(
            peer.max_peer_reputation(peer_b.peer_id, peer_b.peer_id), 0)
        self.assertEqual(
            peer.max_peer_reputation(peer.peer_id, peer_b.peer_id), 0)

    def test_one_shared_group(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        gid = self.helper.create_query_group(peer, peer_a)
        peer.query_groups[gid][peer.peer_id].reputation = 5
        peer.query_groups[gid][peer_a.peer_id].reputation = 6
        self.assertEqual(
            peer.max_peer_reputation(peer_a.peer_id, peer_a.peer_id), 6)
        self.assertEqual(
            peer.max_peer_reputation(peer.peer_id, peer_a.peer_id), 5)

    def test_multiple_shared_groups(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        gid_1 = self.helper.create_query_group(peer, peer_a)
        gid_2 = self.helper.create_query_group(peer, peer_a)
        peer.query_groups[gid_1][peer.peer_id].reputation = 5
        peer.query_groups[gid_1][peer_a.peer_id].reputation = 6
        peer.query_groups[gid_2][peer.peer_id].reputation = 4
        peer.query_groups[gid_2][peer_a.peer_id].reputation = 7
        self.assertEqual(
            peer.max_peer_reputation(peer_a.peer_id, peer_a.peer_id), 7)
        self.assertEqual(
            peer.max_peer_reputation(peer.peer_id, peer_a.peer_id), 5)


class TestMinPeerReputation(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_no_groups(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        self.assertEqual(peer.min_peer_reputation(peer_a.peer_id), 0)

    def test_no_shared_groups(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer, peer_b)
        self.assertEqual(peer.min_peer_reputation(peer_a.peer_id), 0)

    def test_one_shared_group(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        gid = self.helper.create_query_group(peer, peer_a)
        peer.query_groups[gid][peer_a.peer_id].reputation = 5
        self.assertEqual(peer.min_peer_reputation(peer_a.peer_id), 5)

    def test_multiple_shared_groups(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        gid_1 = self.helper.create_query_group(peer, peer_a)
        gid_2 = self.helper.create_query_group(peer, peer_a)
        gid_3 = self.helper.create_query_group(peer, peer_a)
        peer.query_groups[gid_1][peer_a.peer_id].reputation = 5
        peer.query_groups[gid_2][peer_a.peer_id].reputation = 4
        peer.query_groups[gid_3][peer_a.peer_id].reputation = 6
        self.assertEqual(peer.min_peer_reputation(peer_a.peer_id), 4)


class TestExpectedMinReputation(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_no_groups(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        self.assertEqual(
            peer.expected_min_reputation(peer_a.peer_id), 0)

    def test_no_shared_groups(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer, peer_a)
        self.assertEqual(
            peer.expected_min_reputation(peer_b.peer_id), 0)

    def test_one_shared_group(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        gid = self.helper.create_query_group(peer, peer_a)
        peer.query_groups[gid][peer.peer_id].reputation = 5
        self.assertEqual(
            peer.expected_min_reputation(peer_a.peer_id), 5)

    def test_multiple_shared_groups(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        gid_1 = self.helper.create_query_group(peer, peer_a)
        gid_2 = self.helper.create_query_group(peer, peer_a)
        peer.query_groups[gid_1][peer.peer_id].reputation = 5
        peer.query_groups[gid_2][peer.peer_id].reputation = 7
        self.assertEqual(
            peer.expected_min_reputation(peer_a.peer_id), 5)

    def test_considers_expected_penalties_from_same_peer(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        gid = self.helper.create_query_group(peer, peer_a)
        peer.query_groups[gid][peer.peer_id].reputation = 5
        peer.expected_penalties[peer_a.peer_id] = [(0, -2)]
        self.assertEqual(
            peer.expected_min_reputation(peer_a.peer_id), 3)

    def test_considers_expected_penalties_from_other_peer(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        gid = self.helper.create_query_group(peer, peer_a, peer_b)
        peer.query_groups[gid][peer.peer_id].reputation = 5
        peer.expected_penalties[peer_b.peer_id] = [(0, -2)]
        self.assertEqual(
            peer.expected_min_reputation(peer_a.peer_id), 3)

    def test_considers_multiple_expected_penalties_from_different_peers(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        gid = self.helper.create_query_group(peer, peer_a, peer_b)
        peer.query_groups[gid][peer.peer_id].reputation = 5
        peer.expected_penalties[peer_a.peer_id] = [(0, -1)]
        peer.expected_penalties[peer_b.peer_id] = [(0, -2)]
        self.assertEqual(
            peer.expected_min_reputation(peer_a.peer_id), 2)

    def test_considers_multiple_expected_penalties_from_the_same_peer(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        gid = self.helper.create_query_group(peer, peer_a, peer_b)
        peer.query_groups[gid][peer.peer_id].reputation = 5
        peer.expected_penalties[peer_a.peer_id] = [(0, -1), (1, -1)]
        self.assertEqual(
            peer.expected_min_reputation(peer_a.peer_id), 3)

    def test_considers_expected_penalties_for_multiple_groups(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        gid_1 = self.helper.create_query_group(peer, peer_a)
        gid_2 = self.helper.create_query_group(peer, peer_a)
        peer.query_groups[gid_1][peer.peer_id].reputation = 5
        peer.query_groups[gid_2][peer.peer_id].reputation = 4
        peer.expected_penalties[peer_a.peer_id] = [(0, -2)]
        self.assertEqual(
            peer.expected_min_reputation(peer_a.peer_id), 2)

    def test_doesnt_consider_expected_penalties_from_other_group(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        gid = self.helper.create_query_group(peer, peer_a)
        self.helper.create_query_group(peer, peer_b)
        peer.query_groups[gid][peer.peer_id].reputation = 5
        peer.expected_penalties[peer_b.peer_id] = [(0, -2)]
        self.assertEqual(
            peer.expected_min_reputation(peer_a.peer_id), 5)

    def test_doesnt_consider_expected_penalties_after_a_timeout(self):
        peer = self.helper.peer_with_prefix('')
        peer_a = self.helper.peer_with_prefix('')
        gid = self.helper.create_query_group(peer, peer_a)
        peer.query_groups[gid][peer.peer_id].reputation = 5
        timeout_time = 11
        peer.expected_penalties[peer_a.peer_id] = [(timeout_time, -2, 0)]

        self.helper.schedule_in(timeout_time + 1, lambda: None)
        self.helper.env.run()
        self.assertEqual(
            peer.expected_min_reputation(peer_a.peer_id), 5)


class TestCalculateReputation(unittest.TestCase):
    def test_doesnt_go_below_zero(self):
        ra = {'type': 'none'}
        self.assertEqual(p.calculate_reputation(ra, 1, -2), 0)

    def test_doesnt_attenuate_anything(self):
        ra = {'type': 'none'}
        self.assertEqual(p.calculate_reputation(ra, 20, 2), 22)

    def test_attenuates_rewards_by_a_constant_coefficient(self):
        ra = {
            'type': 'constant',
            'coefficient': 0.5,
            'lower_bound': 10,
            'upper_bound': 20
        }
        self.assertEqual(p.calculate_reputation(ra, 5, 2), 7)
        self.assertEqual(p.calculate_reputation(ra, 9, 2), 10.5)
        self.assertEqual(p.calculate_reputation(ra, 10, 2), 11)
        self.assertEqual(p.calculate_reputation(ra, 12, 2), 13)
        self.assertEqual(p.calculate_reputation(ra, 12.2, 2.6), 13.5)
        self.assertEqual(p.calculate_reputation(ra, 15, 5), 17.5)
        self.assertEqual(p.calculate_reputation(ra, 19, 5), 20)
        self.assertEqual(p.calculate_reputation(ra, 20, 2), 20)
        self.assertEqual(p.calculate_reputation(ra, 30, 1000), 20)
        self.assertEqual(p.calculate_reputation(ra, 15, -2), 13)

    def test_attenuates_rewards_by_exponential(self):
        ra = {
            'type': 'exponential',
            'exponent': 0.5,
            'coefficient': 0.5,
            'lower_bound': 10,
            'upper_bound': 20
        }
        self.assertEqual(p.calculate_reputation(ra, 5, 4), 9)
        self.assertEqual(p.calculate_reputation(ra, 9, 5), 11)
        self.assertEqual(p.calculate_reputation(ra, 10, 4), 11)
        self.assertEqual(p.calculate_reputation(ra, 11, 5), 11.5)
        self.assertEqual(p.calculate_reputation(ra, 11.5, 3.25), 11.75)
        self.assertEqual(p.calculate_reputation(ra, 19, 76), 20)
        self.assertEqual(p.calculate_reputation(ra, 20, 1000), 20)
        self.assertEqual(p.calculate_reputation(ra, 30, 1000), 20)
        self.assertEqual(p.calculate_reputation(ra, 15, -2), 13)
        ra['exponent'] = 0.4
        self.assertEqual(p.calculate_reputation(ra, 10, 32 ** 0.5), 11)
        self.assertEqual(p.calculate_reputation(ra, 10, 32), 12)
        self.assertEqual(p.calculate_reputation(ra, 11, 32 - 32 ** 0.5), 12)
        ra['exponent'] = 2
        self.assertAlmostEqual(p.calculate_reputation(ra, 10, 2 ** 0.5), 11)
        self.assertAlmostEqual(
            p.calculate_reputation(ra, 11, 2 - 2 ** 0.5), 12)

    def test_attenuates_rewards_harmonically(self):
        ra = {
            'type': 'harmonic',
            'a': 2,
            'k': 2,
            'lower_bound': 10,
            'upper_bound': 20
        }
        self.assertEqual(p.calculate_reputation(ra, 5, 4), 9)
        self.assertEqual(p.calculate_reputation(ra, 9, 2), 10.5)
        self.assertEqual(p.calculate_reputation(ra, 10, 1), 10.5)
        self.assertEqual(p.calculate_reputation(ra, 10, 2), 11)
        self.assertEqual(p.calculate_reputation(ra, 11, 2), 11.5)
        self.assertEqual(p.calculate_reputation(ra, 11, 3), 11.75)
        self.assertEqual(p.calculate_reputation(ra, 11, 4), 12)
        self.assertEqual(p.calculate_reputation(ra, 12, 3), 12.5)
        self.assertEqual(p.calculate_reputation(ra, 12, 6), 13)
        self.assertEqual(p.calculate_reputation(ra, 13.5, 2), 13.75)
        self.assertEqual(p.calculate_reputation(ra, 11.25, 0.75), 11.4375)
        self.assertEqual(p.calculate_reputation(ra, 10, 90), 19)
        self.assertEqual(p.calculate_reputation(ra, 19, 2), 19.1)
        self.assertEqual(p.calculate_reputation(ra, 19, 5), 19.25)
        self.assertEqual(p.calculate_reputation(ra, 20, 1000), 20)
        self.assertEqual(p.calculate_reputation(ra, 30, 1000), 20)
        self.assertEqual(p.calculate_reputation(ra, 15, -2), 13)


class TestFindMissingQueryPeers(unittest.TestCase):
    @unittest.mock.patch('util.Network.send_query')
    def setUp(self, mocked_send_query):
        self.helper = TestHelper()
        self.helper.network.send_query = mocked_send_query
        self.mocked_send_query = mocked_send_query
        self.helper.settings['prefix_length'] = 2
        self.helper.settings['min_desired_query_peers'] = 1
        self.helper.settings['ignore_non_existent_subprefixes'] = False
        self.helper.settings['query_sync_for_subprefixes'] = False

    def test_queries_for_uncovered_subprefixes(self):
        peer = self.helper.peer_with_prefix('00')
        peer_a = self.helper.peer_with_prefix('10')
        self.helper.create_query_group(peer, peer_a)
        peer.find_missing_query_peers()
        self.mocked_send_query.assert_called_once_with(
            peer.peer_id, peer.address, peer_a.address, bs.Bits('0b01'), ANY)

    def test_queries_covered_prefixes_if_less_than_desired(self):
        self.helper.settings['min_desired_query_peers'] = 2
        peer = self.helper.peer_with_prefix('00')
        peer_a = self.helper.peer_with_prefix('10')
        peer_b = self.helper.peer_with_prefix('10')
        peer_c = self.helper.peer_with_prefix('01')
        self.helper.create_query_group(peer, peer_a, peer_b)
        peer.find_missing_query_peers()
        self.mocked_send_query.assert_called_once_with(
            peer.peer_id, peer.address,
            arg_any_of(peer_a.address, peer_b.address, peer_c.address),
            bs.Bits('0b01'), ANY)

    def test_doesnt_query_if_query_is_pending(self):
        peer = self.helper.peer_with_prefix('00')
        peer_a = self.helper.peer_with_prefix('10')
        self.helper.create_query_group(peer, peer_a)
        peer.pending_queries[bs.Bits('0b0100101')] = None
        peer.find_missing_query_peers()
        self.mocked_send_query.assert_not_called()

    def test_queries_sync_peers(self):
        self.helper.settings['query_sync_for_subprefixes'] = True
        peer = self.helper.peer_with_prefix('00')
        peer_a = self.helper.peer_with_prefix('00')
        peer.find_missing_query_peers()
        self.assertEqual(len(self.mocked_send_query.call_args_list), 2)
        self.assertTrue(
            call(peer.peer_id, peer.address, peer_a.address, bs.Bits('0b01'),
                 ANY)
            in self.mocked_send_query.call_args_list)
        self.assertTrue(
            call(peer.peer_id, peer.address, peer_a.address, bs.Bits('0b1'),
                 ANY)
            in self.mocked_send_query.call_args_list)

    def test_ignores_non_existent_subprefixes(self):
        self.helper.settings['ignore_non_existent_subprefixes'] = True
        peer = self.helper.peer_with_prefix('00')
        peer_a = self.helper.peer_with_prefix('10')
        self.helper.create_query_group(peer, peer_a)
        peer.find_missing_query_peers()
        self.mocked_send_query.assert_not_called()
