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

from core.cleaner import (
    format_bytes,
    delete_session_files,
    prune_sessions_by_age,
    open_session_folder,
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


if __name__ == "__main__":
    unittest.main()
