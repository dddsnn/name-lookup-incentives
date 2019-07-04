import unittest
from unittest.mock import ANY, call
from test_utils import TestHelper, set_containing, arg_any_of
import bitstring as bs
import peer as p
import util
from util import SortedBitsTrie as SBT
import simpy
import copy


class TestSendQuery(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def outgoing_query_eq(self, other):
        return (self.time == other.time
                and self.peers_already_queried == other.peers_already_queried
                and self.query_further == other.query_further
                and self.query_sync == other.query_sync
                and self.excluded_peer_ids == other.excluded_peer_ids)

    p.OutgoingQuery.__eq__ = outgoing_query_eq
    p.OutgoingQuery.__repr__ = util.generic_repr

    @unittest.mock.patch('util.Network.send_query')
    def test_sends_query(self, mocked_send):
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer_a, peer_b)
        queried_id = self.helper.id_with_prefix('')
        peer_a.send_query(peer_b.peer_id, queried_id, set(), False, False,
                          SBT(), None)
        mocked_send.assert_called_once_with(
            peer_a.peer_id, peer_a.address, peer_b.address, queried_id, SBT(),
            ANY)

    @unittest.mock.patch('util.Network.send_query')
    def test_passes_on_excluded_peer_ids(self, mocked_send):
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer_a, peer_b)
        queried_id = self.helper.id_with_prefix('')
        excluded_id = self.helper.id_with_prefix('')
        peer_a.send_query(peer_b.peer_id, queried_id, set(), False, False,
                          SBT({excluded_id: None}), None)
        mocked_send.assert_called_once_with(
            peer_a.peer_id, peer_a.address, peer_b.address, queried_id,
            SBT({excluded_id: ANY}),  ANY)

    def test_adds_out_query(self):
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer_a, peer_b)
        queried_id = self.helper.id_with_prefix('')
        peer_a.send_query(peer_b.peer_id, queried_id, set(), False, False,
                          SBT(), None)
        self.assertEqual(peer_a.out_queries_map[queried_id],
                         {peer_b.peer_id: p.OutgoingQuery(
                             0, set((peer_b.peer_id,)), False, False, SBT())})

    def test_saves_peers_already_queried(self):
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        peers_already_queried = set((self.helper.id_with_prefix('')))
        self.helper.create_query_group(peer_a, peer_b)
        queried_id = self.helper.id_with_prefix('')
        peer_a.send_query(peer_b.peer_id, queried_id, peers_already_queried,
                          False, False, SBT(), None)
        peers_already_queried.add(peer_b.peer_id)
        self.assertEqual(peer_a.out_queries_map[queried_id],
                         {peer_b.peer_id: p.OutgoingQuery(
                             0, peers_already_queried, False, False, SBT())})

    def test_saves_query_further(self):
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer_a, peer_b)
        queried_id = self.helper.id_with_prefix('')
        peer_a.send_query(peer_b.peer_id, queried_id, set(), True, False,
                          SBT(), None)
        self.assertEqual(peer_a.out_queries_map[queried_id],
                         {peer_b.peer_id: p.OutgoingQuery(
                             0, set((peer_b.peer_id,)), True, False, SBT())})

    def test_saves_query_sync(self):
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer_a, peer_b)
        queried_id = self.helper.id_with_prefix('')
        peer_a.send_query(peer_b.peer_id, queried_id, set(), False, True,
                          SBT(), None)
        self.assertEqual(peer_a.out_queries_map[queried_id],
                         {peer_b.peer_id: p.OutgoingQuery(
                             0, set((peer_b.peer_id,)), False, True, SBT())})

    def test_saves_excluded_peer_ids(self):
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer_a, peer_b)
        queried_id = self.helper.id_with_prefix('')
        excluded_id = self.helper.id_with_prefix('')
        peer_a.send_query(peer_b.peer_id, queried_id, set(), False, False,
                          SBT({excluded_id: None}), None)
        self.assertEqual(peer_a.out_queries_map[queried_id],
                         {peer_b.peer_id: p.OutgoingQuery(
                             0, set((peer_b.peer_id,)), False, False,
                             SBT({excluded_id: ANY}))})

    def test_starts_timeout(self):
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer_a, peer_b)
        queried_id = self.helper.id_with_prefix('')
        with unittest.mock.patch.object(peer_a.env, 'process') as process,\
                unittest.mock.patch.object(peer_a, 'query_timeout') as timeout:
            peer_a.send_query(peer_b.peer_id, queried_id, set(), False, True,
                              SBT(), None)
            process.assert_called_once()
            timeout.assert_called_once_with(peer_b.peer_id, queried_id, ANY)


class TestSendResponse(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    @unittest.mock.patch('util.do_delayed')
    def test_sends_response(self, mocked_do_delayed):
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer_a, peer_b)
        queried_id = self.helper.id_with_prefix('')
        peer_a.send_response(peer_b.peer_id, queried_id, 'info', None)
        mocked_do_delayed.assert_called_once_with(
            ANY, ANY, peer_a.network.send_response, peer_a.peer_id,
            peer_a.address, peer_b.address, queried_id, 'info', ANY)

    @unittest.mock.patch('util.do_delayed')
    def test_uses_delay(self, mocked_do_delayed):
        peer_a = self.helper.peer_with_prefix('')
        peer_b = self.helper.peer_with_prefix('')
        self.helper.create_query_group(peer_a, peer_b)
        queried_id = self.helper.id_with_prefix('')
        peer_a.send_response(peer_b.peer_id, queried_id, 'info', None, delay=7)
        mocked_do_delayed.assert_called_once_with(
            ANY, 7, peer_a.network.send_response, ANY, ANY, ANY, ANY, ANY, ANY)

    @unittest.mock.patch('util.do_delayed')
    def test_doesnt_send_to_unknown_peers(self, mocked_do_delayed):
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('1111')
        queried_id = self.helper.id_with_prefix('')
        peer_a.send_response(peer_b.peer_id, queried_id, 'info', None)
        mocked_do_delayed.assert_not_called()


class TestRecvQuery(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def peer_info_eq(self, other):
        return (self.peer_id == other.peer_id and self.prefix == other.prefix
                and self.address == other.address)

    p.PeerInfo.__eq__ = peer_info_eq
    p.PeerInfo.__repr__ = util.generic_repr

    def test_reacts_to_query_for_self(self):
        peer_a = self.helper.peer_with_prefix('')
        querying_peer_id = self.helper.id_with_prefix('')
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_query(querying_peer_id, peer_a.peer_id, None)
            mocked_behavior.on_query_self.assert_called_once_with(
                querying_peer_id, peer_a.peer_id, ANY)
            mocked_behavior.on_query_sync.assert_not_called()
            mocked_behavior.on_query_external.assert_not_called()
            mocked_behavior.on_query_no_such_peer.assert_not_called()

    def test_reacts_to_query_for_prefix_of_self(self):
        peer_a = self.helper.peer_with_prefix('')
        querying_peer_id = self.helper.id_with_prefix('')
        queried_id = peer_a.peer_id[:-4]
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_query(querying_peer_id, queried_id, None)
            mocked_behavior.on_query_self.assert_called_once_with(
                querying_peer_id, queried_id, ANY)
            mocked_behavior.on_query_sync.assert_not_called()
            mocked_behavior.on_query_external.assert_not_called()
            mocked_behavior.on_query_no_such_peer.assert_not_called()

    def test_reacts_to_query_for_sync_peer(self):
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0000')
        querying_peer_id = self.helper.id_with_prefix('')
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_query(querying_peer_id, peer_b.peer_id, None)
            mocked_behavior.on_query_sync.assert_called_once_with(
                querying_peer_id, peer_b.peer_id, peer_b.info(), ANY)
            mocked_behavior.on_query_self.assert_not_called()
            mocked_behavior.on_query_external.assert_not_called()
            mocked_behavior.on_query_no_such_peer.assert_not_called()

    def test_reacts_to_query_for_prefix_of_sync_peer(self):
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0000')
        querying_peer_id = self.helper.id_with_prefix('')
        queried_id = peer_b.peer_id[:-4]
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_query(querying_peer_id, queried_id, None)
            mocked_behavior.on_query_sync.assert_called_once_with(
                querying_peer_id, queried_id, peer_b.info(), ANY)
            mocked_behavior.on_query_self.assert_not_called()
            mocked_behavior.on_query_external.assert_not_called()
            mocked_behavior.on_query_no_such_peer.assert_not_called()

    def test_reacts_to_query_for_external_peer(self):
        peer_a = self.helper.peer_with_prefix('0000')
        querying_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('1111')
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_query(querying_peer_id, queried_id, None)
            mocked_behavior.on_query_external.assert_called_once_with(
                querying_peer_id, queried_id, ANY, excluded_peer_ids=SBT())
            mocked_behavior.on_query_self.assert_not_called()
            mocked_behavior.on_query_sync.assert_not_called()
            mocked_behavior.on_query_no_such_peer.assert_not_called()

    def test_doesnt_react_to_repeated_query_from_self(self):
        peer_a = self.helper.peer_with_prefix('0000')
        queried_id = self.helper.id_with_prefix('1111')
        peer_a.in_queries_map.setdefault(queried_id, {}).setdefault(
            peer_a.peer_id, p.IncomingQuery(5, SBT()))
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_query(peer_a.peer_id, queried_id, None)
            mocked_behavior.on_query_self.assert_not_called()
            mocked_behavior.on_query_sync.assert_not_called()
            mocked_behavior.on_query_external.assert_not_called()
            mocked_behavior.on_query_no_such_peer.assert_not_called()
        self.assertEqual(
            peer_a.in_queries_map[queried_id][peer_a.peer_id].response_time, 5)

    def test_only_updates_time_on_repeated_query(self):
        peer_a = self.helper.peer_with_prefix('0000')
        querying_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('1111')
        peer_a.in_queries_map.setdefault(queried_id, {}).setdefault(
            querying_peer_id, p.IncomingQuery(5, SBT()))
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            mocked_behavior.decide_delay.return_value = 3
            peer_a.recv_query(querying_peer_id, queried_id, None)
            mocked_behavior.on_query_self.assert_not_called()
            mocked_behavior.on_query_sync.assert_not_called()
            mocked_behavior.on_query_external.assert_not_called()
            mocked_behavior.on_query_no_such_peer.assert_not_called()
        self.assertEqual(
            peer_a.in_queries_map[queried_id][querying_peer_id].response_time,
            3)

    def test_doesnt_return_self_if_excluded(self):
        peer_a = self.helper.peer_with_prefix('')
        querying_peer_id = self.helper.id_with_prefix('')
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_query(querying_peer_id, peer_a.peer_id, None,
                              excluded_peer_ids=SBT({peer_a.peer_id: None}))
            mocked_behavior.on_query_self.assert_not_called()
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_query(querying_peer_id, peer_a.peer_id, None,
                              excluded_peer_ids=SBT(
                                  {peer_a.peer_id[:4]: None}))
            mocked_behavior.on_query_self.assert_not_called()

    def test_doesnt_return_sync_peer_if_excluded(self):
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0000')
        querying_peer_id = self.helper.id_with_prefix('')
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_query(querying_peer_id, peer_b.peer_id, None,
                              excluded_peer_ids=SBT({peer_b.peer_id: None}))
            mocked_behavior.on_query_sync.assert_not_called()
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_query(querying_peer_id, peer_b.peer_id, None,
                              excluded_peer_ids=SBT(
                                  {peer_b.peer_id[:2]: None}))
            mocked_behavior.on_query_sync.assert_not_called()

    def test_passes_on_excluded_peer_ids(self):
        peer_a = self.helper.peer_with_prefix('0000')
        querying_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('1111')
        excluded_id = self.helper.id_with_prefix('1111')
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_query(querying_peer_id, queried_id, None,
                              excluded_peer_ids=SBT({excluded_id: None}))
            mocked_behavior.on_query_external.assert_called_once_with(
                querying_peer_id, queried_id, ANY,
                excluded_peer_ids=SBT({excluded_id: None}))

    def test_excludes_own_prefix_if_all_sync_peers_are_excluded(self):
        peer_a = self.helper.peer_with_prefix('0000')
        peer_b = self.helper.peer_with_prefix('0000')
        peer_c = self.helper.peer_with_prefix('0000')
        querying_peer_id = self.helper.id_with_prefix('')
        queried_id = bs.Bits('0b0')
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_query(querying_peer_id, queried_id, None,
                              excluded_peer_ids=SBT({peer_a.peer_id: None,
                                                     peer_b.peer_id: None,
                                                     peer_c.peer_id: None}))
            mocked_behavior.on_query_external.assert_called_once_with(
                querying_peer_id, queried_id, ANY, excluded_peer_ids=SBT({
                    peer_a.prefix: None, peer_a.peer_id: None,
                    peer_b.peer_id: None, peer_c.peer_id: None}))

    def test_responds_no_such_peer_if_prefix_covers_queried_id(self):
        peer_a = self.helper.peer_with_prefix('0000')
        self.helper.peer_with_prefix('0000')
        querying_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('0000')
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_query(querying_peer_id, queried_id, None)
            mocked_behavior.on_query_no_such_peer.assert_called_once_with(
                querying_peer_id, queried_id, ANY)

    def test_responds_no_such_peer_if_all_sync_groups_excluded(self):
        self.helper.settings['prefix_length'] = 2
        peer_a = self.helper.peer_with_prefix('00')
        querying_peer_id = self.helper.id_with_prefix('')
        queried_id = bs.Bits('0b0')
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_query(querying_peer_id, queried_id, None,
                              excluded_peer_ids=SBT({peer_a.peer_id: None,
                                                     bs.Bits('0b01'): None}))
            mocked_behavior.on_query_no_such_peer.assert_called_once_with(
                querying_peer_id, queried_id, ANY)

    def test_doesnt_respond_no_such_peer_if_not_all_sync_groups_excluded(self):
        self.helper.settings['prefix_length'] = 3
        peer_a = self.helper.peer_with_prefix('000')
        querying_peer_id = self.helper.id_with_prefix('')
        queried_id = bs.Bits('0b0')
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_query(querying_peer_id, queried_id, None,
                              excluded_peer_ids=SBT({peer_a.peer_id: None,
                                                     bs.Bits('0b001'): None,
                                                     bs.Bits('0b011'): None}))
            mocked_behavior.on_query_no_such_peer.assert_not_called()


class TestRecvResponse(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_reacts_to_success(self):
        peer_a = self.helper.peer_with_prefix('')
        responding_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        excluded_id = self.helper.id_with_prefix('')
        queried_peer_info = self.helper.peer_with_prefix('').info()
        out_query = p.OutgoingQuery(0, set(), False, False,
                                    SBT({excluded_id: None}))
        out_query.timeout_proc = unittest.mock.Mock()
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            responding_peer_id, out_query)
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_response(responding_peer_id, queried_id,
                                 queried_peer_info, None)
            mocked_behavior.on_response_success.assert_called_once_with(
                responding_peer_id, queried_id, queried_peer_info,
                SBT({excluded_id: None}), ANY)

    def test_reacts_to_failure(self):
        peer_a = self.helper.peer_with_prefix('')
        responding_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        out_query = p.OutgoingQuery(0, set(), False, False, SBT())
        out_query.timeout_proc = unittest.mock.Mock()
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            responding_peer_id, out_query)
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_response(responding_peer_id, queried_id, None, None)
            mocked_behavior.on_response_failure.assert_called_once_with(
                responding_peer_id, queried_id, set(), False, False, SBT(),
                ANY)

    def test_passes_on_peers_already_queried_on_failure(self):
        peer_a = self.helper.peer_with_prefix('')
        responding_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        peers_already_queried = set(self.helper.peer_with_prefix('').peer_id
                                    for _ in range(5))
        out_query = p.OutgoingQuery(0, peers_already_queried, False, False,
                                    SBT())
        out_query.timeout_proc = unittest.mock.Mock()
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            responding_peer_id, out_query)
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_response(responding_peer_id, queried_id, None, None)
            mocked_behavior.on_response_failure.assert_called_once_with(
                responding_peer_id, queried_id, peers_already_queried, False,
                False, SBT(), ANY)

    def test_passes_on_query_further_on_failure(self):
        peer_a = self.helper.peer_with_prefix('')
        responding_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        out_query = p.OutgoingQuery(0, set(), True, False, SBT())
        out_query.timeout_proc = unittest.mock.Mock()
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            responding_peer_id, out_query)
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_response(responding_peer_id, queried_id, None, None)
            mocked_behavior.on_response_failure.assert_called_once_with(
                responding_peer_id, queried_id, set(), True, False, SBT(), ANY)

    def test_passes_on_query_sync_on_failure(self):
        peer_a = self.helper.peer_with_prefix('')
        responding_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        out_query = p.OutgoingQuery(0, set(), False, True, SBT())
        out_query.timeout_proc = unittest.mock.Mock()
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            responding_peer_id, out_query)
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_response(responding_peer_id, queried_id, None, None)
            mocked_behavior.on_response_failure.assert_called_once_with(
                responding_peer_id, queried_id, set(), False, True, SBT(), ANY)

    def test_passes_on_excluded_peer_ids_on_failure(self):
        peer_a = self.helper.peer_with_prefix('')
        responding_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        excluded_id = self.helper.id_with_prefix('')
        out_query = p.OutgoingQuery(0, set(), False, True,
                                    SBT({excluded_id: None}))
        out_query.timeout_proc = unittest.mock.Mock()
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            responding_peer_id, out_query)
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_response(responding_peer_id, queried_id, None, None)
            mocked_behavior.on_response_failure.assert_called_once_with(
                responding_peer_id, queried_id, set(), False, True,
                SBT({excluded_id: ANY}), ANY)

    def test_doesnt_react_if_unmatched(self):
        peer_a = self.helper.peer_with_prefix('')
        responding_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_response(responding_peer_id, queried_id, None, None)
            mocked_behavior.on_response_success.assert_not_called()
            mocked_behavior.on_response_failure.assert_not_called()

    def test_doesnt_react_if_returned_excluded_peer(self):
        peer_a = self.helper.peer_with_prefix('')
        responding_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        queried_peer_info = self.helper.peer_with_prefix('').info()
        out_query = p.OutgoingQuery(0, set(), False, False,
                                    SBT({queried_peer_info.peer_id: None}))
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            responding_peer_id, out_query)
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            peer_a.recv_response(responding_peer_id, queried_id,
                                 queried_peer_info, None)
            mocked_behavior.on_response_success.assert_not_called()
            mocked_behavior.on_response_failure.assert_not_called()
        self.assertEqual(
            peer_a.out_queries_map[queried_id][responding_peer_id],
            out_query)

    def test_deletes_out_query(self):
        peer_a = self.helper.peer_with_prefix('')
        responding_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        queried_peer_info = self.helper.peer_with_prefix('').info()
        out_query = p.OutgoingQuery(0, set(), False, False, SBT())
        out_query.timeout_proc = unittest.mock.Mock()
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            responding_peer_id, out_query)
        peer_a.out_queries_map[queried_id]['asd'] = 1
        peer_a.recv_response(responding_peer_id, queried_id, queried_peer_info,
                             None)
        self.assertEqual(peer_a.out_queries_map, {queried_id: {'asd': 1}})

    def test_deletes_out_query_enclosing_dict(self):
        peer_a = self.helper.peer_with_prefix('')
        responding_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        queried_peer_info = self.helper.peer_with_prefix('').info()
        out_query = p.OutgoingQuery(0, set(), False, False, SBT())
        out_query.timeout_proc = unittest.mock.Mock()
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            responding_peer_id, out_query)
        peer_a.recv_response(responding_peer_id, queried_id, queried_peer_info,
                             None)
        self.assertEqual(peer_a.out_queries_map, {})

    def test_introduces_on_success(self):
        peer_a = self.helper.peer_with_prefix('')
        responding_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        queried_peer_info = self.helper.peer_with_prefix('').info()
        out_query = p.OutgoingQuery(0, set(), False, False, SBT())
        out_query.timeout_proc = unittest.mock.Mock()
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            responding_peer_id, out_query)
        with unittest.mock.patch.object(peer_a, 'introduce') as mocked_intro:
            peer_a.recv_response(responding_peer_id, queried_id,
                                 queried_peer_info, None)
            mocked_intro.assert_called_once_with(queried_peer_info)

    def test_interrupts_timeout(self):
        peer_a = self.helper.peer_with_prefix('')
        responding_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        queried_peer_info = self.helper.peer_with_prefix('').info()
        out_query = p.OutgoingQuery(0, set(), False, False, SBT())
        out_query.timeout_proc = unittest.mock.Mock()
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            responding_peer_id, out_query)
        peer_a.recv_response(responding_peer_id, queried_id, queried_peer_info,
                             None)
        out_query.timeout_proc.interrupt.assert_called_once_with()


class TestQueryTimeout(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()

    def test_reacts_to_triggered_timeout(self):
        peer_a = self.helper.peer_with_prefix('')
        timeout_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            timeout_peer_id, p.OutgoingQuery(0, set(), False, False, SBT()))
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            mocked_behavior.expect_delay.return_value = 0
            to = peer_a.query_timeout(timeout_peer_id, queried_id, None)
            next(to)
            try:
                next(to)
                self.fail('Too many events generated.')
            except StopIteration:
                pass
            mocked_behavior.on_timeout.assert_called_once_with(
                timeout_peer_id, queried_id, set(), False, False, SBT(), ANY)

    def test_doesnt_react_if_interrupted(self):
        peer_a = self.helper.peer_with_prefix('')
        timeout_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        with unittest.mock.patch.object(peer_a, 'behavior')\
                as mocked_behavior,\
                unittest.mock.patch.object(peer_a.env, 'timeout')\
                as mocked_timeout:
            mocked_timeout.side_effect = simpy.Interrupt
            to = peer_a.query_timeout(timeout_peer_id, queried_id, None)
            try:
                next(to)
                self.fail('Timeout was not interrupted.')
            except StopIteration:
                pass
            mocked_behavior.on_timeout.assert_not_called()

    def test_chooses_timeout_delay(self):
        peer_a = self.helper.peer_with_prefix('')
        timeout_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        with unittest.mock.patch.object(peer_a, 'behavior')\
                as mocked_behavior,\
                unittest.mock.patch.object(peer_a.env, 'timeout')\
                as mocked_timeout:
            mocked_behavior.expect_delay.return_value = 3
            timeout_delay = self.helper.settings['query_timeout'] + 3
            to = peer_a.query_timeout(timeout_peer_id, queried_id, None)
            next(to)
            mocked_timeout.assert_called_once_with(timeout_delay)

    def test_deletes_out_query(self):
        peer_a = self.helper.peer_with_prefix('')
        timeout_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            timeout_peer_id, p.OutgoingQuery(0, set(), False, False, SBT()))
        peer_a.out_queries_map[queried_id]['asd'] = 1
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            mocked_behavior.expect_delay.return_value = 0
            to = peer_a.query_timeout(timeout_peer_id, queried_id, None)
            next(to)
            try:
                next(to)
            except StopIteration:
                pass
        self.assertEqual(peer_a.out_queries_map[queried_id], {'asd': 1})

    def test_deletes_out_query_enclosing_dict(self):
        peer_a = self.helper.peer_with_prefix('')
        timeout_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            timeout_peer_id, p.OutgoingQuery(0, set(), False, False, SBT()))
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            mocked_behavior.expect_delay.return_value = 0
            to = peer_a.query_timeout(timeout_peer_id, queried_id, None)
            next(to)
            try:
                next(to)
            except StopIteration:
                pass
        self.assertEqual(peer_a.out_queries_map, {})

    def test_passes_on_peers_already_queried(self):
        peer_a = self.helper.peer_with_prefix('')
        timeout_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        peers_already_queried = set(self.helper.peer_with_prefix('').peer_id
                                    for _ in range(5))
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            timeout_peer_id, p.OutgoingQuery(0, peers_already_queried, False,
                                             False, SBT()))
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            mocked_behavior.expect_delay.return_value = 0
            to = peer_a.query_timeout(timeout_peer_id, queried_id, None)
            next(to)
            try:
                next(to)
                self.fail('Too many events generated.')
            except StopIteration:
                pass
            mocked_behavior.on_timeout.assert_called_once_with(
                timeout_peer_id, queried_id, peers_already_queried, False,
                False, SBT(), ANY)

    def test_passes_on_query_further(self):
        peer_a = self.helper.peer_with_prefix('')
        timeout_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            timeout_peer_id, p.OutgoingQuery(0, set(), True, False, SBT()))
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            mocked_behavior.expect_delay.return_value = 0
            to = peer_a.query_timeout(timeout_peer_id, queried_id, None)
            next(to)
            try:
                next(to)
                self.fail('Too many events generated.')
            except StopIteration:
                pass
            mocked_behavior.on_timeout.assert_called_once_with(
                timeout_peer_id, queried_id, set(), True, False, SBT(), ANY)

    def test_passes_on_query_sync(self):
        peer_a = self.helper.peer_with_prefix('')
        timeout_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            timeout_peer_id, p.OutgoingQuery(0, set(), False, True, SBT()))
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            mocked_behavior.expect_delay.return_value = 0
            to = peer_a.query_timeout(timeout_peer_id, queried_id, None)
            next(to)
            try:
                next(to)
                self.fail('Too many events generated.')
            except StopIteration:
                pass
            mocked_behavior.on_timeout.assert_called_once_with(
                timeout_peer_id, queried_id, set(), False, True, SBT(), ANY)

    def test_passes_on_excluded_peer_ids(self):
        peer_a = self.helper.peer_with_prefix('')
        timeout_peer_id = self.helper.id_with_prefix('')
        queried_id = self.helper.id_with_prefix('')
        excluded_id = self.helper.id_with_prefix('')
        peer_a.out_queries_map.setdefault(queried_id, {}).setdefault(
            timeout_peer_id, p.OutgoingQuery(0, set(), False, False,
                                             SBT({excluded_id: None})))
        with unittest.mock.patch.object(peer_a, 'behavior') as mocked_behavior:
            mocked_behavior.expect_delay.return_value = 0
            to = peer_a.query_timeout(timeout_peer_id, queried_id, None)
            next(to)
            try:
                next(to)
                self.fail('Too many events generated.')
            except StopIteration:
                pass
            mocked_behavior.on_timeout.assert_called_once_with(
                timeout_peer_id, queried_id, set(), False, False,
                SBT({excluded_id: ANY}), ANY)


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
                         {sp: SBT() for sp in peer.subprefixes()})

    def test_with_all_peers_same_prefix(self):
        peer = self.helper.peer_with_prefix('0000')
        self.helper.create_query_group(
            peer,
            self.helper.peer_with_prefix('0000'),
            self.helper.peer_with_prefix('0000'))
        self.assertEqual(peer.subprefix_coverage(),
                         {sp: SBT() for sp in peer.subprefixes()})

    def test_subprefix_coverage(self):
        peer = self.helper.peer_with_prefix('0000')
        peer_1_0001 = self.helper.peer_with_prefix('0001')
        peer_2_0001 = self.helper.peer_with_prefix('0001')
        peer_3_0100 = self.helper.peer_with_prefix('0100')
        peer_4_0101 = self.helper.peer_with_prefix('0101')
        peer_5_0110 = self.helper.peer_with_prefix('0110')
        peer_6_1111 = self.helper.peer_with_prefix('1111')
        self.helper.create_query_group(
            peer, peer_1_0001, peer_2_0001, peer_3_0100, peer_4_0101,
            peer_5_0110, peer_6_1111)
        self.assertEqual(peer.subprefix_coverage(), {
                         bs.Bits(bin='0001'): SBT({peer_1_0001.peer_id: None,
                                                   peer_2_0001.peer_id: None}),
                         bs.Bits(bin='001'): SBT(),
                         bs.Bits(bin='01'): SBT({peer_3_0100.peer_id: None,
                                                 peer_4_0101.peer_id: None,
                                                 peer_5_0110.peer_id: None}),
                         bs.Bits(bin='1'): SBT({peer_6_1111.peer_id: None})})


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
            peer.peer_id, peer.address, peer_a.address, bs.Bits('0b01'), SBT(),
            ANY)

    def test_queries_covered_prefixes_if_less_than_desired(self):
        self.helper.settings['min_desired_query_peers'] = 2
        peer = self.helper.peer_with_prefix('00')
        peer_a = self.helper.peer_with_prefix('10')
        peer_b = self.helper.peer_with_prefix('10')
        self.helper.create_query_group(peer, peer_a, peer_b)
        peer.find_missing_query_peers()
        self.mocked_send_query.assert_called_once_with(
            peer.peer_id, peer.address,
            arg_any_of(peer_a.address, peer_b.address),
            bs.Bits('0b01'), SBT(), ANY)

    def test_specifies_known_peers(self):
        self.helper.settings['min_desired_query_peers'] = 2
        peer = self.helper.peer_with_prefix('00')
        peer_a = self.helper.peer_with_prefix('10')
        peer_b = self.helper.peer_with_prefix('10')
        peer_c = self.helper.peer_with_prefix('01')
        self.helper.create_query_group(peer, peer_a, peer_b, peer_c)
        peer.find_missing_query_peers()
        self.mocked_send_query.assert_called_once_with(
            peer.peer_id, peer.address, ANY, bs.Bits('0b01'),
            SBT({peer_c.peer_id: ANY}), ANY)

    def test_also_quries_peers_for_prefixes_who_were_excluded(self):
        self.helper.settings['min_desired_query_peers'] = 2
        peer = self.helper.peer_with_prefix('00')
        peer_a = self.helper.peer_with_prefix('10')
        peer_b = self.helper.peer_with_prefix('10')
        peer_c = self.helper.peer_with_prefix('01')
        self.helper.create_query_group(peer, peer_a, peer_b, peer_c)
        peer.find_missing_query_peers()
        self.mocked_send_query.assert_called_once_with(
            peer.peer_id, peer.address, peer_c.address, bs.Bits('0b01'),
            SBT({peer_c.peer_id: ANY}), ANY)

    def test_doesnt_query_if_query_is_pending(self):
        peer = self.helper.peer_with_prefix('00')
        peer_a = self.helper.peer_with_prefix('10')
        self.helper.create_query_group(peer, peer_a)
        peer.out_queries_map[bs.Bits('0b0100101')] = {
            peer_a.peer_id: p.OutgoingQuery(0, set(), False, False, SBT())
        }
        peer.find_missing_query_peers()
        self.mocked_send_query.assert_not_called()

    def test_queries_if_query_is_pending_but_doesnt_exclude_known_peers(self):
        self.helper.settings['min_desired_query_peers'] = 2
        peer = self.helper.peer_with_prefix('00')
        peer_a = self.helper.peer_with_prefix('10')
        peer_b = self.helper.peer_with_prefix('10')
        peer_c = self.helper.peer_with_prefix('01')
        self.helper.create_query_group(peer, peer_a, peer_b, peer_c)
        peer.out_queries_map[bs.Bits('0b0100101')] = {
            peer_a.peer_id: p.OutgoingQuery(0, set(), False, False, SBT())
        }
        peer.find_missing_query_peers()
        self.mocked_send_query.assert_called_once_with(
            peer.peer_id, peer.address, peer_c.address, bs.Bits('0b01'),
            SBT({peer_c.peer_id: ANY}), ANY)

    def test_queries_sync_peers(self):
        self.helper.settings['query_sync_for_subprefixes'] = True
        peer = self.helper.peer_with_prefix('00')
        peer_a = self.helper.peer_with_prefix('00')
        peer.find_missing_query_peers()
        self.assertEqual(len(self.mocked_send_query.call_args_list), 2)
        self.assertTrue(
            call(peer.peer_id, peer.address, peer_a.address, bs.Bits('0b01'),
                 SBT(), ANY)
            in self.mocked_send_query.call_args_list)
        self.assertTrue(
            call(peer.peer_id, peer.address, peer_a.address, bs.Bits('0b1'),
                 SBT(), ANY)
            in self.mocked_send_query.call_args_list)

    def test_ignores_non_existent_subprefixes(self):
        self.helper.settings['ignore_non_existent_subprefixes'] = True
        peer = self.helper.peer_with_prefix('00')
        peer_a = self.helper.peer_with_prefix('10')
        self.helper.create_query_group(peer, peer_a)
        peer.find_missing_query_peers()
        self.mocked_send_query.assert_not_called()

    def test_doesnt_query_for_more_if_there_is_none(self):
        self.helper.settings['ignore_non_existent_subprefixes'] = True
        self.helper.settings['min_desired_query_peers'] = 2
        peer = self.helper.peer_with_prefix('00')
        peer_a = self.helper.peer_with_prefix('10')
        self.helper.create_query_group(peer, peer_a)
        peer.find_missing_query_peers()
        self.mocked_send_query.assert_not_called()


class TestHasInQuery(unittest.TestCase):
    def setUp(self):
        self.mock_peer = unittest.mock.Mock()
        self.mock_peer.in_queries_map = util.SortedBitsTrie()
        self.id_1 = bs.Bits('0b0000')
        self.id_2 = bs.Bits('0b1000')
        self.id_3 = bs.Bits('0b0100')
        self.id_4 = bs.Bits('0b1100')

    def test_no_match(self):
        self.mock_peer.in_queries_map.setdefault(self.id_1, {}).setdefault(
            self.id_2, p.IncomingQuery(0, SBT()))
        self.assertFalse(p.Peer.has_in_query(self.mock_peer, self.id_3,
                                             self.id_4, set()))

    def test_match(self):
        self.mock_peer.in_queries_map.setdefault(self.id_1, {}).setdefault(
            self.id_2, p.IncomingQuery(0, SBT({self.id_3: None})))
        self.assertTrue(p.Peer.has_in_query(self.mock_peer, self.id_2,
                                            self.id_1, SBT()))

    def test_no_excluded_peers_match(self):
        self.mock_peer.in_queries_map.setdefault(self.id_1, {}).setdefault(
            self.id_2, p.IncomingQuery(0, SBT()))
        self.assertFalse(p.Peer.has_in_query(self.mock_peer, self.id_2,
                                             self.id_1,
                                             SBT({self.id_3: None})))
        self.assertFalse(p.Peer.has_in_query(self.mock_peer, self.id_2,
                                             self.id_1,
                                             SBT({self.id_3[:1]: None})))


class TestHasMatchingOutQueries(unittest.TestCase):
    def setUp(self):
        self.mock_peer = unittest.mock.Mock()
        self.mock_peer.out_queries_map = util.SortedBitsTrie()
        self.id_1 = bs.Bits('0b0000')
        self.id_2 = bs.Bits('0b1000')
        self.id_3 = bs.Bits('0b0100')
        self.id_4 = bs.Bits('0b1100')

    def test_no_match(self):
        self.assertFalse(p.Peer.has_matching_out_queries(self.mock_peer,
                                                         self.id_1, SBT()))
        self.mock_peer.out_queries_map.setdefault(self.id_1, {}).setdefault(
            self.id_2, 0)
        self.assertFalse(p.Peer.has_matching_out_queries(self.mock_peer,
                                                         self.id_3, SBT()))

    def test_exact_match(self):
        self.mock_peer.out_queries_map.setdefault(self.id_1, {}).setdefault(
            self.id_2, p.IncomingQuery(0, SBT()))
        self.mock_peer.out_queries_map.setdefault(
            self.id_3[:-2], {}).setdefault(self.id_4,
                                           p.IncomingQuery(0, SBT()))
        self.assertTrue(p.Peer.has_matching_out_queries(self.mock_peer,
                                                        self.id_1, SBT()))
        self.assertTrue(p.Peer.has_matching_out_queries(self.mock_peer,
                                                        self.id_3[:-2], SBT()))

    def test_prefix_match(self):
        self.mock_peer.out_queries_map.setdefault(self.id_1, {}).setdefault(
            self.id_2, p.IncomingQuery(0, SBT()))
        self.mock_peer.out_queries_map.setdefault(
            self.id_3[:-2], {}).setdefault(self.id_4,
                                           p.IncomingQuery(0, SBT()))
        self.assertTrue(p.Peer.has_matching_out_queries(self.mock_peer,
                                                        self.id_1[:-2], SBT()))
        self.assertFalse(p.Peer.has_matching_out_queries(self.mock_peer,
                                                         self.id_3, SBT()))

    def test_match_if_excluded_peer_ids_is_a_superset(self):
        self.mock_peer.out_queries_map.setdefault(self.id_1, {}).setdefault(
            self.id_2, p.OutgoingQuery(
                0, set(), False, False, SBT({self.id_3: None,
                                             self.id_4: None})))
        self.assertTrue(p.Peer.has_matching_out_queries(
            self.mock_peer, self.id_1, SBT({self.id_3: None,
                                            self.id_4: None})))
        self.assertTrue(p.Peer.has_matching_out_queries(
            self.mock_peer, self.id_1, SBT({self.id_4: None})))
        self.assertTrue(p.Peer.has_matching_out_queries(
            self.mock_peer, self.id_1, SBT()))

    def test_match_if_excluded_peer_ids_has_prefix(self):
        self.mock_peer.out_queries_map.setdefault(self.id_1, {}).setdefault(
            self.id_2, p.OutgoingQuery(
                0, set(), False, False, SBT({self.id_3[:1]: None})))
        self.assertTrue(p.Peer.has_matching_out_queries(
            self.mock_peer, self.id_1, SBT({self.id_3: None})))

    def test_no_match_if_excluded_peer_ids_isnt_a_superset(self):
        self.mock_peer.out_queries_map.setdefault(self.id_1, {}).setdefault(
            self.id_2, p.OutgoingQuery(
                0, set(), False, False, SBT({self.id_3: None})))
        self.assertFalse(p.Peer.has_matching_out_queries(
            self.mock_peer, self.id_1, SBT({self.id_3: None,
                                            self.id_4: None})))
        self.assertFalse(p.Peer.has_matching_out_queries(
            self.mock_peer, self.id_1, SBT({self.id_4: None})))


class TestMatchingInQueries(unittest.TestCase):
    def setUp(self):
        self.mock_peer = unittest.mock.Mock()
        self.mock_peer.in_queries_map = util.SortedBitsTrie()
        self.id_1 = bs.Bits('0b0000')
        self.id_2 = bs.Bits('0b1000')
        self.id_3 = bs.Bits('0b0100')
        self.id_4 = bs.Bits('0b1100')

    def in_query_eq(self, other):
        return (self.response_time == other.response_time
                and self.excluded_peer_ids == other.excluded_peer_ids)

    p.IncomingQuery.__eq__ = in_query_eq

    def test_no_match(self):
        self.mock_peer.in_queries_map.setdefault(self.id_1, {}).setdefault(
            self.id_2, p.IncomingQuery(0, SBT()))
        self.assertEqual(p.Peer.matching_in_queries(self.mock_peer, self.id_3,
                                                    SBT()),
                         {})

    def test_exact_match(self):
        self.mock_peer.in_queries_map.setdefault(self.id_1, {}).setdefault(
            self.id_2, p.IncomingQuery(0, SBT()))
        self.mock_peer.in_queries_map.setdefault(
            self.id_3[:-2], {}).setdefault(self.id_4,
                                           p.IncomingQuery(0, SBT()))
        self.assertEqual(p.Peer.matching_in_queries(self.mock_peer, self.id_1,
                                                    SBT()),
                         {self.id_1: {self.id_2: p.IncomingQuery(0, SBT())}})
        self.assertEqual(p.Peer.matching_in_queries(self.mock_peer,
                                                    self.id_3[:-2], SBT()),
                         {self.id_3[:-2]: {
                             self.id_4: p.IncomingQuery(0, SBT())}})

    def test_no_longer_matches(self):
        self.mock_peer.in_queries_map.setdefault(self.id_1, {}).setdefault(
            self.id_2, p.IncomingQuery(0, SBT()))
        self.mock_peer.in_queries_map.setdefault(
            self.id_1[:-2], {}).setdefault(self.id_3,
                                           p.IncomingQuery(0, SBT()))
        self.assertEqual(p.Peer.matching_in_queries(self.mock_peer,
                                                    self.id_1[:-2], SBT()),
                         {self.id_1[:-2]: {
                             self.id_3: p.IncomingQuery(0, SBT())}})

    def test_multiple_matches(self):
        self.mock_peer.in_queries_map.setdefault(self.id_1, {}).setdefault(
            self.id_2, p.IncomingQuery(0, SBT()))
        self.mock_peer.in_queries_map.setdefault(
            self.id_1[:-2], {}).setdefault(self.id_3,
                                           p.IncomingQuery(0, SBT()))
        self.assertEqual(p.Peer.matching_in_queries(self.mock_peer, self.id_1,
                                                    SBT()),
                         {self.id_1: {self.id_2: p.IncomingQuery(0, SBT())},
                          self.id_1[:-2]: {
                              self.id_3: p.IncomingQuery(0, SBT())}})

    def test_no_match_due_to_excluded_peer_ids(self):
        self.mock_peer.in_queries_map.setdefault(self.id_1, {}).setdefault(
            self.id_2, p.IncomingQuery(0, SBT({self.id_3: None})))
        self.assertEqual(p.Peer.matching_in_queries(self.mock_peer, self.id_1,
                                                    SBT()), {})

    def test_match_if_excluded_peer_ids_have_prefix(self):
        self.mock_peer.in_queries_map.setdefault(self.id_1, {}).setdefault(
            self.id_2, p.IncomingQuery(0, SBT({bs.Bits('0b1100'): None,
                                               bs.Bits('0b1111'): None})))
        self.assertEqual(p.Peer.matching_in_queries(
            self.mock_peer, self.id_1, SBT({bs.Bits('0b11'): None})),
                         {
                             self.id_1: {self.id_2: p.IncomingQuery(
                                 0, SBT({bs.Bits('0b1100'): None,
                                         bs.Bits('0b1111'): None}))
                             }
                         })


class TestFinalizeInQueries(unittest.TestCase):
    def setUp(self):
        self.mock_peer = unittest.mock.Mock()
        self.mock_peer.in_queries_map = util.SortedBitsTrie()
        self.id_1 = bs.Bits('0b0000')
        self.id_2 = bs.Bits('0b1000')
        self.id_3 = bs.Bits('0b0100')
        self.id_4 = bs.Bits('0b1100')
        self.id_5 = bs.Bits('0b0010')
        self.mock_peer.peer_id = self.id_2

    def test_deletes_in_queries(self):
        in_queries_map = {
            self.id_1: {self.id_2: 0, self.id_4: 0}
        }
        self.mock_peer.in_queries_map = copy.deepcopy(in_queries_map)
        self.mock_peer.in_queries_map.setdefault(
            self.id_1[:-3], {}).setdefault(self.id_5, 0)
        p.Peer.finalize_in_queries(self.mock_peer, in_queries_map, 'status',
                                   None)
        self.assertEqual(self.mock_peer.in_queries_map,
                         {self.id_1[:-3]: {self.id_5: 0}})

    def test_finalizes_own_query(self):
        in_queries_map = {
            self.id_1: {self.id_2: 0, self.id_4: 0}
        }
        self.mock_peer.in_queries_map = copy.deepcopy(in_queries_map)
        with unittest.mock.patch.object(
                self.mock_peer, 'finalize_own_query') as mocked_finalize:
            p.Peer.finalize_in_queries(self.mock_peer, in_queries_map,
                                       'status', None)
            mocked_finalize.assert_called_once_with('status', ANY)


class TestOutQueryRecipients(unittest.TestCase):
    def setUp(self):
        self.mock_peer = unittest.mock.Mock()
        self.id_1 = bs.Bits(uint=0, length=8)
        self.id_2 = bs.Bits(uint=1, length=8)
        self.id_3 = bs.Bits(uint=2, length=8)
        self.id_4 = bs.Bits(uint=3, length=8)
        self.id_5 = bs.Bits(uint=4, length=8)

    def test_on_empty(self):
        self.mock_peer.out_queries_map = {}
        self.assertEqual(
            p.Peer.out_query_recipients(self.mock_peer, self.id_1), set())
        self.mock_peer.out_queries_map = {
            self.id_2: {self.id_3: 0, self.id_4: 0}
        }
        self.assertEqual(
            p.Peer.out_query_recipients(self.mock_peer, self.id_1), set())

    def test_on_matches(self):
        self.mock_peer.out_queries_map = {
            self.id_1: {self.id_2: 0, self.id_3: 0},
            self.id_4: {self.id_5: 0}
        }
        self.assertEqual(
            p.Peer.out_query_recipients(self.mock_peer, self.id_1),
            set((self.id_2, self.id_3)))
        self.assertEqual(
            p.Peer.out_query_recipients(self.mock_peer, self.id_4),
            set((self.id_5,)))


class TestPrefixesFor(unittest.TestCase):
    def setUp(self):
        self.helper = TestHelper()
        self.helper.settings['prefix_length'] = 3

    def test_generates_all(self):
        peer = self.helper.peer_with_prefix('')
        self.assertEqual(set(peer.prefixes_for(bs.Bits())),
                         set((bs.Bits('0b000'), bs.Bits('0b001'),
                              bs.Bits('0b010'), bs.Bits('0b011'),
                              bs.Bits('0b100'), bs.Bits('0b101'),
                              bs.Bits('0b110'), bs.Bits('0b111'))))
        self.assertEqual(set(peer.prefixes_for(bs.Bits('0b0'))),
                         set((bs.Bits('0b000'), bs.Bits('0b001'),
                              bs.Bits('0b010'), bs.Bits('0b011'))))
        self.assertEqual(set(peer.prefixes_for(bs.Bits('0b01'))),
                         set((bs.Bits('0b010'), bs.Bits('0b011'))))
        self.assertEqual(set(peer.prefixes_for(bs.Bits('0b101'))),
                         set((bs.Bits('0b101'),)))

    def test_generates_only_once(self):
        peer = self.helper.peer_with_prefix('')
        self.assertEqual(len(set(peer.prefixes_for(bs.Bits()))),
                         len(list(peer.prefixes_for(bs.Bits()))))
        self.assertEqual(len(set(peer.prefixes_for(bs.Bits('0b0')))),
                         len(list(peer.prefixes_for(bs.Bits('0b0')))))
        self.assertEqual(len(set(peer.prefixes_for(bs.Bits('0b01')))),
                         len(list(peer.prefixes_for(bs.Bits('0b01')))))
        self.assertEqual(len(set(peer.prefixes_for(bs.Bits('0b101')))),
                         len(list(peer.prefixes_for(bs.Bits('0b101')))))
