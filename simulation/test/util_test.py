import unittest.mock
import test_helper
import util
import peer
import bitstring as bs
import simpy


class TestBitOverlap(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(0, util.bit_overlap(bs.Bits(), bs.Bits()))

    def test_overlap(self):
        self.assertEqual(1, util.bit_overlap(bs.Bits('0b0101'),
                                             bs.Bits('0b0001')))
        self.assertEqual(2, util.bit_overlap(bs.Bits('0b0101'),
                                             bs.Bits('0b0111')))
        self.assertEqual(3, util.bit_overlap(bs.Bits('0b0101'),
                                             bs.Bits('0b0100')))

    def test_equal(self):
        self.assertEqual(4, util.bit_overlap(bs.Bits('0b0101'),
                                             bs.Bits('0b0101')))

    def test_left_longer(self):
        self.assertEqual(1, util.bit_overlap(bs.Bits('0b0101'),
                                             bs.Bits('0b00')))
        self.assertEqual(0, util.bit_overlap(bs.Bits('0b0101'),
                                             bs.Bits('0b10')))

    def test_right_longer(self):
        self.assertEqual(1, util.bit_overlap(bs.Bits('0b00'),
                                             bs.Bits('0b0101')))
        self.assertEqual(0, util.bit_overlap(bs.Bits('0b10'),
                                             bs.Bits('0b0101')))


class TestNetwork(unittest.TestCase):
    def setUp(self):
        self.settings = test_helper.get_settings()
        self.env = simpy.Environment()
        self.network = util.Network(self.env, self.settings)
        self.peer_a_id = bs.Bits(uint=0, length=16)
        self.peer_b_id = bs.Bits(uint=1, length=16)
        self.peer_a = unittest.mock.Mock(spec=peer.Peer)
        self.peer_b = unittest.mock.Mock(spec=peer.Peer)
        self.peer_a_address = self.network.register(self.peer_a)
        self.peer_b_address = self.network.register(self.peer_b)

    def test_assigns_unique_addresses(self):
        self.assertNotEqual(self.peer_a_address, self.peer_b_address)

    def test_sends_queries(self):
        queried_id = bs.Bits(uint=10, length=16)
        self.network.send_query(self.peer_a_id, self.peer_a_address,
                                self.peer_b_address, queried_id, 0)
        self.env.run()
        self.peer_b.recv_query.assert_called_with(self.peer_a_id, queried_id,
                                                  0)

    def test_sends_responses(self):
        self.network.send_response(self.peer_a_id, self.peer_a_address,
                                   self.peer_b_address, util.SortedIterSet(),
                                   None, 0)
        self.env.run()
        self.peer_b.recv_response.assert_called_with(self.peer_a_id,
                                                     util.SortedIterSet(),
                                                     None, 0)

    def test_adds_transmission_delay(self):
        queried_id = bs.Bits(uint=10, length=16)
        self.network.send_query(self.peer_a_id, self.peer_a_address,
                                self.peer_b_address, queried_id, 0)
        self.assertEqual(self.env.peek(), self.settings['transmission_delay'])

    def test_doesnt_add_transmission_delay_for_messages_to_oneself(self):
        queried_id = bs.Bits(uint=10, length=16)
        self.network.send_query(self.peer_a_id, self.peer_a_address,
                                self.peer_a_address, queried_id, 0)
        self.assertEqual(self.env.peek(), 0)

    def test_raises_for_unassigned_addresses(self):
        queried_id = bs.Bits(uint=10, length=16)
        unassigned_address = self.peer_a_address + self.peer_b_address + 1
        self.assertNotEqual(unassigned_address, self.peer_a_address)
        self.assertNotEqual(unassigned_address, self.peer_b_address)
        with self.assertRaises(util.UnassignedAddressError):
            self.network.send_query(self.peer_a_id, self.peer_a_address,
                                    unassigned_address, queried_id, 0)
