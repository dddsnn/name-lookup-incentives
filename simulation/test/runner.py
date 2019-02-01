import unittest
import sys
import util_test
import peer_test

loader = unittest.TestLoader()
suite = unittest.TestSuite()

suite.addTests(loader.loadTestsFromModule(util_test))
suite.addTests(loader.loadTestsFromModule(peer_test))

runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2)
result = runner.run(suite)