import os
import sys
import unittest
import tempfile
import json
from pathlib import Path

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from unittest.mock import patch

from core.cleaner import (
    format_bytes,
    delete_session_files,
    prune_sessions_by_age,
    prune_sessions_keep_latest,
    prune_empty_sessions,
    prune_all_previous,
    open_session_folder,
    open_storage_folder,
    get_disk_usage_summary,
    sync_and_prune_orphaned_sessions,
)
from core.ledger import ledger


class TestCleaner(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(500), "500 B")
        self.assertEqual(format_bytes(2048), "2.0 KB")
        self.assertEqual(format_bytes(5 * 1024 * 1024), "5.00 MB")
        self.assertEqual(format_bytes(2 * 1024 * 1024 * 1024), "2.00 GB")

    def test_prune_functions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a mock session folder with transcript
            mock_brain = Path(tmpdir) / "brain"
            mock_sess = mock_brain / "mock_session_1" / ".system_generated" / "logs"
            mock_sess.mkdir(parents=True, exist_ok=True)
            mock_file = mock_sess / "transcript_full.jsonl"
            mock_file.write_text(json.dumps({"source": "USER", "content": "test"}) + "\n", encoding="utf-8")

            # Test delete_session_files
            ok, freed, msg = delete_session_files("mock_session_1", folder_path=str(mock_sess), file_path=str(mock_file), custom_dirs=[str(mock_brain)])
            self.assertTrue(ok)
            self.assertFalse(mock_sess.exists())

    def test_prune_by_age_and_keep_latest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_brain = Path(tmpdir) / "brain"
            for i in range(5):
                sess_dir = mock_brain / f"sess_{i}" / ".system_generated" / "logs"
                sess_dir.mkdir(parents=True, exist_ok=True)
                f = sess_dir / "transcript_full.jsonl"
                f.write_text(json.dumps({"source": "USER", "content": f"msg {i}"}) + "\n", encoding="utf-8")

            # Test age pruning with 0 results for huge threshold
            res = prune_sessions_by_age(3650, keep_active=True, delete_disk_files=False)
            self.assertEqual(res["deleted_count"], 0)

    def test_sync_and_prune_orphaned_sessions(self):
        # Inject phantom session into in-memory ledger
        phantom_id = "phantom_session_xyz_99999"
        ledger.sessions[phantom_id] = {
            "session_id": phantom_id,
            "account": "user@example.com",
            "prompt": 500,
            "thinking": 200,
            "candidates": 300,
            "total": 1000,
            "folder": "/non/existent/path/xyz",
            "file": "/non/existent/path/xyz/log.jsonl",
            "records": []
        }
        self.assertIn(phantom_id, ledger.sessions)

        # Run sync and verify phantom session is pruned
        res = sync_and_prune_orphaned_sessions()
        self.assertGreaterEqual(res["orphaned_count"], 1)
        self.assertIn(phantom_id, res["orphaned_ids"])
        self.assertNotIn(phantom_id, ledger.sessions)

    def test_open_session_folder_validation(self):
        ok, msg = open_session_folder("..")
        self.assertFalse(ok)
        self.assertIn("Invalid", msg)

        ok, msg = open_session_folder("non_existent_session_id_404")
        self.assertFalse(ok)
        self.assertIn("not found", msg)

    def test_delete_session_files_security_and_modes(self):
        # 1. Path traversal attacks rejected
        ok, freed, msg = delete_session_files("..")
        self.assertFalse(ok)
        self.assertIn("Invalid session ID", msg)

        ok, freed, msg = delete_session_files("/")
        self.assertFalse(ok)
        self.assertIn("Invalid session ID", msg)

        ok, freed, msg = delete_session_files("")
        self.assertFalse(ok)

        # 2. delete_disk_files=False removes from ledger/cache but leaves disk intact
        with tempfile.TemporaryDirectory() as tmpdir:
            sess_dir = Path(tmpdir) / "brain" / "keep_disk_sess" / ".system_generated" / "logs"
            sess_dir.mkdir(parents=True, exist_ok=True)
            log_f = sess_dir / "transcript_full.jsonl"
            log_f.write_text('{"source":"USER"}\n', encoding="utf-8")

            ledger.sessions["keep_disk_sess"] = {"session_id": "keep_disk_sess", "total": 100}
            ok, freed, msg = delete_session_files(
                "keep_disk_sess",
                folder_path=str(sess_dir),
                file_path=str(log_f),
                delete_disk_files=False
            )
            self.assertTrue(ok)
            self.assertIn("removed from ledger", msg)
            self.assertNotIn("keep_disk_sess", ledger.sessions)
            self.assertTrue(log_f.exists())  # File still exists on disk

    def test_prune_sessions_keep_latest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Path(tmpdir) / "brain"
            mock_sessions = []
            for i in range(5):
                s_id = f"keep_latest_{i}"
                s_dir = brain / s_id / ".system_generated" / "logs"
                s_dir.mkdir(parents=True, exist_ok=True)
                f = s_dir / "transcript_full.jsonl"
                f.write_text('{"source":"USER"}\n', encoding="utf-8")
                mock_sessions.append({
                    "session_id": s_id,
                    "folder": s_dir,
                    "file": f,
                    "mtime": 1000.0 + i,
                    "last_active": None,
                })
            # Sort newest first
            mock_sessions.sort(key=lambda s: s["mtime"], reverse=True)

            with patch("core.cleaner.get_all_session_files", return_value=mock_sessions):
                # Keep latest 2 sessions, delete 3 older ones
                res = prune_sessions_keep_latest(n_latest=2, keep_active=False, delete_disk_files=True)
                self.assertEqual(res["deleted_count"], 3)
                self.assertEqual(len(res["deleted_ids"]), 3)

    def test_prune_empty_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Path(tmpdir) / "brain"
            # Session 0: active session (should NOT be pruned even if 0 tokens)
            dir0 = brain / "active_zero" / ".system_generated" / "logs"
            dir0.mkdir(parents=True, exist_ok=True)
            f0 = dir0 / "transcript_full.jsonl"
            f0.write_text('{"source":"USER"}\n', encoding="utf-8")

            # Session 1: empty / 0-byte
            dir1 = brain / "empty_sess" / ".system_generated" / "logs"
            dir1.mkdir(parents=True, exist_ok=True)
            f1 = dir1 / "transcript_full.jsonl"
            f1.write_text('', encoding="utf-8")

            mock_sessions = [
                {"session_id": "active_zero", "folder": dir0, "file": f0, "size": 100, "mtime": 2000.0},
                {"session_id": "empty_sess", "folder": dir1, "file": f1, "size": 0, "mtime": 1000.0},
            ]

            ledger.sessions["active_zero"] = {"session_id": "active_zero", "total": 0}
            ledger.sessions["empty_sess"] = {"session_id": "empty_sess", "total": 0}

            with patch("core.cleaner.get_all_session_files", return_value=mock_sessions):
                res = prune_empty_sessions(delete_disk_files=True)
                self.assertEqual(res["deleted_count"], 1)
                self.assertIn("empty_sess", res["deleted_ids"])
                self.assertNotIn("active_zero", res["deleted_ids"])

            # Cleanup
            ledger.remove_session("active_zero")
            ledger.remove_session("empty_sess")

    def test_prune_all_previous(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Path(tmpdir) / "brain"
            dir_act = brain / "sess_active" / ".system_generated" / "logs"
            dir_act.mkdir(parents=True, exist_ok=True)
            f_act = dir_act / "transcript_full.jsonl"
            f_act.write_text('{"source":"USER"}\n', encoding="utf-8")

            dir_old = brain / "sess_old" / ".system_generated" / "logs"
            dir_old.mkdir(parents=True, exist_ok=True)
            f_old = dir_old / "transcript_full.jsonl"
            f_old.write_text('{"source":"USER"}\n', encoding="utf-8")

            mock_sessions = [
                {"session_id": "sess_active", "folder": dir_act, "file": f_act, "mtime": 2000.0},
                {"session_id": "sess_old", "folder": dir_old, "file": f_old, "mtime": 1000.0},
            ]

            with patch("core.cleaner.get_all_session_files", return_value=mock_sessions):
                res = prune_all_previous(keep_active=True, delete_disk_files=True)
                self.assertEqual(res["deleted_count"], 1)
                self.assertIn("sess_old", res["deleted_ids"])
                self.assertNotIn("sess_active", res["deleted_ids"])

    def test_open_storage_folder(self):
        # 1. No brain dirs
        with patch("core.cleaner.find_all_brain_dirs", return_value=[]):
            ok, msg = open_storage_folder()
            self.assertFalse(ok)
            self.assertIn("No Antigravity storage", msg)

        # 2. Existing brain dir
        with tempfile.TemporaryDirectory() as tmpdir:
            b_dir = Path(tmpdir) / "brain"
            b_dir.mkdir()
            with patch("core.cleaner.find_all_brain_dirs", return_value=[b_dir]):
                with patch("subprocess.Popen") if os.name == "nt" else patch("os.system"):
                    ok, msg = open_storage_folder()
                    self.assertTrue(ok)
                    self.assertIn(str(b_dir), msg)

    def test_get_disk_usage_summary_synthetic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sess_dir = Path(tmpdir) / "brain" / "summary_test" / ".system_generated" / "logs"
            sess_dir.mkdir(parents=True, exist_ok=True)
            log_f = sess_dir / "transcript_full.jsonl"
            log_f.write_text('{"source":"USER"}\n', encoding="utf-8")

            mock_sessions = [
                {
                    "session_id": "summary_test",
                    "folder": sess_dir,
                    "file": log_f,
                    "size": 512,
                    "mtime": 1788000000.0,
                    "first_prompt": "Prompt for summary",
                    "last_active_str": "2026-08-30 12:00:00",
                }
            ]
            with patch("core.cleaner.get_all_session_files", return_value=mock_sessions):
                summary = get_disk_usage_summary()
                self.assertEqual(summary["total_sessions"], 1)
                self.assertGreater(summary["total_bytes"], 0)
                self.assertIn("B", summary["total_size_str"])
                self.assertEqual(len(summary["sessions"]), 1)
                self.assertEqual(summary["sessions"][0]["session_id"], "summary_test")


if __name__ == "__main__":
    unittest.main()
