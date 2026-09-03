import os
import sys
import unittest

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Explicitly import all domain test modules
from tests import (
    test_config,
    test_engine,
    test_cleaner,
    test_accounts,
    test_ledger,
    test_watcher,
    test_gui,
    test_stability,
)

MODULES = [
    test_config,
    test_engine,
    test_cleaner,
    test_accounts,
    test_ledger,
    test_watcher,
    test_gui,
    test_stability,
]


def load_tests(loader, standard_tests, pattern):
    """
    Standard unittest protocol:
    Enables `python -m unittest tests/test_all.py` to run all modular test suites
    with 100% backward compatibility.
    When invoked via `unittest discover`, pattern is provided so we yield to individual modules
    to avoid running the suite twice.
    """
    if pattern is not None:
        return unittest.TestSuite()

    suite = unittest.TestSuite()
    for module in MODULES:
        suite.addTests(loader.loadTestsFromModule(module))
    return suite


if __name__ == "__main__":
    unittest.main()
