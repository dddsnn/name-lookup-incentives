import unittest
from unittest.mock import ANY
from test_utils import TestHelper, pending_query, PeerFactory
from collections import OrderedDict


class TestPeerSelection(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.all_query_groups = OrderedDict()
        self.peer_factory = PeerFactory(self.all_query_groups,
                                        self.helper.settings)

    def test_selects_peers(self):
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1100')
        peer_c = self.peer_factory.peer_with_prefix('1000')
        self.helper.create_query_group(self.all_query_groups, peer_a, peer_b,
                                       peer_c)
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        self.assertEqual(set(selected), set((peer_b.peer_id, peer_c.peer_id)))

    def test_doesnt_select_peers_with_smaller_or_equal_overlap(self):
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('0000')
        peer_c = self.peer_factory.peer_with_prefix('0011')
        peer_d = self.peer_factory.peer_with_prefix('1000')
        self.helper.create_query_group(self.all_query_groups, peer_a, peer_b,
                                       peer_c, peer_d)
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('0001'))
        self.assertEqual(selected, [])

    def test_only_selects_peers_once(self):
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1111')
        self.helper.create_query_group(self.all_query_groups, peer_a, peer_b)
        self.helper.create_query_group(self.all_query_groups, peer_a, peer_b)
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_b.peer_id])

    def test_sorts_by_overlap_length(self):
        self.helper.settings['query_peer_selection'] = 'overlap'
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1000')
        peer_c = self.peer_factory.peer_with_prefix('1111')
        peer_d = self.peer_factory.peer_with_prefix('1100')
        self.helper.create_query_group(self.all_query_groups, peer_a, peer_b,
                                       peer_c, peer_d)
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_c.peer_id, peer_d.peer_id,
                                    peer_b.peer_id])

    def test_puts_high_rep_peers_to_the_back(self):
        self.helper.settings['query_peer_selection'] = 'overlap_low_rep_first'
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1111')
        peer_c = self.peer_factory.peer_with_prefix('1000')
        query_group_id = self.helper.create_query_group(self.all_query_groups,
                                                        peer_a, peer_b, peer_c)
        enough_rep = (self.helper.settings['reputation_buffer_factor']
                      * self.helper.settings['no_penalty_reputation'])
        peer_a.query_groups[query_group_id][peer_b.peer_id].reputation\
            = enough_rep + 1
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_c.peer_id, peer_b.peer_id])

    def test_considers_minimum_rep_in_all_shared_query_groups(self):
        self.helper.settings['query_peer_selection'] = 'overlap_low_rep_first'
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1111')
        peer_c = self.peer_factory.peer_with_prefix('1000')
        query_group_id_1 = self.helper.create_query_group(
            self.all_query_groups, peer_a, peer_b, peer_c)
        self.helper.create_query_group(self.all_query_groups, peer_a, peer_b,
                                       peer_c)
        enough_rep = (self.helper.settings['reputation_buffer_factor']
                      * self.helper.settings['no_penalty_reputation'])
        peer_a.query_groups[query_group_id_1][peer_b.peer_id].reputation\
            = enough_rep + 1
        selected = peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        self.assertEqual(selected, [peer_b.peer_id, peer_c.peer_id])

    @unittest.mock.patch('random.shuffle')
    def test_shuffles(self, mocked_shuffle):
        self.helper.settings['query_peer_selection'] = 'overlap_shuffled'
        peer_a = self.peer_factory.peer_with_prefix('0000')
        peer_b = self.peer_factory.peer_with_prefix('1000')
        self.helper.create_query_group(self.all_query_groups, peer_a, peer_b)
        peer_a.behavior.select_peers_to_query(
            self.peer_factory.id_with_prefix('1111'))
        mocked_shuffle.assert_called_once()


class TestOnQuery(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.peer_factory = PeerFactory({}, self.helper.settings)

    def test_adds_pending_query(self):
        peer_a, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        peer_b, _\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        self.helper.create_query_group({}, peer_a, peer_b)
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
        self.helper.create_query_group({}, peer_a, peer_b)
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

    def test_does_nothing_if_enough_reputation(self):
        peer_a, behavior\
            = self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1111')
        querying_peer, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        query_group_id = self.helper.create_query_group({}, peer_a, peer_b,
                                                        querying_peer)
        enough_rep = (self.helper.settings['reputation_buffer_factor']
                      * self.helper.settings['no_penalty_reputation'])
        peer_a.query_groups[query_group_id][peer_a.peer_id].reputation\
            = enough_rep + 1
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer.peer_id, queried_id, None)
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
        query_group_id = self.helper.create_query_group({}, peer_a, peer_b,
                                                        querying_peer)
        self.helper.create_query_group({}, peer_a, peer_b, querying_peer)
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
        self.helper.create_query_group({}, peer_a, peer_b)
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
        self.helper.create_query_group({}, peer_a, peer_b, peer_c, peer_d)
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None, query_all=True)
        peer_a.send_query.assert_called_once_with(
            queried_id, pending_query(querying_peer_id, queried_id,
                                      [peer_c.peer_id, peer_d.peer_id,
                                       peer_b.peer_id]), ANY)

    def test_query_all_puts_high_rep_peers_to_the_back(self):
        self.helper.settings['query_peer_selection'] = 'overlap_low_rep_first'
        peer_a, behavior =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        peer_c, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1110')
        peer_d, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1100')
        query_group_id = self.helper.create_query_group({}, peer_a, peer_b,
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

    @unittest.mock.patch('random.shuffle')
    def test_query_all_shuffles(self, mocked_shuffle):
        self.helper.settings['query_peer_selection'] = 'overlap_shuffled'
        peer_a, behavior =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        self.helper.create_query_group({}, peer_a, peer_b)
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None, query_all=True)
        mocked_shuffle.assert_called_once()

    def test_query_all_doesnt_include_peers_multiple_times(self):
        peer_a, behavior =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ =\
            self.peer_factory.mock_peer_and_behavior_with_prefix('1000')
        self.helper.create_query_group({}, peer_a, peer_b)
        self.helper.create_query_group({}, peer_a, peer_b)
        querying_peer_id = self.peer_factory.id_with_prefix('0000')
        queried_id = self.peer_factory.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query(querying_peer_id, queried_id, None, query_all=True)
        peer_a.send_query.assert_called_once_with(
            queried_id, pending_query(querying_peer_id, queried_id,
                                      [peer_b.peer_id]), ANY)
