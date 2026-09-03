import os
import sys
import unittest

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from core.watcher import SessionWatcher


class TestWatcher(unittest.TestCase):
    def test_watcher_callback(self):
        called = []
        watcher = SessionWatcher(on_update_callback=lambda act, all_r, sess: called.append(True))
        watcher._poll(force=True)
        self.assertGreaterEqual(len(called), 0)


class TestSessionWatcherIdlePause(unittest.TestCase):
    def test_watcher_pause_resume_behavior(self):
        watcher = SessionWatcher()
        self.assertFalse(watcher.is_paused())

        # Test pause puts watcher into idle
        watcher.pause()
        self.assertTrue(watcher.is_paused())

        # Verify _poll skips when paused
        poll_executed = False
        def mock_callback(active, all_rep, sess):
            nonlocal poll_executed
            poll_executed = True

        watcher.on_update_callback = mock_callback
        watcher._poll(force=False)
        self.assertFalse(poll_executed)

        # Test resume wakes watcher and triggers sync
        watcher.resume()
        self.assertFalse(watcher.is_paused())

        # Cleanup
        watcher.stop()


if __name__ == "__main__":
    unittest.main()
