import os
import sys
import time
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from core.session_finder import (
    find_all_brain_dirs,
    get_all_session_files,
    get_brain_dirs_summary,
    clear_brain_dirs_cache,
    clear_wsl_cache,
    get_wsl_distros,
    get_available_drives,
)


class TestSessionFinder(unittest.TestCase):
    def setUp(self):
        clear_brain_dirs_cache()
        clear_wsl_cache()

    def tearDown(self):
        clear_brain_dirs_cache()
        clear_wsl_cache()

    def test_find_all_brain_dirs_custom_and_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom1 = Path(tmpdir) / "custom_brain_1"
            custom1.mkdir()
            custom2 = Path(tmpdir) / "custom_brain_2"
            custom2.mkdir()
            non_existent = Path(tmpdir) / "non_existent_folder"

            # Fresh scan
            dirs = find_all_brain_dirs(custom_dirs=[str(custom1), str(custom2), str(non_existent)], force_refresh=True)
            dir_strs = [str(d) for d in dirs]
            self.assertIn(str(custom1), dir_strs)
            self.assertIn(str(custom2), dir_strs)
            self.assertNotIn(str(non_existent), dir_strs)

            # Caching check: without force_refresh, returns cached list
            cached_dirs = find_all_brain_dirs(custom_dirs=[str(custom1), str(custom2)], force_refresh=False)
            self.assertEqual(len(cached_dirs), len(dirs))

            # Invalidate cache
            clear_brain_dirs_cache()

    def test_session_discovery_precedence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Path(tmpdir) / "brain"
            sess_dir = brain / "sess-uuid-precedence" / ".system_generated" / "logs"
            sess_dir.mkdir(parents=True, exist_ok=True)

            file_full = sess_dir / "transcript_full.jsonl"
            file_full.write_text('{"type": "USER_INPUT", "content": "Full transcript"}\n', encoding="utf-8")

            file_compact = sess_dir / "transcript.jsonl"
            file_compact.write_text('{"type": "USER_INPUT", "content": "Compact transcript"}\n', encoding="utf-8")

            with patch("core.session_finder.find_all_brain_dirs", return_value=[brain]):
                sessions = get_all_session_files()
                self.assertEqual(len(sessions), 1)
                sess = sessions[0]
                self.assertEqual(sess["session_id"], "sess-uuid-precedence")
                # transcript_full.jsonl must take precedence over transcript.jsonl
                self.assertEqual(sess["file"].name, "transcript_full.jsonl")

    def test_session_discovery_fallback_to_compact_transcript(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Path(tmpdir) / "brain"
            sess_dir = brain / "sess-uuid-compact" / ".system_generated" / "logs"
            sess_dir.mkdir(parents=True, exist_ok=True)

            file_compact = sess_dir / "transcript.jsonl"
            file_compact.write_text('{"type": "USER_INPUT", "content": "Compact only"}\n', encoding="utf-8")

            with patch("core.session_finder.find_all_brain_dirs", return_value=[brain]):
                sessions = get_all_session_files()
                self.assertEqual(len(sessions), 1)
                self.assertEqual(sessions[0]["session_id"], "sess-uuid-compact")
                self.assertEqual(sessions[0]["file"].name, "transcript.jsonl")

    def test_chunks_directory_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Path(tmpdir) / "brain"
            sess_dir = brain / "sess-uuid-main" / ".system_generated" / "logs"
            sess_dir.mkdir(parents=True, exist_ok=True)
            (sess_dir / "transcript_full.jsonl").write_text('{"source": "USER"}\n', encoding="utf-8")

            # Create chunks subfolder with a fake transcript
            chunks_dir = sess_dir / "chunks"
            chunks_dir.mkdir(parents=True, exist_ok=True)
            (chunks_dir / "transcript_full.jsonl").write_text('{"source": "CHUNK"}\n', encoding="utf-8")

            with patch("core.session_finder.find_all_brain_dirs", return_value=[brain]):
                sessions = get_all_session_files()
                # Only the main session should be discovered, not the chunks directory
                self.assertEqual(len(sessions), 1)
                self.assertEqual(sessions[0]["session_id"], "sess-uuid-main")

    def test_session_deduplication_by_mtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            brain1 = Path(tmpdir) / "brain1"
            brain2 = Path(tmpdir) / "brain2"

            sess1 = brain1 / "duplicate-session" / ".system_generated" / "logs"
            sess2 = brain2 / "duplicate-session" / ".system_generated" / "logs"
            sess1.mkdir(parents=True, exist_ok=True)
            sess2.mkdir(parents=True, exist_ok=True)

            f1 = sess1 / "transcript_full.jsonl"
            f2 = sess2 / "transcript_full.jsonl"
            f1.write_text('{"source": "USER", "content": "older"}\n', encoding="utf-8")
            f2.write_text('{"source": "USER", "content": "newer"}\n', encoding="utf-8")

            # Set mtimes explicitly: f1 = 1000s, f2 = 2000s
            os.utime(str(f1), (1000.0, 1000.0))
            os.utime(str(f2), (2000.0, 2000.0))

            with patch("core.session_finder.find_all_brain_dirs", return_value=[brain1, brain2]):
                sessions = get_all_session_files()
                # Deduplicated: only 1 session returned
                self.assertEqual(len(sessions), 1)
                # The newer file in brain2 should be chosen
                self.assertEqual(sessions[0]["mtime"], 2000.0)
                self.assertEqual(sessions[0]["brain_dir"], brain2)

    def test_get_brain_dirs_summary_and_classification(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Path(tmpdir) / "brain"
            sess_dir = brain / "sess-summary" / ".system_generated" / "logs"
            sess_dir.mkdir(parents=True, exist_ok=True)
            (sess_dir / "transcript_full.jsonl").write_text('{"source": "USER"}\n', encoding="utf-8")

            summary = get_brain_dirs_summary(custom_dirs=[str(brain)])
            self.assertIsInstance(summary, list)
            match = next((item for item in summary if str(brain) in item["path"]), None)
            self.assertIsNotNone(match)
            self.assertTrue(match["is_custom"])
            self.assertEqual(match["session_count"], 1)
            self.assertTrue(match["exists"])

    def test_clear_wsl_and_drives_cache(self):
        drives = get_available_drives()
        self.assertIsInstance(drives, list)

        distros = get_wsl_distros(force_refresh=True)
        self.assertIsInstance(distros, list)

        clear_wsl_cache()
        # Ensure re-calling get_wsl_distros succeeds without error
        distros2 = get_wsl_distros()
        self.assertIsInstance(distros2, list)


if __name__ == "__main__":
    unittest.main()
