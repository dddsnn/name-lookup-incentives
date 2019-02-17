import util
import os
import bitstring as bs


bs.Bits.__lt__ = util.bits_lt


def get_settings():
    file_name = os.path.join(os.getcwd(), '../default.settings')
    return util.read_settings(file_name)
