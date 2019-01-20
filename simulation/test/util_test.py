import unittest
import simulation as s
import bitstring as bs


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


if __name__ == "__main__":
    unittest.main()
