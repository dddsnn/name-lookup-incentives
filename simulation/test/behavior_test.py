import unittest
from unittest.mock import ANY, call
from test_utils import (TestHelper, pending_query, PeerFactory, set_containing,
                        arg_with)
import bitstring as bs


class TestPeerSelection(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.peer_factory = PeerFactory(self.helper.settings)

    def test_selects_peers(self):
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1100')
        peer_c = self.peer_factory.peer_with_prefix('1000')
        self.peer_factory.create_query_group(peer_a, peer_b, peer_c)
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        self.assertEqual(set(selected), set((peer_b.peer_id, peer_c.peer_id)))

    def test_doesnt_select_peers_with_smaller_or_equal_overlap(self):
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('0000')
        peer_c = self.peer_factory.peer_with_prefix('0011')
        peer_d = self.peer_factory.peer_with_prefix('1000')
        self.peer_factory.create_query_group(peer_a, peer_b, peer_c, peer_d)
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('0001'))
        self.assertEqual(selected, [])

    def test_only_selects_peers_once(self):
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1111')
        self.peer_factory.create_query_group(peer_a, peer_b)
        self.peer_factory.create_query_group(peer_a, peer_b)
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_b.peer_id])

    def test_sorts_by_overlap_length(self):
        self.helper.settings['query_peer_selection'] = 'overlap'
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1000')
        peer_c = self.peer_factory.peer_with_prefix('1111')
        peer_d = self.peer_factory.peer_with_prefix('1100')
        self.peer_factory.create_query_group(peer_a, peer_b, peer_c, peer_d)
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_c.peer_id, peer_d.peer_id,
                                    peer_b.peer_id])

    def test_puts_high_rep_peers_to_the_back(self):
        self.helper.settings['query_peer_selection'] = 'overlap_high_rep_last'
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1111')
        peer_c = self.peer_factory.peer_with_prefix('1000')
        query_group_id = self.peer_factory.create_query_group(peer_a, peer_b,
                                                              peer_c)
        enough_rep = (self.helper.settings['reputation_buffer_factor']
                      * self.helper.settings['no_penalty_reputation'])
        peer_a.query_groups[query_group_id][peer_b.peer_id].reputation\
            = enough_rep + 1
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_c.peer_id, peer_b.peer_id])

    def test_overlap_high_rep_lastconsiders_minimum_rep(self):
        self.helper.settings['query_peer_selection'] = 'overlap_high_rep_last'
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1111')
        peer_c = self.peer_factory.peer_with_prefix('1000')
        query_group_id_1 = self.peer_factory.create_query_group(peer_a, peer_b,
                                                                peer_c)
        self.peer_factory.create_query_group(peer_a, peer_b, peer_c)
        enough_rep = (self.helper.settings['reputation_buffer_factor']
                      * self.helper.settings['no_penalty_reputation'])
        peer_a.query_groups[query_group_id_1][peer_b.peer_id].reputation\
            = enough_rep + 1
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_b.peer_id, peer_c.peer_id])

    @unittest.mock.patch('random.shuffle')
    def test_shuffles(self, mocked_shuffle):
        self.helper.settings['query_peer_selection'] = 'shuffled'
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1000')
        self.peer_factory.create_query_group(peer_a, peer_b)
        peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        mocked_shuffle.assert_called_once()

    def test_sorts_by_overlap_and_reputation(self):
        self.helper.settings['query_peer_selection'] = 'overlap_rep_sorted'
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1111')
        peer_c = self.peer_factory.peer_with_prefix('1111')
        peer_d = self.peer_factory.peer_with_prefix('1000')
        peer_e = self.peer_factory.peer_with_prefix('1000')
        query_group_id = self.peer_factory.create_query_group(
            peer_a, peer_b, peer_c, peer_d, peer_e)
        peer_a.query_groups[query_group_id][peer_b.peer_id].reputation = 6
        peer_a.query_groups[query_group_id][peer_c.peer_id].reputation = 5
        peer_a.query_groups[query_group_id][peer_d.peer_id].reputation = 2
        peer_a.query_groups[query_group_id][peer_e.peer_id].reputation = 3
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_c.peer_id, peer_b.peer_id,
                                    peer_d.peer_id, peer_e.peer_id])

    def test_overlap_rep_sorted_considers_minimum_rep(self):
        self.helper.settings['query_peer_selection'] = 'overlap_rep_sorted'
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1111')
        peer_c = self.peer_factory.peer_with_prefix('1111')
        peer_d = self.peer_factory.peer_with_prefix('1111')
        query_group_id_1 = self.peer_factory.create_query_group(
            peer_a, peer_b, peer_c, peer_d)
        query_group_id_2 = self.peer_factory.create_query_group(
            peer_a, peer_b, peer_c, peer_d)
        peer_a.query_groups[query_group_id_1][peer_b.peer_id].reputation = 2
        peer_a.query_groups[query_group_id_1][peer_c.peer_id].reputation = 4
        peer_a.query_groups[query_group_id_1][peer_d.peer_id].reputation = 6
        peer_a.query_groups[query_group_id_2][peer_b.peer_id].reputation = 7
        peer_a.query_groups[query_group_id_2][peer_c.peer_id].reputation = 1
        peer_a.query_groups[query_group_id_2][peer_d.peer_id].reputation = 3
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_c.peer_id, peer_b.peer_id,
                                    peer_d.peer_id])

    def test_sorts_by_reputation(self):
        self.helper.settings['query_peer_selection'] = 'rep_sorted'
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1111')
        peer_c = self.peer_factory.peer_with_prefix('1111')
        peer_d = self.peer_factory.peer_with_prefix('1000')
        peer_e = self.peer_factory.peer_with_prefix('1000')
        query_group_id = self.peer_factory.create_query_group(
            peer_a, peer_b, peer_c, peer_d, peer_e)
        peer_a.query_groups[query_group_id][peer_b.peer_id].reputation = 6
        peer_a.query_groups[query_group_id][peer_c.peer_id].reputation = 5
        peer_a.query_groups[query_group_id][peer_d.peer_id].reputation = 2
        peer_a.query_groups[query_group_id][peer_e.peer_id].reputation = 3
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_d.peer_id, peer_e.peer_id,
                                    peer_c.peer_id, peer_b.peer_id])

    def test_rep_sorted_considers_minimum_rep(self):
        self.helper.settings['query_peer_selection'] = 'rep_sorted'
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1111')
        peer_c = self.peer_factory.peer_with_prefix('1111')
        peer_d = self.peer_factory.peer_with_prefix('1000')
        query_group_id_1 = self.peer_factory.create_query_group(
            peer_a, peer_b, peer_c, peer_d)
        query_group_id_2 = self.peer_factory.create_query_group(
            peer_a, peer_b, peer_c, peer_d)
        peer_a.query_groups[query_group_id_1][peer_b.peer_id].reputation = 2
        peer_a.query_groups[query_group_id_1][peer_c.peer_id].reputation = 4
        peer_a.query_groups[query_group_id_1][peer_d.peer_id].reputation = 6
        peer_a.query_groups[query_group_id_2][peer_b.peer_id].reputation = 7
        peer_a.query_groups[query_group_id_2][peer_c.peer_id].reputation = 1
        peer_a.query_groups[query_group_id_2][peer_d.peer_id].reputation = 3
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_c.peer_id, peer_b.peer_id,
                                    peer_d.peer_id])


class TestOnQuerySelf(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.peer_factory = PeerFactory(self.helper.settings)

    def test_responds(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('')
        querying_peer_id = self.peer_factory.id_with_prefix('')
        peer.send_query.return_value = None
        behavior.on_query_self(querying_peer_id, peer.peer_id, None)
        peer.send_response.assert_called_once_with(
            querying_peer_id, set_containing(peer.peer_id),
            arg_with(peer_id=peer.peer_id), ANY, delay=ANY)

    def test_applies_delay(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('')
        querying_peer, _\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('')
        gid = self.peer_factory.create_query_group(peer, querying_peer)
        npr = self.helper.settings['no_penalty_reputation']
        delay = 4
        peer.query_groups[gid][querying_peer.peer_id].reputation = npr - delay
        peer.send_query.return_value = None
        behavior.on_query_self(querying_peer.peer_id, peer.peer_id, None)
        peer.send_response.assert_called_once_with(
            querying_peer.peer_id, ANY, ANY, ANY, delay=delay)

    def test_does_nothing_if_enough_reputation(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('')
        querying_peer, _\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('')
        query_group_id = self.peer_factory.create_query_group(peer,
                                                              querying_peer)
        enough_rep = (self.helper.settings['reputation_buffer_factor']
                      * self.helper.settings['no_penalty_reputation'])
        peer.query_groups[query_group_id][peer.peer_id].reputation\
            = enough_rep + 1
        peer.send_query.return_value = None
        behavior.on_query_self(querying_peer.peer_id, peer.peer_id, None)
        peer.send_response.assert_not_called()
        peer.expect_penalty.assert_called_once_with(
            querying_peer.peer_id,
            self.helper.settings['timeout_query_penalty'],
            behavior.decide_delay(querying_peer.peer_id)
            + self.helper.settings['expected_penalty_timeout_buffer'], ANY)


class TestOnQuerySync(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.peer_factory = PeerFactory(self.helper.settings)

    def test_responds(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        sync_peer, _\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        querying_peer_id = self.peer_factory.id_with_prefix('')
        peer.send_query.return_value = None
        behavior.on_query_sync(querying_peer_id, peer.peer_id,
                               sync_peer.info(), None)
        peer.send_response.assert_called_once_with(
            querying_peer_id, set_containing(peer.peer_id),
            arg_with(peer_id=sync_peer.peer_id), ANY, delay=ANY)

    def test_applies_penalty(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        sync_peer, _\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        querying_peer, _\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('')
        gid = self.peer_factory.create_query_group(peer, querying_peer)
        npr = self.helper.settings['no_penalty_reputation']
        delay = 4
        peer.query_groups[gid][querying_peer.peer_id].reputation = npr - delay
        peer.send_query.return_value = None
        behavior.on_query_sync(querying_peer.peer_id, peer.peer_id,
                               sync_peer.info(), None)
        peer.send_response.assert_called_once_with(
            querying_peer.peer_id, ANY, ANY, ANY, delay=delay)

    def test_does_nothing_if_enough_reputation(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        sync_peer, _\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        querying_peer, _\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('')
        query_group_id = self.peer_factory.create_query_group(peer,
                                                              querying_peer)
        enough_rep = (self.helper.settings['reputation_buffer_factor']
                      * self.helper.settings['no_penalty_reputation'])
        peer.query_groups[query_group_id][peer.peer_id].reputation\
            = enough_rep + 1
        peer.send_query.return_value = None
        behavior.on_query_sync(querying_peer.peer_id, peer.peer_id,
                               sync_peer.info(), None)
        peer.send_response.assert_not_called()
        peer.expect_penalty.assert_called_once_with(
            querying_peer.peer_id,
            self.helper.settings['timeout_query_penalty'],
            behavior.decide_delay(querying_peer.peer_id)
            + self.helper.settings['expected_penalty_timeout_buffer'], ANY)


class TestOnQuery(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.peer_factory = PeerFactory(self.helper.settings)

    def test_adds_pending_query(self):
        peer_a, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        peer_b, _\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        self.peer_factory.create_query_group(peer_a, peer_b)
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None)
        peer_a.add_pending_query.assert_called_once_with(
            queried_id, pending_query(querying_peer_id, queried_id,
                                      [peer_b.peer_id]))

    def test_sends_query(self):
        peer_a, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        peer_b, _\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        self.peer_factory.create_query_group(peer_a, peer_b)
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None)
        peer_a.send_query.assert_called_once_with(
            queried_id, pending_query(querying_peer_id, queried_id,
                                      [peer_b.peer_id]), ANY)

    def test_just_finalizes_if_query_from_self_and_no_known_peers(self):
        peer_a, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('')
        behavior.on_query(peer_a.peer_id,
                          self.peer_factory.id_with_prefix(''), None)
        peer_a.send_response.assert_not_called()
        peer_a.send_query.assert_not_called()
        peer_a.add_pending_query.assert_not_called()
        peer_a.finalize_query.assert_called_with('impossible', ANY)

    def test_informs_querying_peers_of_impossible_query(self):
        peer_a, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('')
        querying_peer_id = self.peer_factory.id_with_prefix('')
        queried_id = self.peer_factory.id_with_prefix('')
        peer_a.send_response.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None)
        peer_a.send_response.assert_called_once_with(
            querying_peer_id, set((queried_id,)), None, ANY, delay=ANY)
        peer_a.expect_penalty.assert_called_once_with(
            querying_peer_id, self.helper.settings['failed_query_penalty'],
            behavior.decide_delay(querying_peer_id)
            + self.helper.settings['expected_penalty_timeout_buffer'], ANY)

    def test_does_nothing_if_enough_reputation(self):
        peer_a, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        querying_peer, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        query_group_id = self.peer_factory.create_query_group(peer_a, peer_b,
                                                              querying_peer)
        enough_rep = (self.helper.settings['reputation_buffer_factor']
                      * self.helper.settings['no_penalty_reputation'])
        peer_a.query_groups[query_group_id][peer_a.peer_id].reputation\
            = enough_rep + 1
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer.peer_id, queried_id, None)
        peer_a.expect_penalty.assert_called_once_with(
            querying_peer.peer_id,
            self.helper.settings['timeout_query_penalty'],
            behavior.decide_delay(querying_peer.peer_id)
            + self.helper.settings['expected_penalty_timeout_buffer'], ANY)
        peer_a.send_response.assert_not_called()
        peer_a.send_query.assert_not_called()
        peer_a.add_pending_query.assert_not_called()

    def test_considers_min_rep_in_all_shared_query_groups(self):
        peer_a, behavior =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        querying_peer, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        query_group_id = self.peer_factory.create_query_group(peer_a, peer_b,
                                                              querying_peer)
        self.peer_factory.create_query_group(peer_a, peer_b, querying_peer)
        enough_rep = (self.helper.settings['reputation_buffer_factor']
                      * self.helper.settings['no_penalty_reputation'])
        peer_a.query_groups[query_group_id][peer_a.peer_id].reputation\
            = enough_rep + 1
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer.peer_id, queried_id, None)
        peer_a.send_query.assert_called_once()

    def test_query_all_also_queries_query_peers_with_smaller_overlap(self):
        peer_a, behavior =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        self.peer_factory.create_query_group(peer_a, peer_b)
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None, query_all=True)
        peer_a.send_query.assert_called_once_with(
            queried_id, pending_query(querying_peer_id, queried_id,
                                      [peer_b.peer_id]), ANY)

    def test_query_all_also_queries_sync_peers(self):
        peer_a, behavior =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        peer_a.sync_peers[peer_b.peer_id] = peer_b.info()
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None, query_all=True)
        peer_a.send_query.assert_called_once_with(
            queried_id, pending_query(querying_peer_id, queried_id,
                                      [peer_b.peer_id]), ANY)

    def test_query_all_sorts_by_overlap_length(self):
        self.helper.settings['query_peer_selection'] = 'overlap'
        peer_a, behavior =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        peer_c, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1110')
        peer_d, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1100')
        self.peer_factory.create_query_group(peer_a, peer_b, peer_c, peer_d)
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None, query_all=True)
        peer_a.send_query.assert_called_once_with(
            queried_id, pending_query(querying_peer_id, queried_id,
                                      [peer_c.peer_id, peer_d.peer_id,
                                       peer_b.peer_id]), ANY)

    def test_query_all_puts_high_rep_peers_to_the_back(self):
        self.helper.settings['query_peer_selection'] = 'overlap_high_rep_last'
        peer_a, behavior =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        peer_c, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1110')
        peer_d, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1100')
        query_group_id = self.peer_factory.create_query_group(peer_a, peer_b,
                                                              peer_c, peer_d)
        enough_rep = (self.helper.settings['reputation_buffer_factor']
                      * self.helper.settings['no_penalty_reputation'])
        peer_a.query_groups[query_group_id][peer_c.peer_id].reputation\
            = enough_rep + 1
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None, query_all=True)
        peer_a.send_query.assert_called_once_with(
            queried_id, pending_query(querying_peer_id, queried_id,
                                      [peer_d.peer_id, peer_b.peer_id,
                                       peer_c.peer_id]), ANY)

    def test_query_all_overlap_high_rep_last_considers_minimum_rep(self):
        self.helper.settings['query_peer_selection'] = 'overlap_high_rep_last'
        peer_a, behavior =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        peer_c, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1110')
        peer_d, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1100')
        query_group_id_1 = self.peer_factory.create_query_group(peer_a, peer_b,
                                                                peer_c, peer_d)
        self.peer_factory.create_query_group(peer_a, peer_c)
        enough_rep = (self.helper.settings['reputation_buffer_factor']
                      * self.helper.settings['no_penalty_reputation'])
        peer_a.query_groups[query_group_id_1][peer_c.peer_id].reputation\
            = enough_rep + 1
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None, query_all=True)
        peer_a.send_query.assert_called_once_with(
            queried_id, pending_query(querying_peer_id, queried_id,
                                      [peer_c.peer_id, peer_d.peer_id,
                                       peer_b.peer_id]), ANY)

    @unittest.mock.patch('random.shuffle')
    def test_query_all_shuffles(self, mocked_shuffle):
        self.helper.settings['query_peer_selection'] = 'shuffled'
        peer_a, behavior =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        self.peer_factory.create_query_group(peer_a, peer_b)
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None, query_all=True)
        mocked_shuffle.assert_called_once()

    def test_query_all_sorts_by_overlap_and_reputation(self):
        self.helper.settings['query_peer_selection'] = 'overlap_rep_sorted'
        peer_a, behavior =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_c, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_d, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        peer_e, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        query_group_id = self.peer_factory.create_query_group(
            peer_a, peer_b, peer_c, peer_d, peer_e)
        peer_a.query_groups[query_group_id][peer_b.peer_id].reputation = 6
        peer_a.query_groups[query_group_id][peer_c.peer_id].reputation = 5
        peer_a.query_groups[query_group_id][peer_d.peer_id].reputation = 2
        peer_a.query_groups[query_group_id][peer_e.peer_id].reputation = 3
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None, query_all=True)
        peer_a.send_query.assert_called_once_with(
            queried_id, pending_query(querying_peer_id, queried_id,
                                      [peer_c.peer_id, peer_b.peer_id,
                                       peer_d.peer_id, peer_e.peer_id]), ANY)

    def test_query_all_overlap_sorted_considers_minimum_rep(self):
        self.helper.settings['query_peer_selection'] = 'overlap_rep_sorted'
        peer_a, behavior =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_c, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_d, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        query_group_id_1 = self.peer_factory.create_query_group(
            peer_a, peer_b, peer_c, peer_d)
        query_group_id_2 = self.peer_factory.create_query_group(
            peer_a, peer_b, peer_c, peer_d)
        peer_a.query_groups[query_group_id_1][peer_b.peer_id].reputation = 2
        peer_a.query_groups[query_group_id_1][peer_c.peer_id].reputation = 4
        peer_a.query_groups[query_group_id_1][peer_d.peer_id].reputation = 6
        peer_a.query_groups[query_group_id_2][peer_b.peer_id].reputation = 7
        peer_a.query_groups[query_group_id_2][peer_c.peer_id].reputation = 1
        peer_a.query_groups[query_group_id_2][peer_d.peer_id].reputation = 3
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None, query_all=True)
        peer_a.send_query.assert_called_once_with(
            queried_id, pending_query(querying_peer_id, queried_id,
                                      [peer_c.peer_id, peer_b.peer_id,
                                       peer_d.peer_id]), ANY)

    def test_query_all_sorts_by_reputation(self):
        self.helper.settings['query_peer_selection'] = 'rep_sorted'
        peer_a, behavior =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_c, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_d, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        peer_e, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        query_group_id = self.peer_factory.create_query_group(
            peer_a, peer_b, peer_c, peer_d, peer_e)
        peer_a.query_groups[query_group_id][peer_b.peer_id].reputation = 6
        peer_a.query_groups[query_group_id][peer_c.peer_id].reputation = 5
        peer_a.query_groups[query_group_id][peer_d.peer_id].reputation = 2
        peer_a.query_groups[query_group_id][peer_e.peer_id].reputation = 3
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None, query_all=True)
        peer_a.send_query.assert_called_once_with(
            queried_id, pending_query(querying_peer_id, queried_id,
                                      [peer_d.peer_id, peer_e.peer_id,
                                       peer_c.peer_id, peer_b.peer_id]), ANY)

    def test_query_all_rep_sorted_considers_minimum_rep(self):
        self.helper.settings['query_peer_selection'] = 'rep_sorted'
        peer_a, behavior =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_c, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_d, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        query_group_id_1 = self.peer_factory.create_query_group(
            peer_a, peer_b, peer_c, peer_d)
        query_group_id_2 = self.peer_factory.create_query_group(
            peer_a, peer_b, peer_c, peer_d)
        peer_a.query_groups[query_group_id_1][peer_b.peer_id].reputation = 2
        peer_a.query_groups[query_group_id_1][peer_c.peer_id].reputation = 4
        peer_a.query_groups[query_group_id_1][peer_d.peer_id].reputation = 6
        peer_a.query_groups[query_group_id_2][peer_b.peer_id].reputation = 7
        peer_a.query_groups[query_group_id_2][peer_c.peer_id].reputation = 1
        peer_a.query_groups[query_group_id_2][peer_d.peer_id].reputation = 3
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None, query_all=True)
        peer_a.send_query.assert_called_once_with(
            queried_id, pending_query(querying_peer_id, queried_id,
                                      [peer_c.peer_id, peer_b.peer_id,
                                       peer_d.peer_id]), ANY)

    def test_query_all_doesnt_include_peers_multiple_times(self):
        peer_a, behavior =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        self.peer_factory.create_query_group(peer_a, peer_b)
        self.peer_factory.create_query_group(peer_a, peer_b)
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None, query_all=True)
        peer_a.send_query.assert_called_once_with(
            queried_id, pending_query(querying_peer_id, queried_id,
                                      [peer_b.peer_id]), ANY)


class TestQueryGroupPerforms(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.peer_factory = PeerFactory(self.helper.settings)

    def test_performs_if_history_doesnt_exist(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('')
        query_group_id = self.peer_factory.create_query_group(peer)
        self.assertTrue(behavior.query_group_performs(query_group_id))

    def test_performs_if_history_too_short(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('')
        query_group_id = self.peer_factory.create_query_group(peer)
        for _ in range(self.helper.settings['query_group_min_history'] - 1):
            peer.update_query_group_history()
        self.assertTrue(behavior.query_group_performs(query_group_id))

    def test_performs_if_enough_reputation(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('')
        query_group_id = self.peer_factory.create_query_group(peer)
        min_rep = (self.helper.settings['no_penalty_reputation']
                   * self.helper.settings['performance_no_penalty_fraction'])
        peer.query_groups[query_group_id][peer.peer_id].reputation = min_rep
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        self.assertTrue(behavior.query_group_performs(query_group_id))

    def test_performs_if_rep_rises_fast_enough(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('')
        query_group_id = self.peer_factory.create_query_group(peer)
        slope = self.helper.settings['performance_min_slope']
        for i in range(self.helper.settings['query_group_min_history']):
            peer.query_groups[query_group_id][peer.peer_id].reputation\
                = i * (slope + 0.01)
            peer.update_query_group_history()
        self.assertTrue(behavior.query_group_performs(query_group_id))

    def test_doesnt_perform_if_rep_rises_too_slowly(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('')
        query_group_id = self.peer_factory.create_query_group(peer)
        slope = self.helper.settings['performance_min_slope'] - 0.01
        for i in range(self.helper.settings['query_group_min_history']):
            peer.query_groups[query_group_id][peer.peer_id].reputation\
                = i * slope
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id))

    def test_accounts_for_history_interval(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('')
        interval = 10
        self.helper.settings['query_group_history_interval'] = interval
        query_group_id = self.peer_factory.create_query_group(peer)
        slope = self.helper.settings['performance_min_slope']
        for i in range(self.helper.settings['query_group_min_history']):
            peer.query_groups[query_group_id][peer.peer_id].reputation\
                = i * slope
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id))


class TestReevaluateQueryGroups(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.peer_factory = PeerFactory(self.helper.settings)

    def test_doesnt_do_anything_if_group_performs(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('0000')
        query_group_id = self.peer_factory.create_query_group(peer, peer_a)
        self.peer_factory.create_query_group(peer_b)
        self.assertTrue(behavior.query_group_performs(query_group_id))
        behavior.reevaluate_query_groups(None)
        peer.find_query_peers_for.assert_not_called()
        peer.leave_query_group.assert_not_called()

    def test_removes_non_performing_group_if_covered_by_other_group(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('0000')
        peer_c = self.peer_factory.peer_with_prefix('0000')
        query_group_id_1 = self.peer_factory.create_query_group(peer, peer_a)
        query_group_id_2 = self.peer_factory.create_query_group(peer, peer_b,
                                                                peer_c)
        peer.query_groups[query_group_id_2][peer.peer_id].reputation = 10
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id_1))
        self.assertTrue(behavior.query_group_performs(query_group_id_2))
        behavior.reevaluate_query_groups(None)
        peer.find_query_peers_for.assert_not_called()
        peer.leave_query_group.assert_called_once_with(query_group_id_1, ANY)

    def test_removes_non_performing_group_if_joined_replacement(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('0000')
        peer_c = self.peer_factory.peer_with_prefix('0000')
        query_group_id = self.peer_factory.create_query_group(peer, peer_a)
        self.peer_factory.create_query_group(peer_b, peer_c)
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id))
        behavior.reevaluate_query_groups(None)
        peer.find_query_peers_for.assert_called_once_with(bs.Bits('0b0'), ANY,
                                                          ANY, ANY, ANY)
        peer.leave_query_group.assert_called_once_with(query_group_id, ANY)

    def test_includes_already_covering_peers(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('0000')
        query_group_id_1 = self.peer_factory.create_query_group(peer, peer_a)
        query_group_id_2 = self.peer_factory.create_query_group(peer, peer_b)
        peer.query_groups[query_group_id_2][peer.peer_id].reputation = 10
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id_1))
        self.assertTrue(behavior.query_group_performs(query_group_id_2))
        behavior.reevaluate_query_groups(None)
        peer.find_query_peers_for.assert_called_once_with(
            bs.Bits('0b0'), set((peer_b.peer_id,)), ANY, ANY, ANY)

    def test_specifies_number_of_missing_peers(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('0000')
        query_group_id_1 = self.peer_factory.create_query_group(peer, peer_a)
        query_group_id_2 = self.peer_factory.create_query_group(peer, peer_b)
        peer.query_groups[query_group_id_2][peer.peer_id].reputation = 10
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id_1))
        self.assertTrue(behavior.query_group_performs(query_group_id_2))
        behavior.reevaluate_query_groups(None)
        peer.find_query_peers_for.assert_called_once_with(
            bs.Bits('0b0'), ANY, 1, ANY, ANY)

    def test_doesnt_remove_non_performing_group_if_no_replacement(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.peer_factory.peer_with_prefix('0000')
        query_group_id = self.peer_factory.create_query_group(peer, peer_a)
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id))
        behavior.reevaluate_query_groups(None)
        peer.leave_query_group.assert_not_called()

    def test_checks_all_subprefixes(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1110')
        peer_c = self.peer_factory.peer_with_prefix('0000')
        peer_d = self.peer_factory.peer_with_prefix('0000')
        query_group_id_1 = self.peer_factory.create_query_group(peer, peer_a,
                                                                peer_b)
        query_group_id_2 = self.peer_factory.create_query_group(peer_c, peer_d)
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id_1))
        behavior.reevaluate_query_groups(None)
        self.assertTrue(query_group_id_2 in peer.query_groups)
        peer.leave_query_group.assert_not_called()

    def test_removes_multiple_groups(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('0000')
        peer_c = self.peer_factory.peer_with_prefix('0000')
        peer_d = self.peer_factory.peer_with_prefix('0000')
        query_group_id_1 = self.peer_factory.create_query_group(peer, peer_a)
        query_group_id_2 = self.peer_factory.create_query_group(peer, peer_b)
        self.peer_factory.create_query_group(peer_c, peer_d)
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id_1))
        self.assertFalse(behavior.query_group_performs(query_group_id_2))
        behavior.reevaluate_query_groups(None)
        self.assertEqual(len(peer.leave_query_group.call_args_list), 2)
        self.assertTrue(call(query_group_id_1, ANY)
                        in peer.leave_query_group.call_args_list)
        self.assertTrue(call(query_group_id_2, ANY)
                        in peer.leave_query_group.call_args_list)

    def test_specifies_min_usefulness(self):
        peer, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.peer_factory.peer_with_prefix('0000')
        query_group_id = self.peer_factory.create_query_group(peer, peer_a)
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        peer.estimated_usefulness_in.return_value = 5
        self.assertFalse(behavior.query_group_performs(query_group_id))
        behavior.reevaluate_query_groups(None)
        peer.find_query_peers_for.assert_called_once_with(
            bs.Bits('0b0'), ANY, ANY, 5, ANY)
