import unittest.mock
import simulation as s
import bitstring as bs
import simpy


class TestBitOverlap(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(0, s.bit_overlap(bs.Bits(), bs.Bits()))

    def test_overlap(self):
        self.assertEqual(1, s.bit_overlap(bs.Bits('0b0101'),
                                          bs.Bits('0b0001')))
        self.assertEqual(2, s.bit_overlap(bs.Bits('0b0101'),
                                          bs.Bits('0b0111')))
        self.assertEqual(3, s.bit_overlap(bs.Bits('0b0101'),
                                          bs.Bits('0b0100')))

    def test_equal(self):
        self.assertEqual(4, s.bit_overlap(bs.Bits('0b0101'),
                                          bs.Bits('0b0101')))

    def test_left_longer(self):
        self.assertEqual(1, s.bit_overlap(bs.Bits('0b0101'),
                                          bs.Bits('0b00')))
        self.assertEqual(0, s.bit_overlap(bs.Bits('0b0101'),
                                          bs.Bits('0b10')))

    def test_right_longer(self):
        self.assertEqual(1, s.bit_overlap(bs.Bits('0b00'),
                                          bs.Bits('0b0101')))
        self.assertEqual(0, s.bit_overlap(bs.Bits('0b10'),
                                          bs.Bits('0b0101')))


class TestNetwork(unittest.TestCase):
    def setUp(self):
        self.env = simpy.Environment()
        self.network = s.Network(self.env)
        self.peer_a_id = bs.Bits(uint=0, length=16)
        self.peer_b_id = bs.Bits(uint=1, length=16)
        self.peer_a = unittest.mock.Mock(spec=s.Peer)
        self.peer_b = unittest.mock.Mock(spec=s.Peer)
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
                                   self.peer_b_address, set(), None, 0)
        self.env.run()
        self.peer_b.recv_response.assert_called_with(self.peer_a_id, set(),
                                                     None, 0)

    def test_adds_transmission_delay(self):
        queried_id = bs.Bits(uint=10, length=16)
        self.network.send_query(self.peer_a_id, self.peer_a_address,
                                self.peer_b_address, queried_id, 0)
        self.assertEqual(self.env.peek(), s.Network.TRANSMISSION_DELAY)

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
        with self.assertRaises(s.UnassignedAddressError):
            self.network.send_query(self.peer_a_id, self.peer_a_address,
                                    unassigned_address, queried_id, 0)


if __name__ == "__main__":
    unittest.main()
