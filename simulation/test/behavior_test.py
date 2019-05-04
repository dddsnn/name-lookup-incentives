import unittest
from unittest.mock import ANY, call
from test_utils import TestHelper, arg_with
import bitstring as bs
import peer as p


class TestOnQuerySelf(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_responds(self):
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('')
        querying_peer_id = self.helper.id_with_prefix('')
        peer.send_query.return_value = None
        behavior.on_query_self(querying_peer_id, peer.peer_id, None)
        peer.send_response.assert_called_once_with(
            querying_peer_id, peer.peer_id, arg_with(peer_id=peer.peer_id),
            ANY, delay=ANY)

    def test_applies_delay(self):
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('')
        querying_peer, _ = self.helper.mock_peer_and_behavior_with_prefix('')
        gid = self.helper.create_query_group(peer, querying_peer)
        npr = self.helper.settings['no_penalty_reputation']
        delay = 4
        peer.query_groups[gid][querying_peer.peer_id].reputation = npr - delay
        peer.send_query.return_value = None
        behavior.on_query_self(querying_peer.peer_id, peer.peer_id, None)
        peer.send_response.assert_called_once_with(
            querying_peer.peer_id, ANY, ANY, ANY, delay=delay)

    def test_does_nothing_if_enough_reputation(self):
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('')
        querying_peer, _ = self.helper.mock_peer_and_behavior_with_prefix('')
        query_group_id = self.helper.create_query_group(peer, querying_peer)
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

    def test_responds(self):
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('0000')
        sync_peer, _ = self.helper.mock_peer_and_behavior_with_prefix('0000')
        querying_peer_id = self.helper.id_with_prefix('')
        peer.send_query.return_value = None
        behavior.on_query_sync(querying_peer_id, peer.peer_id,
                               sync_peer.info(), None)
        peer.send_response.assert_called_once_with(
            querying_peer_id, peer.peer_id,
            arg_with(peer_id=sync_peer.peer_id), ANY, delay=ANY)

    def test_applies_penalty(self):
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('0000')
        sync_peer, _ = self.helper.mock_peer_and_behavior_with_prefix('0000')
        querying_peer, _ = self.helper.mock_peer_and_behavior_with_prefix('')
        gid = self.helper.create_query_group(peer, querying_peer)
        npr = self.helper.settings['no_penalty_reputation']
        delay = 4
        peer.query_groups[gid][querying_peer.peer_id].reputation = npr - delay
        peer.send_query.return_value = None
        behavior.on_query_sync(querying_peer.peer_id, peer.peer_id,
                               sync_peer.info(), None)
        peer.send_response.assert_called_once_with(
            querying_peer.peer_id, ANY, ANY, ANY, delay=delay)

    def test_does_nothing_if_enough_reputation(self):
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('0000')
        sync_peer, _ = self.helper.mock_peer_and_behavior_with_prefix('0000')
        querying_peer, _ = self.helper.mock_peer_and_behavior_with_prefix('')
        query_group_id = self.helper.create_query_group(peer, querying_peer)
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


class TestOnQueryExternal(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_adds_in_query_and_queries(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('1000')
        peer_b, _ = self.helper.mock_peer_and_behavior_with_prefix('1111')
        self.helper.create_query_group(peer_a, peer_b)
        querying_peer_id = self.helper.id_with_prefix('0000')
        queried_id = self.helper.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query_external(querying_peer_id, queried_id, None)
        peer_a.add_in_query.assert_called_once_with(querying_peer_id,
                                                    queried_id)
        peer_a.send_query.assert_called_once_with(
            peer_b.peer_id, queried_id, set(), False, False, ANY)

    def test_passes_on_query_further(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('1000')
        peer_b, _ = self.helper.mock_peer_and_behavior_with_prefix('1111')
        self.helper.create_query_group(peer_a, peer_b)
        querying_peer_id = self.helper.id_with_prefix('0000')
        queried_id = self.helper.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query_external(querying_peer_id, queried_id, None,
                                   query_further=True)
        peer_a.send_query.assert_called_once_with(
            peer_b.peer_id, queried_id, set(), True, False, ANY)

    def test_passes_on_query_sync(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('1000')
        peer_b, _ = self.helper.mock_peer_and_behavior_with_prefix('1111')
        self.helper.create_query_group(peer_a, peer_b)
        querying_peer_id = self.helper.id_with_prefix('0000')
        queried_id = self.helper.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query_external(querying_peer_id, queried_id, None,
                                   query_sync=True)
        peer_a.send_query.assert_called_once_with(
            peer_b.peer_id, queried_id, set(), False, True, ANY)

    def test_just_finalizes_if_query_from_self_and_no_known_peers(self):
        peer_a, behavior = self.helper.mock_peer_and_behavior_with_prefix('')
        behavior.on_query_external(peer_a.peer_id,
                                   self.helper.id_with_prefix(''), None)
        peer_a.send_response.assert_not_called()
        peer_a.send_query.assert_not_called()
        peer_a.add_in_query.assert_not_called()
        peer_a.finalize_own_query.assert_called_with('impossible', ANY)

    def test_informs_querying_peers_of_impossible_query(self):
        peer_a, behavior = self.helper.mock_peer_and_behavior_with_prefix('')
        querying_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        peer_a.send_response.return_value = None
        behavior.on_query_external(querying_peer_id, queried_id, None)
        peer_a.send_response.assert_called_once_with(
            querying_peer_id, queried_id, None, ANY, delay=ANY)
        peer_a.expect_penalty.assert_called_once_with(
            querying_peer_id, self.helper.settings['failed_query_penalty'],
            behavior.decide_delay(querying_peer_id)
            + self.helper.settings['expected_penalty_timeout_buffer'], ANY)
        peer_a.add_in_query.assert_not_called()

    def test_does_nothing_if_enough_reputation(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('1000')
        peer_b, _ = self.helper.mock_peer_and_behavior_with_prefix('1111')
        querying_peer, _ =\
            self.helper.mock_peer_and_behavior_with_prefix('0000')
        query_group_id = self.helper.create_query_group(peer_a, peer_b,
                                                        querying_peer)
        enough_rep = (self.helper.settings['reputation_buffer_factor']
                      * self.helper.settings['no_penalty_reputation'])
        peer_a.query_groups[query_group_id][peer_a.peer_id].reputation\
            = enough_rep + 1
        queried_id = self.helper.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        behavior.on_query_external(querying_peer.peer_id, queried_id, None)
        peer_a.expect_penalty.assert_called_once_with(
            querying_peer.peer_id,
            self.helper.settings['timeout_query_penalty'],
            behavior.decide_delay(querying_peer.peer_id)
            + self.helper.settings['expected_penalty_timeout_buffer'], ANY)
        peer_a.send_response.assert_not_called()
        peer_a.send_query.assert_not_called()
        peer_a.add_in_query.assert_not_called()

    def test_only_adds_in_query_if_existing_out_query(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('1000')
        querying_peer_id = self.helper.id_with_prefix('0000')
        queried_id = self.helper.id_with_prefix('1111')
        peer_a.send_query.return_value = None
        peer_a.has_matching_out_queries.return_value = True
        behavior.on_query_external(querying_peer_id, queried_id, None)
        peer_a.add_in_query.assert_called_once_with(querying_peer_id,
                                                    queried_id)
        peer_a.send_response.assert_not_called()
        peer_a.send_query.assert_not_called()


class TestOnResponseSuccess(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_updates_reputation(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_peer = self.helper.peer_with_prefix('1111')
        behavior.on_response_success(responding_peer_id, queried_peer.peer_id,
                                     queried_peer.info(), None)
        peer_a.send_reputation_update.assert_called_once_with(
            responding_peer_id,
            self.helper.settings['successful_query_reward'], ANY)

    def test_responds_to_peers(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ = self.helper.mock_peer_and_behavior_with_prefix('0000')
        peer_c, _ = self.helper.mock_peer_and_behavior_with_prefix('0000')
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_peer = self.helper.peer_with_prefix('1111')
        queried_peer_info = queried_peer.info()
        matching_in_queries = {
            queried_peer.peer_id: {peer_b.peer_id: p.IncomingQuery(0),
                                   peer_c.peer_id: p.IncomingQuery(0)},
            queried_peer.peer_id[:-4]: {peer_b.peer_id: p.IncomingQuery(0)}
        }
        peer_a.matching_in_queries.return_value = matching_in_queries
        peer_a.finalize_in_queries.return_value = None
        behavior.on_response_success(responding_peer_id, queried_peer.peer_id,
                                     queried_peer_info, None)
        peer_a.matching_in_queries.assert_called_once_with(
            queried_peer.peer_id)
        self.assertEqual(len(peer_a.send_response.call_args_list), 3)
        self.assertTrue(call(peer_b.peer_id, queried_peer.peer_id,
                             queried_peer_info, ANY, delay=ANY)
                        in peer_a.send_response.call_args_list)
        self.assertTrue(call(peer_b.peer_id, queried_peer.peer_id[:-4],
                             queried_peer_info, ANY, delay=ANY)
                        in peer_a.send_response.call_args_list)
        self.assertTrue(call(peer_c.peer_id, queried_peer.peer_id,
                             queried_peer_info, ANY, delay=ANY)
                        in peer_a.send_response.call_args_list)

    def test_finalizes(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ = self.helper.mock_peer_and_behavior_with_prefix('0000')
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_peer = self.helper.peer_with_prefix('1111')
        matching_in_queries = {
            queried_peer.peer_id: {peer_b.peer_id: p.IncomingQuery(0)}
        }
        peer_a.matching_in_queries.return_value = matching_in_queries
        peer_a.finalize_in_queries.return_value = None
        behavior.on_response_success(responding_peer_id, queried_peer.peer_id,
                                     queried_peer.info(), None)
        peer_a.finalize_in_queries.assert_called_once_with(matching_in_queries,
                                                           'success', ANY)


class TestOnResponseFailure(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_updates_reputation(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        behavior.on_response_failure(responding_peer_id, queried_id, set(),
                                     False, False, None)
        peer_a.send_reputation_update.assert_called_once_with(
            responding_peer_id, self.helper.settings['failed_query_penalty'],
            ANY)

    def test_attempts_retry(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0001')
        peer_c = self.helper.peer_with_prefix('1000')
        self.helper.create_query_group(peer_a, peer_c)
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        peer_a.matching_in_queries.return_value = {
            queried_id: {peer_b.peer_id: p.IncomingQuery(0)}
        }
        behavior.on_response_failure(responding_peer_id, queried_id,
                                     set(), False, False, None)
        peer_a.send_query.assert_called_once_with(
            peer_c.peer_id, queried_id, set((peer_c.peer_id,)), False, False,
            None)

    def test_doesnt_retry_if_no_queries_could_be_answered(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1000')
        self.helper.create_query_group(peer_a, peer_b)
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        behavior.on_response_failure(responding_peer_id, queried_id,
                                     set(), False, False, None)
        peer_a.send_query.assert_not_called()

    def test_doesnt_retry_if_all_peers_have_been_tried(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0001')
        peer_c = self.helper.peer_with_prefix('1000')
        self.helper.create_query_group(peer_a, peer_c)
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        peer_a.matching_in_queries.return_value = {
            queried_id: {peer_b.peer_id: p.IncomingQuery(0)}
        }
        peer_a.finalize_in_queries.return_value = None
        behavior.on_response_failure(
            responding_peer_id, queried_id, set((peer_c.peer_id,)), False,
            False, None)
        peer_a.send_query.assert_not_called()

    def test_uses_query_further(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('1000')
        peer_b = self.helper.peer_with_prefix('0001')
        peer_c = self.helper.peer_with_prefix('0011')
        self.helper.create_query_group(peer_a, peer_c)
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        peer_a.matching_in_queries.return_value = {
            queried_id: {peer_b.peer_id: p.IncomingQuery(0)}
        }
        peer_a.finalize_in_queries.return_value = None
        behavior.on_response_failure(
            responding_peer_id, queried_id, set(), True, False, None)
        peer_a.send_query.assert_called_once_with(
            peer_c.peer_id, queried_id, set((peer_c.peer_id,)), True, False,
            None)

    def test_uses_query_sync(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('1000')
        peer_b = self.helper.peer_with_prefix('0001')
        peer_c = self.helper.peer_with_prefix('1000')
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        peer_a.matching_in_queries.return_value = {
            queried_id: {peer_b.peer_id: p.IncomingQuery(0)}
        }
        peer_a.finalize_in_queries.return_value = None
        behavior.on_response_failure(
            responding_peer_id, queried_id, set(), False, True, None)
        peer_a.send_query.assert_called_once_with(
            peer_c.peer_id, queried_id, set((peer_c.peer_id,)), False, True,
            None)

    def test_responds_to_peers_if_no_retry_possible(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ = self.helper.mock_peer_and_behavior_with_prefix('0000')
        peer_c, _ = self.helper.mock_peer_and_behavior_with_prefix('0000')
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        matching_in_queries = {
            queried_id: {peer_b.peer_id: p.IncomingQuery(0),
                         peer_c.peer_id: p.IncomingQuery(0)},
            queried_id[:-4]: {peer_b.peer_id: p.IncomingQuery(0)}
        }
        peer_a.matching_in_queries.return_value = matching_in_queries
        peer_a.finalize_in_queries.return_value = None
        behavior.on_response_failure(
            responding_peer_id, queried_id, set(), False, False, None)
        peer_a.matching_in_queries.assert_called_once_with(
            queried_id)
        self.assertEqual(len(peer_a.send_response.call_args_list), 3)
        self.assertTrue(call(peer_b.peer_id, queried_id, None, ANY, delay=ANY)
                        in peer_a.send_response.call_args_list)
        self.assertTrue(call(peer_b.peer_id, queried_id[:-4], None, ANY,
                             delay=ANY)
                        in peer_a.send_response.call_args_list)
        self.assertTrue(call(peer_c.peer_id, queried_id, None, ANY, delay=ANY)
                        in peer_a.send_response.call_args_list)

    def test_finalizes(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ = self.helper.mock_peer_and_behavior_with_prefix('0000')
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        matching_in_queries = {
            queried_id: {peer_b.peer_id: p.IncomingQuery(0)}
        }
        peer_a.matching_in_queries.return_value = matching_in_queries
        peer_a.finalize_in_queries.return_value = None
        behavior.on_response_failure(responding_peer_id, queried_id, set(),
                                     False, False, None)
        peer_a.finalize_in_queries.assert_called_once_with(matching_in_queries,
                                                           'failure', ANY)


class TestOnTimeout(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_updates_reputation(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        behavior.on_timeout(responding_peer_id, queried_id, set(), False,
                            False, None)
        peer_a.send_reputation_update.assert_called_once_with(
            responding_peer_id, self.helper.settings['failed_query_penalty'],
            ANY)

    def test_attempts_retry(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0001')
        peer_c = self.helper.peer_with_prefix('1000')
        self.helper.create_query_group(peer_a, peer_c)
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        peer_a.matching_in_queries.return_value = {
            queried_id: {peer_b.peer_id: p.IncomingQuery(0)}
        }
        behavior.on_timeout(responding_peer_id, queried_id, set(), False,
                            False, None)
        peer_a.send_query.assert_called_once_with(
            peer_c.peer_id, queried_id, set((peer_c.peer_id,)), False, False,
            None)

    def test_doesnt_retry_if_no_queries_could_be_answered(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1000')
        self.helper.create_query_group(peer_a, peer_b)
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        behavior.on_timeout(responding_peer_id, queried_id, set(), False,
                            False, None)
        peer_a.send_query.assert_not_called()

    def test_doesnt_retry_if_all_peers_have_been_tried(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0001')
        peer_c = self.helper.peer_with_prefix('1000')
        self.helper.create_query_group(peer_a, peer_c)
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        peer_a.matching_in_queries.return_value = {
            queried_id: {peer_b.peer_id: p.IncomingQuery(0)}
        }
        peer_a.finalize_in_queries.return_value = None
        behavior.on_timeout(
            responding_peer_id, queried_id, set((peer_c.peer_id,)), False,
            False, None)
        peer_a.send_query.assert_not_called()

    def test_uses_query_further(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('1000')
        peer_b = self.helper.peer_with_prefix('0001')
        peer_c = self.helper.peer_with_prefix('0011')
        self.helper.create_query_group(peer_a, peer_c)
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        peer_a.matching_in_queries.return_value = {
            queried_id: {peer_b.peer_id: p.IncomingQuery(0)}
        }
        peer_a.finalize_in_queries.return_value = None
        behavior.on_timeout(
            responding_peer_id, queried_id, set(), True, False, None)
        peer_a.send_query.assert_called_once_with(
            peer_c.peer_id, queried_id, set((peer_c.peer_id,)), True, False,
            None)

    def test_uses_query_sync(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('1000')
        peer_b = self.helper.peer_with_prefix('0001')
        peer_c = self.helper.peer_with_prefix('1000')
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        peer_a.matching_in_queries.return_value = {
            queried_id: {peer_b.peer_id: p.IncomingQuery(0)}
        }
        peer_a.finalize_in_queries.return_value = None
        behavior.on_timeout(
            responding_peer_id, queried_id, set(), False, True, None)
        peer_a.send_query.assert_called_once_with(
            peer_c.peer_id, queried_id, set((peer_c.peer_id,)), False, True,
            None)

    def test_responds_to_peers_if_no_retry_possible(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ = self.helper.mock_peer_and_behavior_with_prefix('0000')
        peer_c, _ = self.helper.mock_peer_and_behavior_with_prefix('0000')
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        matching_in_queries = {
            queried_id: {peer_b.peer_id: p.IncomingQuery(0),
                         peer_c.peer_id: p.IncomingQuery(0)},
            queried_id[:-4]: {peer_b.peer_id: p.IncomingQuery(0)}
        }
        peer_a.matching_in_queries.return_value = matching_in_queries
        peer_a.finalize_in_queries.return_value = None
        behavior.on_timeout(
            responding_peer_id, queried_id, set(), False, False, None)
        peer_a.matching_in_queries.assert_called_once_with(
            queried_id)
        self.assertEqual(len(peer_a.send_response.call_args_list), 3)
        self.assertTrue(call(peer_b.peer_id, queried_id, None, ANY, delay=ANY)
                        in peer_a.send_response.call_args_list)
        self.assertTrue(call(peer_b.peer_id, queried_id[:-4], None, ANY,
                             delay=ANY)
                        in peer_a.send_response.call_args_list)
        self.assertTrue(call(peer_c.peer_id, queried_id, None, ANY, delay=ANY)
                        in peer_a.send_response.call_args_list)

    def test_finalizes(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        peer_b, _ = self.helper.mock_peer_and_behavior_with_prefix('0000')
        responding_peer_id = self.helper.id_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('1111')
        matching_in_queries = {
            queried_id: {peer_b.peer_id: p.IncomingQuery(0)}
        }
        peer_a.matching_in_queries.return_value = matching_in_queries
        peer_a.finalize_in_queries.return_value = None
        behavior.on_timeout(responding_peer_id, queried_id, set(), False,
                            False, None)
        peer_a.finalize_in_queries.assert_called_once_with(matching_in_queries,
                                                           'timeout', ANY)


class TestRespondToInQueries(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_responds(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        querying_peer_id_a = self.helper.id_with_prefix('')
        querying_peer_id_b = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('1111')
        in_queries_map = {
            queried_id: {querying_peer_id_a: p.IncomingQuery(0),
                         querying_peer_id_b: p.IncomingQuery(0)}
        }
        queried_peer_info = 'info'
        behavior.respond_to_in_queries(in_queries_map, queried_peer_info, None)
        self.assertEqual(len(peer_a.send_response.call_args_list), 2)
        self.assertTrue(call(querying_peer_id_a, queried_id, queried_peer_info,
                             ANY, delay=ANY)
                        in peer_a.send_response.call_args_list)
        self.assertTrue(call(querying_peer_id_b, queried_id, queried_peer_info,
                             ANY, delay=ANY)
                        in peer_a.send_response.call_args_list)

    def test_responds_multiple_times_to_same_peer_for_prefixes(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        querying_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('1111')
        in_queries_map = {
            queried_id: {querying_peer_id: p.IncomingQuery(0)},
            queried_id[:-4]: {querying_peer_id: p.IncomingQuery(0)}
        }
        queried_peer_info = 'info'
        behavior.respond_to_in_queries(in_queries_map, queried_peer_info, None)
        self.assertEqual(len(peer_a.send_response.call_args_list), 2)
        self.assertTrue(call(querying_peer_id, queried_id, queried_peer_info,
                             ANY, delay=ANY)
                        in peer_a.send_response.call_args_list)
        self.assertTrue(call(querying_peer_id, queried_id[:-4],
                             queried_peer_info, ANY, delay=ANY)
                        in peer_a.send_response.call_args_list)

    def test_computes_delay(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        sync_peer_id = self.helper.id_with_prefix('0000')
        query_peer = self.helper.peer_with_prefix('1010')
        query_group_id = self.helper.create_query_group(peer_a, query_peer)
        queried_id = self.helper.id_with_prefix('1111')
        in_queries_map = {
            queried_id: {sync_peer_id: p.IncomingQuery(0),
                         query_peer.peer_id: p.IncomingQuery(0)}
        }
        queried_peer_info = 'info'
        peer_a.query_groups[query_group_id][query_peer.peer_id].reputation = 4
        behavior.respond_to_in_queries(in_queries_map, queried_peer_info, None)
        sync_peer_delay = self.helper.settings['no_penalty_reputation']
        query_peer_delay = self.helper.settings['no_penalty_reputation'] - 4
        self.assertEqual(len(peer_a.send_response.call_args_list), 2)
        self.assertTrue(call(sync_peer_id, queried_id, queried_peer_info,
                             ANY, delay=sync_peer_delay)
                        in peer_a.send_response.call_args_list)
        self.assertTrue(call(query_peer.peer_id, queried_id, queried_peer_info,
                             ANY, delay=query_peer_delay)
                        in peer_a.send_response.call_args_list)

    def test_expects_penalty(self):
        peer_a, behavior\
            = self.helper.mock_peer_and_behavior_with_prefix('0000')
        query_peer = self.helper.peer_with_prefix('1010')
        query_group_id = self.helper.create_query_group(peer_a, query_peer)
        queried_id = self.helper.id_with_prefix('1111')
        in_queries_map = {
            queried_id: {query_peer.peer_id: p.IncomingQuery(0)}
        }
        queried_peer_info = 'info'
        peer_a.query_groups[query_group_id][query_peer.peer_id].reputation = 4
        expected_penalty = 2
        behavior.respond_to_in_queries(in_queries_map, queried_peer_info, None,
                                       expected_penalty=expected_penalty)
        timeout = (self.helper.settings['no_penalty_reputation'] - 4
                   + self.helper.settings['expected_penalty_timeout_buffer'])
        peer_a.expect_penalty.assert_called_once_with(
            query_peer.peer_id, expected_penalty, timeout, ANY)


class TestSelectPeerToQuery(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_doesnt_select_self(self):
        peer_a = self.helper.peer_with_prefix('0000')
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('0001'), set(), False, False)
        self.assertEqual(selected, None)

    def test_selects_peer(self):
        self.helper.settings['query_peer_selection'] = 'overlap'
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1100')
        self.helper.create_query_group(peer_a, peer_b)
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('1111'), set(), False, False)
        self.assertEqual(selected, peer_b.peer_id)

    def test_doesnt_select_peers_with_smaller_or_equal_overlap(self):
        self.helper.settings['query_peer_selection'] = 'overlap'
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0000')
        peer_c = self.helper.peer_with_prefix('0011')
        peer_d = self.helper.peer_with_prefix('1000')
        self.helper.create_query_group(peer_a, peer_b, peer_c, peer_d)
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('0001'), set(), False, False)
        self.assertEqual(selected, None)

    def test_sorts_by_overlap_length(self):
        self.helper.settings['query_peer_selection'] = 'overlap'
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1000')
        peer_c = self.helper.peer_with_prefix('1111')
        peer_d = self.helper.peer_with_prefix('1100')
        self.helper.create_query_group(peer_a, peer_b, peer_c, peer_d)
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('1111'), set(), False, False)
        self.assertEqual(selected, peer_c.peer_id)

    def test_doesnt_select_high_rep_peers(self):
        self.helper.settings['query_peer_selection'] = 'overlap_high_rep_last'
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1111')
        peer_c = self.helper.peer_with_prefix('1000')
        query_group_id = self.helper.create_query_group(peer_a, peer_b, peer_c)
        enough_rep = (self.helper.settings['reputation_buffer_factor']
                      * self.helper.settings['no_penalty_reputation'])
        peer_a.query_groups[query_group_id][peer_b.peer_id].reputation\
            = enough_rep + 1
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('1111'), set(), False, False)
        self.assertEqual(selected, peer_c.peer_id)

    def test_overlap_high_rep_last_considers_minimum_rep(self):
        self.helper.settings['query_peer_selection'] = 'overlap_high_rep_last'
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1111')
        peer_c = self.helper.peer_with_prefix('1000')
        query_group_id_1 = self.helper.create_query_group(peer_a, peer_b,
                                                          peer_c)
        self.helper.create_query_group(peer_a, peer_b, peer_c)
        enough_rep = (self.helper.settings['reputation_buffer_factor']
                      * self.helper.settings['no_penalty_reputation'])
        peer_a.query_groups[query_group_id_1][peer_b.peer_id].reputation\
            = enough_rep + 1
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('1111'), set(), False, False)
        self.assertEqual(selected, peer_b.peer_id)

    @unittest.mock.patch('random.shuffle')
    def test_shuffles(self, mocked_shuffle):
        self.helper.settings['query_peer_selection'] = 'shuffled'
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1000')
        self.helper.create_query_group(peer_a, peer_b)
        peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('1111'), set(), False, False)
        mocked_shuffle.assert_called_once()

    def test_sorts_by_overlap_and_reputation(self):
        self.helper.settings['query_peer_selection'] = 'overlap_rep_sorted'
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1111')
        peer_c = self.helper.peer_with_prefix('1111')
        peer_d = self.helper.peer_with_prefix('1111')
        peer_e = self.helper.peer_with_prefix('1000')
        query_group_id = self.helper.create_query_group(
            peer_a, peer_b, peer_c, peer_d, peer_e)
        peer_a.query_groups[query_group_id][peer_b.peer_id].reputation = 6
        peer_a.query_groups[query_group_id][peer_c.peer_id].reputation = 5
        peer_a.query_groups[query_group_id][peer_d.peer_id].reputation = 6
        peer_a.query_groups[query_group_id][peer_e.peer_id].reputation = 3
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('1111'), set(), False, False)
        self.assertEqual(selected, peer_c.peer_id)

    def test_overlap_rep_sorted_considers_minimum_rep(self):
        self.helper.settings['query_peer_selection'] = 'overlap_rep_sorted'
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1111')
        peer_c = self.helper.peer_with_prefix('1111')
        peer_d = self.helper.peer_with_prefix('1111')
        query_group_id_1 = self.helper.create_query_group(
            peer_a, peer_b, peer_c, peer_d)
        query_group_id_2 = self.helper.create_query_group(
            peer_a, peer_b, peer_c, peer_d)
        peer_a.query_groups[query_group_id_1][peer_b.peer_id].reputation = 2
        peer_a.query_groups[query_group_id_1][peer_c.peer_id].reputation = 4
        peer_a.query_groups[query_group_id_1][peer_d.peer_id].reputation = 6
        peer_a.query_groups[query_group_id_2][peer_b.peer_id].reputation = 7
        peer_a.query_groups[query_group_id_2][peer_c.peer_id].reputation = 1
        peer_a.query_groups[query_group_id_2][peer_d.peer_id].reputation = 3
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('1111'), set(), False, False)
        self.assertEqual(selected, peer_c.peer_id)

    def test_sorts_by_reputation(self):
        self.helper.settings['query_peer_selection'] = 'rep_sorted'
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1111')
        peer_c = self.helper.peer_with_prefix('1111')
        peer_d = self.helper.peer_with_prefix('1000')
        peer_e = self.helper.peer_with_prefix('1000')
        query_group_id = self.helper.create_query_group(
            peer_a, peer_b, peer_c, peer_d, peer_e)
        peer_a.query_groups[query_group_id][peer_b.peer_id].reputation = 6
        peer_a.query_groups[query_group_id][peer_c.peer_id].reputation = 5
        peer_a.query_groups[query_group_id][peer_d.peer_id].reputation = 2
        peer_a.query_groups[query_group_id][peer_e.peer_id].reputation = 3
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('1111'), set(), False, False)
        self.assertEqual(selected, peer_d.peer_id)

    def test_rep_sorted_considers_minimum_rep(self):
        self.helper.settings['query_peer_selection'] = 'rep_sorted'
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1111')
        peer_c = self.helper.peer_with_prefix('1111')
        peer_d = self.helper.peer_with_prefix('1000')
        query_group_id_1 = self.helper.create_query_group(
            peer_a, peer_b, peer_c, peer_d)
        query_group_id_2 = self.helper.create_query_group(
            peer_a, peer_b, peer_c, peer_d)
        peer_a.query_groups[query_group_id_1][peer_b.peer_id].reputation = 2
        peer_a.query_groups[query_group_id_1][peer_c.peer_id].reputation = 4
        peer_a.query_groups[query_group_id_1][peer_d.peer_id].reputation = 6
        peer_a.query_groups[query_group_id_2][peer_b.peer_id].reputation = 7
        peer_a.query_groups[query_group_id_2][peer_c.peer_id].reputation = 1
        peer_a.query_groups[query_group_id_2][peer_d.peer_id].reputation = 3
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('1111'), set(), False, False)
        self.assertEqual(selected, peer_c.peer_id)

    def test_selects_peers_with_smaller_or_equal_overlap(self):
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1000')
        self.helper.create_query_group(peer_a, peer_b)
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('0001'), set(), True, False)
        self.assertEqual(selected, peer_b.peer_id)

    def test_selects_sync_peers(self):
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0000')
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('0001'), set(), False, True)
        self.assertEqual(selected, peer_b.peer_id)

    def test_also_considers_query_peers_with_sync_peers(self):
        self.helper.settings['query_peer_selection'] = 'overlap'
        peer_a = self.helper.peer_with_prefix('0000')
        self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0001')
        self.helper.create_query_group(peer_a, peer_b)
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('0001'), set(), False, True)
        self.assertEqual(selected, peer_b.peer_id)

    def test_overlap_prefers_query_peers_to_sync_peers(self):
        self.helper.settings['query_peer_selection'] = 'overlap'
        peer_a = self.helper.peer_with_prefix('0000')
        self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1000')
        self.helper.peer_with_prefix('0000')
        self.helper.create_query_group(peer_a, peer_b)
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('1111'), set(), False, True)
        self.assertEqual(selected, peer_b.peer_id)

    def test_overlap_rep_sorted_prefers_query_peers_to_sync_peers(self):
        self.helper.settings['query_peer_selection'] = 'overlap_rep_sorted'
        peer_a = self.helper.peer_with_prefix('0000')
        self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1000')
        self.helper.peer_with_prefix('0000')
        self.helper.create_query_group(peer_a, peer_b)
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('1111'), set(), False, True)
        self.assertEqual(selected, peer_b.peer_id)

    def test_overlap_high_rep_last_prefers_query_peers_to_sync_peers(self):
        self.helper.settings['query_peer_selection'] = 'overlap_high_rep_last'
        peer_a = self.helper.peer_with_prefix('0000')
        self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1000')
        self.helper.peer_with_prefix('0000')
        self.helper.create_query_group(peer_a, peer_b)
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('1111'), set(), False, True)
        self.assertEqual(selected, peer_b.peer_id)

    def test_rep_sorted_prefers_query_peers_to_sync_peers(self):
        self.helper.settings['query_peer_selection'] = 'rep_sorted'
        peer_a = self.helper.peer_with_prefix('0000')
        self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1000')
        query_group_id = self.helper.create_query_group(peer_a, peer_b)
        peer_a.query_groups[query_group_id][peer_b.peer_id].reputation = 2
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('1111'), set(), False, True)
        self.assertEqual(selected, peer_b.peer_id)

    def test_prefers_query_peers_with_lower_overlap_to_sync_peers(self):
        peer_a = self.helper.peer_with_prefix('0000')
        self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1000')
        self.helper.create_query_group(peer_a, peer_b)
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('0001'), set(), True, True)
        self.assertEqual(selected, peer_b.peer_id)

    def test_doesnt_select_peers_already_queried(self):
        self.helper.settings['query_peer_selection'] = 'overlap'
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1000')
        peer_c = self.helper.peer_with_prefix('1110')
        peer_d = self.helper.peer_with_prefix('1111')
        self.helper.create_query_group(peer_a, peer_b, peer_c, peer_d)
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('1111'),
            set((peer_c.peer_id, peer_d.peer_id)), False, False)
        self.assertEqual(selected, peer_b.peer_id)

    def test_doesnt_select_further_peers_already_queried(self):
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1000')
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('0001'), set((peer_b.peer_id,)), True,
            False)
        self.assertEqual(selected, None)

    def test_doesnt_select_sync_peers_already_queried(self):
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0000')
        selected = peer_a.behavior.select_peer_to_query(
            self.helper.id_with_prefix('1111'), set((peer_b.peer_id,)), False,
            True)
        self.assertEqual(selected, None)


class TestQueryGroupPerforms(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_performs_if_history_doesnt_exist(self):
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('')
        query_group_id = self.helper.create_query_group(peer)
        self.assertTrue(behavior.query_group_performs(query_group_id))

    def test_performs_if_history_too_short(self):
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('')
        query_group_id = self.helper.create_query_group(peer)
        for _ in range(self.helper.settings['query_group_min_history'] - 1):
            peer.update_query_group_history()
        self.assertTrue(behavior.query_group_performs(query_group_id))

    def test_performs_if_enough_reputation(self):
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('')
        query_group_id = self.helper.create_query_group(peer)
        min_rep = (self.helper.settings['no_penalty_reputation']
                   * self.helper.settings['performance_no_penalty_fraction'])
        peer.query_groups[query_group_id][peer.peer_id].reputation = min_rep
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        self.assertTrue(behavior.query_group_performs(query_group_id))

    def test_performs_if_rep_rises_fast_enough(self):
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('')
        query_group_id = self.helper.create_query_group(peer)
        slope = self.helper.settings['performance_min_slope']
        for i in range(self.helper.settings['query_group_min_history']):
            peer.query_groups[query_group_id][peer.peer_id].reputation\
                = i * (slope + 0.01)
            peer.update_query_group_history()
        self.assertTrue(behavior.query_group_performs(query_group_id))

    def test_doesnt_perform_if_rep_rises_too_slowly(self):
        self.helper.settings['performance_no_penalty_fraction'] = 0.8
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('')
        query_group_id = self.helper.create_query_group(peer)
        slope = self.helper.settings['performance_min_slope'] - 0.01
        for i in range(self.helper.settings['query_group_min_history']):
            peer.query_groups[query_group_id][peer.peer_id].reputation\
                = i * slope
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id))

    def test_accounts_for_history_interval(self):
        self.helper.settings['performance_no_penalty_fraction'] = 0.8
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('')
        interval = 10
        self.helper.settings['query_group_history_interval'] = interval
        query_group_id = self.helper.create_query_group(peer)
        slope = self.helper.settings['performance_min_slope']
        for i in range(self.helper.settings['query_group_min_history']):
            peer.query_groups[query_group_id][peer.peer_id].reputation\
                = i * slope
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id))


class TestReevaluateQueryGroups(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_doesnt_do_anything_if_group_performs(self):
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0000')
        query_group_id = self.helper.create_query_group(peer, peer_a)
        self.helper.create_query_group(peer_b)
        self.assertTrue(behavior.query_group_performs(query_group_id))
        behavior.reevaluate_query_groups(None)
        peer.find_query_peers_for.assert_not_called()
        peer.leave_query_group.assert_not_called()

    def test_removes_non_performing_group_if_covered_by_other_group(self):
        self.helper.settings['performance_no_penalty_fraction'] = 0.8
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0000')
        peer_c = self.helper.peer_with_prefix('0000')
        query_group_id_1 = self.helper.create_query_group(peer, peer_a)
        query_group_id_2 = self.helper.create_query_group(peer, peer_b, peer_c)
        peer.query_groups[query_group_id_2][peer.peer_id].reputation = 10
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id_1))
        self.assertTrue(behavior.query_group_performs(query_group_id_2))
        behavior.reevaluate_query_groups(None)
        peer.find_query_peers_for.assert_not_called()
        peer.leave_query_group.assert_called_once_with(query_group_id_1, ANY)

    def test_removes_non_performing_group_if_joined_replacement(self):
        self.helper.settings['performance_no_penalty_fraction'] = 0.8
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0000')
        peer_c = self.helper.peer_with_prefix('0000')
        query_group_id = self.helper.create_query_group(peer, peer_a)
        self.helper.create_query_group(peer_b, peer_c)
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id))
        behavior.reevaluate_query_groups(None)
        peer.find_query_peers_for.assert_called_once_with(bs.Bits('0b0'), ANY,
                                                          ANY, ANY, ANY)
        peer.leave_query_group.assert_called_once_with(query_group_id, ANY)

    def test_includes_already_covering_peers(self):
        self.helper.settings['performance_no_penalty_fraction'] = 0.8
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0000')
        query_group_id_1 = self.helper.create_query_group(peer, peer_a)
        query_group_id_2 = self.helper.create_query_group(peer, peer_b)
        peer.query_groups[query_group_id_2][peer.peer_id].reputation = 10
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id_1))
        self.assertTrue(behavior.query_group_performs(query_group_id_2))
        behavior.reevaluate_query_groups(None)
        peer.find_query_peers_for.assert_called_once_with(
            bs.Bits('0b0'), set((peer_b.peer_id,)), ANY, ANY, ANY)

    def test_specifies_number_of_missing_peers(self):
        self.helper.settings['performance_no_penalty_fraction'] = 0.8
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0000')
        query_group_id_1 = self.helper.create_query_group(peer, peer_a)
        query_group_id_2 = self.helper.create_query_group(peer, peer_b)
        peer.query_groups[query_group_id_2][peer.peer_id].reputation = 10
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id_1))
        self.assertTrue(behavior.query_group_performs(query_group_id_2))
        behavior.reevaluate_query_groups(None)
        peer.find_query_peers_for.assert_called_once_with(
            bs.Bits('0b0'), ANY, 1, ANY, ANY)

    def test_doesnt_remove_non_performing_group_if_no_replacement(self):
        self.helper.settings['performance_no_penalty_fraction'] = 0.8
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.helper.peer_with_prefix('0000')
        query_group_id = self.helper.create_query_group(peer, peer_a)
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id))
        behavior.reevaluate_query_groups(None)
        peer.leave_query_group.assert_not_called()

    def test_checks_all_subprefixes(self):
        self.helper.settings['performance_no_penalty_fraction'] = 0.8
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1110')
        peer_c = self.helper.peer_with_prefix('0000')
        peer_d = self.helper.peer_with_prefix('0000')
        query_group_id_1 = self.helper.create_query_group(peer, peer_a, peer_b)
        query_group_id_2 = self.helper.create_query_group(peer_c, peer_d)
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        self.assertFalse(behavior.query_group_performs(query_group_id_1))
        behavior.reevaluate_query_groups(None)
        self.assertTrue(query_group_id_2 in peer.query_groups)
        peer.leave_query_group.assert_not_called()

    def test_removes_multiple_groups(self):
        self.helper.settings['performance_no_penalty_fraction'] = 0.8
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0000')
        peer_c = self.helper.peer_with_prefix('0000')
        peer_d = self.helper.peer_with_prefix('0000')
        query_group_id_1 = self.helper.create_query_group(peer, peer_a)
        query_group_id_2 = self.helper.create_query_group(peer, peer_b)
        self.helper.create_query_group(peer_c, peer_d)
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
        self.helper.settings['performance_no_penalty_fraction'] = 0.8
        peer, behavior = self.helper.mock_peer_and_behavior_with_prefix('1111')
        peer_a = self.helper.peer_with_prefix('0000')
        query_group_id = self.helper.create_query_group(peer, peer_a)
        for _ in range(self.helper.settings['query_group_min_history']):
            peer.update_query_group_history()
        peer.estimated_usefulness_in.return_value = 5
        self.assertFalse(behavior.query_group_performs(query_group_id))
        behavior.reevaluate_query_groups(None)
        peer.find_query_peers_for.assert_called_once_with(
            bs.Bits('0b0'), ANY, ANY, 5, ANY)
