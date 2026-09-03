import os
import sys
import unittest

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import json

from core.watcher import SessionWatcher
from core.ledger import ledger


class TestWatcher(unittest.TestCase):
    def test_watcher_callback_execution(self):
        called = []
        watcher = SessionWatcher(on_update_callback=lambda act, all_r, sess: called.append((act, all_r, sess)))
        
        mock_session = {
            "session_id": "test_watch_sess",
            "file": "/dummy/path/log.jsonl",
            "mtime": 1000.0,
            "size": 500,
            "tokens": 200,
            "account": "user@example.com"
        }
        with patch("core.watcher.get_all_session_files", return_value=[mock_session]), \
             patch("core.watcher.parse_transcript_file_cached", return_value=({"prompt": 100, "thinking": 50, "candidates": 50}, [], "Test prompt")), \
             patch("pathlib.Path.stat", return_value=MagicMock(st_mtime=1000.0, st_size=500)):
            watcher._poll(force=True)
            self.assertGreater(len(called), 0)
            act, all_r, sess = called[0]
            self.assertIsNotNone(act)
            self.assertIsNotNone(all_r)
            self.assertEqual(len(sess), 1)

    def test_watcher_empty_sessions_state(self):
        called = []
        watcher = SessionWatcher(on_update_callback=lambda act, all_r, sess: called.append((act, all_r, sess)))
        with patch("core.watcher.get_all_session_files", return_value=[]):
            watcher._poll(force=True)
            self.assertGreater(len(called), 0)
            act, all_r, sess = called[0]
            self.assertEqual(act["session_id"], "No Sessions Found")
            self.assertEqual(act["total"], 0)
            self.assertEqual(len(sess), 0)

    def test_watcher_set_target_and_routing(self):
        watcher = SessionWatcher()
        mock_sessions = [
            {"session_id": "active_chat_1", "file": "/p/1.jsonl", "mtime": 2000.0, "size": 100},
            {"session_id": "historical_chat_2", "file": "/p/2.jsonl", "mtime": 1000.0, "size": 100},
        ]
        
        captured_active = []
        watcher.on_update_callback = lambda act, all_r, sess: captured_active.append(act)

        with patch("core.watcher.get_all_session_files", return_value=mock_sessions), \
             patch("core.watcher.parse_transcript_file_cached", return_value=({"prompt": 50, "thinking": 25, "candidates": 25}, [], "Prompt")), \
             patch("pathlib.Path.stat", return_value=MagicMock(st_mtime=2000.0, st_size=100)):
            
            # 1. Target mode_all=True -> routes to all_report
            with watcher._lock:
                watcher._selected_session_id = None
                watcher._mode_all = True
            watcher._poll(force=True)
            self.assertTrue(captured_active[-1]["is_all"])

            # 2. Target specific historical session -> routes to single_report
            with watcher._lock:
                watcher._selected_session_id = "historical_chat_2"
                watcher._mode_all = False
            watcher._poll(force=True)
            self.assertFalse(captured_active[-1]["is_all"])
            self.assertEqual(captured_active[-1]["session_id"], "historical_chat_2")

            # 3. Target default / ALL_CHATS -> routes to account_report
            with watcher._lock:
                watcher._selected_session_id = None
                watcher._mode_all = False
            watcher._poll(force=True)
            self.assertEqual(captured_active[-1]["mode"], "account")


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
