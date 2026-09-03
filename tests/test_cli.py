import os
import sys
import io
import json
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import token_counter


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.mock_session_1 = {
            "session_id": "session-uuid-12345678-aaaa",
            "folder": "/mock/folder/1",
            "session_root_dir": "/mock/folder/1",
            "file": "/mock/folder/1/transcript_full.jsonl",
            "mtime": 1788100000.0,
            "size": 2048,
            "last_active_str": "2026-08-30 12:00:00",
            "first_prompt": "How to optimize Python performance",
            "tokens": 450,
            "account": "developer@company.org",
        }
        self.mock_session_2 = {
            "session_id": "session-uuid-87654321-bbbb",
            "folder": "/mock/folder/2",
            "session_root_dir": "/mock/folder/2",
            "file": "/mock/folder/2/transcript_full.jsonl",
            "mtime": 1788000000.0,
            "size": 4096,
            "last_active_str": "2026-08-29 10:00:00",
            "first_prompt": "Explain asyncio in detail",
            "tokens": 800,
            "account": "developer@company.org",
        }

        self.mock_single_rep = {
            "is_all": False,
            "session_id": "session-uuid-12345678-aaaa",
            "title": "How to optimize Python performance",
            "first_prompt": "How to optimize Python performance",
            "account": "developer@company.org",
            "last_active": "2026-08-30 12:00:00",
            "prompt": 150,
            "thinking": 100,
            "candidates": 200,
            "total": 450,
            "prompt_pct": 33.3,
            "thinking_pct": 22.2,
            "candidates_pct": 44.4,
            "tokens_5h": 450,
            "reset_5h_str": "in 2h 30m (50.0% remaining)",
            "tokens_7d": 450,
            "reset_7d_str": "in 5d 10h (75.0% remaining)",
            "burn_rate_str": "1,800 tok/hr",
        }

        self.mock_account_rep = {
            "account_email": "developer@company.org",
            "unique_sessions_count": 2,
            "prompt": 500,
            "thinking": 250,
            "candidates": 500,
            "total": 1250,
            "prompt_pct": 40.0,
            "thinking_pct": 20.0,
            "candidates_pct": 40.0,
            "tokens_5h": 450,
            "reset_5h_str": "in 2h 30m (50.0% remaining)",
            "tokens_7d": 1250,
            "reset_7d_str": "in 5d 10h (75.0% remaining)",
            "burn_rate_str": "1,800 tok/hr",
        }

        self.mock_all_rep = {
            "is_all": True,
            "unique_sessions_count": 2,
            "total_sessions_found": 2,
            "prompt": 500,
            "thinking": 250,
            "candidates": 500,
            "total": 1250,
            "prompt_pct": 40.0,
            "thinking_pct": 20.0,
            "candidates_pct": 40.0,
            "tokens_5h": 450,
            "reset_5h_str": "in 2h 30m",
            "tokens_7d": 1250,
            "reset_7d_str": "in 5d 10h",
            "burn_rate_str": "1,800 tok/hr",
        }

    @patch("token_counter.get_all_session_files")
    def test_report_current_session_no_sessions(self, mock_get_sessions):
        mock_get_sessions.return_value = []

        # Text mode
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_current_session(as_json=False)
        self.assertIn("No active sessions", buf.getvalue())

        # JSON mode
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_current_session(as_json=True)
        data = json.loads(buf.getvalue())
        self.assertIn("error", data)

    @patch("token_counter.get_all_session_files")
    @patch("token_counter.get_single_session_report")
    @patch("token_counter.get_active_account_report")
    @patch("token_counter.get_active_google_account")
    def test_report_current_session_active(self, mock_get_acc, mock_acc_rep, mock_single_rep, mock_get_sessions):
        mock_get_sessions.return_value = [self.mock_session_1, self.mock_session_2]
        mock_get_acc.return_value = "developer@company.org"
        mock_single_rep.return_value = self.mock_single_rep
        mock_acc_rep.return_value = self.mock_account_rep

        # Text mode
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_current_session(as_json=False)
        out = buf.getvalue()
        self.assertIn("ACTIVE CONVERSATION TOKEN REPORT", out)
        self.assertIn("developer@company.org", out)
        self.assertIn("450", out)

        # JSON mode
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_current_session(as_json=True)
        data = json.loads(buf.getvalue())
        self.assertIn("account_report", data)
        self.assertIn("active_chat_report", data)
        self.assertEqual(data["active_chat_report"]["total"], 450)

    @patch("token_counter.get_all_session_files")
    @patch("token_counter.get_single_session_report")
    @patch("token_counter.get_active_account_report")
    def test_report_current_session_specific_id(self, mock_acc_rep, mock_single_rep, mock_get_sessions):
        mock_get_sessions.return_value = [self.mock_session_1, self.mock_session_2]
        mock_single_rep.return_value = self.mock_single_rep
        mock_acc_rep.return_value = self.mock_account_rep

        # Found session (Text)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_current_session(specific_id="12345678", as_json=False)
        self.assertIn("GEMINI SESSION TOKEN REPORT", buf.getvalue())
        self.assertIn("session-uuid-12345678-aaaa", buf.getvalue())

        # Found session (JSON)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_current_session(specific_id="12345678", as_json=True)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["session_id"], "session-uuid-12345678-aaaa")

        # Not found session (Text)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_current_session(specific_id="nonexistent-id", as_json=False)
        self.assertIn("not found", buf.getvalue())

        # Not found session (JSON)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_current_session(specific_id="nonexistent-id", as_json=True)
        data = json.loads(buf.getvalue())
        self.assertIn("error", data)

    @patch("token_counter.get_all_session_files")
    @patch("token_counter.get_active_account_report")
    @patch("token_counter.get_active_google_account")
    def test_report_account_sessions(self, mock_get_acc, mock_acc_rep, mock_get_sessions):
        mock_get_sessions.return_value = [self.mock_session_1]
        mock_get_acc.return_value = "developer@company.org"
        mock_acc_rep.return_value = self.mock_account_rep

        # Text mode
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_account_sessions(as_json=False)
        self.assertIn("ACCOUNT ROLLING QUOTA REPORT", buf.getvalue())
        self.assertIn("1,250", buf.getvalue())

        # JSON mode
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_account_sessions(account_email="developer@company.org", as_json=True)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["total"], 1250)
        self.assertEqual(data["account_email"], "developer@company.org")

    @patch("token_counter.get_all_session_files")
    @patch("token_counter.get_all_sessions_report")
    def test_report_all_sessions(self, mock_all_rep, mock_get_sessions):
        # Empty
        mock_get_sessions.return_value = []
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_all_sessions(as_json=False)
        self.assertIn("No transcripts found", buf.getvalue())

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_all_sessions(as_json=True)
        data = json.loads(buf.getvalue())
        self.assertIn("error", data)

        # Populated
        mock_get_sessions.return_value = [self.mock_session_1, self.mock_session_2]
        mock_all_rep.return_value = self.mock_all_rep

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_all_sessions(as_json=False)
        self.assertIn("GEMINI TOTAL TOKEN CONSUMPTION", buf.getvalue())
        self.assertIn("1,250", buf.getvalue())

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_all_sessions(as_json=True)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["total"], 1250)
        self.assertTrue(data["is_all"])

    @patch("token_counter.get_all_session_files")
    @patch("token_counter.get_all_sessions_report")
    @patch("token_counter.ledger")
    def test_report_usage_graph(self, mock_ledger, mock_all_rep, mock_get_sessions):
        mock_get_sessions.return_value = [self.mock_session_1]
        mock_ledger.get_all_time_series_records.return_value = []

        # Text mode
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_usage_graph(timeframe="5h", as_json=False)
        self.assertIn("USAGE CHART", buf.getvalue().upper())

        # JSON mode
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_usage_graph(timeframe="7d", as_json=True)
        data = json.loads(buf.getvalue())
        self.assertIn("summary", data)
        self.assertIn("buckets", data)
        self.assertEqual(data["timeframe"], "7d")

        # Specific session and account mode
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_usage_graph(specific_id="session-uuid-1234", as_json=True)
        data = json.loads(buf.getvalue())
        self.assertIn("session-uuid-123", data["title"])

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_usage_graph(account_mode=True, as_json=True)
        data = json.loads(buf.getvalue())
        self.assertIn("Account", data["title"])

    @patch("token_counter.get_disk_usage_summary")
    def test_report_disk_usage(self, mock_summary):
        mock_summary.return_value = {
            "total_sessions": 2,
            "total_bytes": 6144,
            "total_size_str": "6.00 KB",
            "sessions": [
                {
                    "session_id": "session-1",
                    "size_str": "2.00 KB",
                    "last_active": "2026-08-30 12:00:00",
                },
                {
                    "session_id": "session-2",
                    "size_str": "4.00 KB",
                    "last_active": "2026-08-29 10:00:00",
                }
            ]
        }

        # Text mode
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_disk_usage(page=1, limit=10, as_json=False)
        out = buf.getvalue()
        self.assertIn("GEMINI SESSION STORAGE & DISK USAGE", out)
        self.assertIn("6.00 KB", out)
        self.assertIn("session-1", out)

        # JSON mode
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.report_disk_usage(page=1, limit=10, as_json=True)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["total_sessions"], 2)
        self.assertEqual(data["total_bytes"], 6144)
        self.assertEqual(data["pagination"]["page"], 1)

    @patch("token_counter.delete_session_files")
    @patch("token_counter.prune_sessions_by_age")
    @patch("token_counter.prune_sessions_keep_latest")
    @patch("token_counter.prune_empty_sessions")
    @patch("token_counter.prune_all_previous")
    def test_handle_cleaning(self, mock_all_prev, mock_empty, mock_keep, mock_age, mock_del):
        mock_del.return_value = (True, 1024, "Session deleted")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.handle_cleaning(delete_session="sess-to-delete")
        self.assertIn("[CLEAN] Session deleted", buf.getvalue())
        mock_del.assert_called_once_with("sess-to-delete")

        mock_age.return_value = {"deleted_count": 3, "freed_str": "15.00 MB"}
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.handle_cleaning(older_than=30)
        self.assertIn("Pruned 3 session(s) older than 30 days", buf.getvalue())

        mock_keep.return_value = {"deleted_count": 5, "freed_str": "25.00 MB"}
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.handle_cleaning(keep_latest=10)
        self.assertIn("Kept latest 10 sessions", buf.getvalue())

        mock_empty.return_value = {"deleted_count": 2, "freed_str": "0 B"}
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.handle_cleaning(clean_empty=True)
        self.assertIn("Removed 2 empty", buf.getvalue())

        mock_all_prev.return_value = {"deleted_count": 8, "freed_str": "40.00 MB"}
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            token_counter.handle_cleaning(clean_all_prev=True)
        self.assertIn("Deleted 8 historical session(s)", buf.getvalue())

    @patch("token_counter.report_current_session")
    @patch("token_counter.report_account_sessions")
    @patch("token_counter.report_all_sessions")
    @patch("token_counter.report_usage_graph")
    @patch("token_counter.report_disk_usage")
    @patch("token_counter.handle_cleaning")
    def test_main_cli_dispatch(self, mock_clean, mock_disk, mock_graph, mock_all, mock_acc, mock_curr):
        # Default -> report_current_session
        with patch("sys.argv", ["token_counter.py"]):
            token_counter.main()
        mock_curr.assert_called_once()

        # Specific session
        mock_curr.reset_mock()
        with patch("sys.argv", ["token_counter.py", "--session", "test-sid"]):
            token_counter.main()
        mock_curr.assert_called_once_with(specific_id="test-sid", as_json=False)

        # Account mode
        with patch("sys.argv", ["token_counter.py", "--account"]):
            token_counter.main()
        mock_acc.assert_called_once_with(account_email=None, as_json=False)

        # Specific account email
        mock_acc.reset_mock()
        with patch("sys.argv", ["token_counter.py", "--account", "user@company.org"]):
            token_counter.main()
        mock_acc.assert_called_once_with(account_email="user@company.org", as_json=False)

        # All mode
        with patch("sys.argv", ["token_counter.py", "--all"]):
            token_counter.main()
        mock_all.assert_called_once_with(as_json=False)

        # Disk usage
        with patch("sys.argv", ["token_counter.py", "--disk-usage", "--page", "2", "--limit", "20"]):
            token_counter.main()
        mock_disk.assert_called_once_with(page=2, limit=20, as_json=False)

        # Graph
        with patch("sys.argv", ["token_counter.py", "--graph", "--history", "24h"]):
            token_counter.main()
        mock_graph.assert_called_once_with(timeframe="24h", specific_id=None, account_mode=False, as_json=False)

        # Cleaning
        with patch("sys.argv", ["token_counter.py", "--clean-older-than", "14"]):
            token_counter.main()
        mock_clean.assert_called_once_with(
            older_than=14,
            keep_latest=None,
            delete_session=None,
            clean_empty=False,
            clean_all_prev=False
        )


if __name__ == "__main__":
    unittest.main()
