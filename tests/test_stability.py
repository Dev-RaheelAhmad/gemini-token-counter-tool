import os
import sys
import unittest
import tempfile
import json
import shutil
import base64
import time
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from core.ledger import AccountLedger, ledger
from core.session_finder import (
    get_available_drives,
    get_wsl_distros,
    clear_wsl_cache,
    find_all_brain_dirs,
    get_all_session_files,
    get_brain_dirs_summary,
)
from core.account_manager import (
    decode_id_token_email,
    find_credential_files,
    get_all_google_accounts,
    has_auth_credentials_changed,
)
from core.cleaner import (
    get_disk_usage_summary,
    prune_sessions_keep_latest,
    prune_empty_sessions,
    prune_all_previous,
    open_storage_folder,
)
from core.engine import (
    parse_transcript_file_cached,
    get_single_session_report,
    get_all_sessions_report,
    get_active_account_report,
)
from core.watcher import SessionWatcher


class TestAdditionalCoverage(unittest.TestCase):
    def test_ledger_load_from_disk_bugfix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_ledger = AccountLedger()
            usage_file = Path(tmpdir) / "account_usage.json"
            test_ledger.ledger_file = usage_file
            # Simulate a persisted file with lifetime_tokens and NO account_breakdown/account_usage
            payload = {
                "database_meta": {"schema_version": 2},
                "sessions": {
                    "sess_test_load_bugfix": {
                        "account": "developer@company.org",
                        "title": "Bugfix test session",
                        "lifetime_tokens": {
                            "prompt": 120,
                            "thinking": 80,
                            "candidates": 200,
                            "total": 400
                        },
                        "records": [["2026-08-30T12:00:00Z", 120, 80, 200]]
                    }
                }
            }
            usage_file.write_text(json.dumps(payload), encoding="utf-8")
            test_ledger.sessions = {}
            test_ledger.load_from_disk()
            self.assertIn("sess_test_load_bugfix", test_ledger.sessions)
            entry = test_ledger.sessions["sess_test_load_bugfix"]
            self.assertEqual(entry["prompt"], 120)
            self.assertEqual(entry["thinking"], 80)
            self.assertEqual(entry["candidates"], 200)
            self.assertEqual(entry["total"], 400)
            self.assertIn("developer@company.org", entry["account_usage"])

    def test_session_finder_utilities(self):
        drives = get_available_drives()
        self.assertIsInstance(drives, list)

        distros = get_wsl_distros()
        self.assertIsInstance(distros, list)

        clear_wsl_cache()

        brain_dirs = find_all_brain_dirs()
        self.assertIsInstance(brain_dirs, list)

        sessions = get_all_session_files()
        self.assertIsInstance(sessions, list)

        summary = get_brain_dirs_summary()
        self.assertIsInstance(summary, list)

    def test_account_manager_helpers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            oauth_file = Path(tmpdir) / "oauth_creds.json"
            # Invalid or missing
            self.assertIsNone(decode_id_token_email(oauth_file))

            # Valid synthetic JWT
            header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').decode("utf-8").rstrip("=")
            payload = base64.urlsafe_b64encode(b'{"email":"developer@company.org"}').decode("utf-8").rstrip("=")
            fake_jwt = f"{header}.{payload}.signature"
            oauth_file.write_text(json.dumps({"id_token": fake_jwt}), encoding="utf-8")
            decoded_email = decode_id_token_email(oauth_file)
            self.assertEqual(decoded_email, "developer@company.org")

        files = find_credential_files()
        self.assertIn("google_accounts", files)
        self.assertIn("oauth_creds", files)

        all_acc = get_all_google_accounts()
        self.assertIn("active_account", all_acc)
        self.assertIn("old_accounts", all_acc)

        changed = has_auth_credentials_changed()
        self.assertIsInstance(changed, bool)

    def test_cleaner_utilities(self):
        summary = get_disk_usage_summary()
        self.assertIn("total_sessions", summary)
        self.assertIn("total_bytes", summary)

        # Test prune functions with mock data
        with tempfile.TemporaryDirectory() as tmpdir:
            res_latest = prune_sessions_keep_latest(100, keep_active=True, delete_disk_files=False)
            self.assertIn("deleted_count", res_latest)

            res_empty = prune_empty_sessions(delete_disk_files=False)
            self.assertIn("deleted_count", res_empty)

            res_prev = prune_all_previous(keep_active=True, delete_disk_files=False)
            self.assertIn("deleted_count", res_prev)

        # Storage folder finder
        ok, msg = open_storage_folder()
        self.assertIsInstance(ok, bool)

    def test_engine_cached_and_reports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs"
            log_dir.mkdir()
            log_file = log_dir / "transcript_full.jsonl"
            log_file.write_text(
                json.dumps({"source": "USER", "type": "USER_INPUT", "content": "How to optimize code?", "created_at": "2026-08-30T10:00:00Z"}) + "\n" +
                json.dumps({"source": "MODEL", "type": "PLANNER_RESPONSE", "thinking": "Let me analyze...", "content": "Optimization tips...", "created_at": "2026-08-30T10:00:05Z"}) + "\n",
                encoding="utf-8"
            )
            stats, records, fp = parse_transcript_file_cached(log_file)
            self.assertGreater(stats["prompt"], 0)
            self.assertGreater(stats["thinking"], 0)
            self.assertGreater(stats["candidates"], 0)
            self.assertTrue("How to optimize code" in fp)

            mock_session = {
                "session_id": "test_engine_sess_001",
                "file": log_file,
                "folder": log_dir,
                "mtime": log_file.stat().st_mtime,
                "size": log_file.stat().st_size,
                "last_active_str": "2026-08-30 10:00:05"
            }
            s_rep = get_single_session_report(mock_session, account_email="developer@company.org")
            self.assertEqual(s_rep["session_id"], "test_engine_sess_001")
            self.assertGreater(s_rep["total"], 0)

            all_rep = get_all_sessions_report([mock_session])
            self.assertTrue(all_rep["is_all"])
            self.assertGreater(all_rep["total"], 0)

            act_rep = get_active_account_report("developer@company.org", sessions=[mock_session])
            self.assertGreaterEqual(act_rep["total"], 0)

            # Cleanup from singleton ledger
            ledger.remove_session("test_engine_sess_001")


class TestContinuousLongevityAndStability(unittest.TestCase):
    """Tests guaranteeing 24/7 continuous runtime stability, memory integrity, and reload idempotency."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.ledger_file = Path(self.tmp_dir) / "account_usage.json"
        self.log_file = Path(self.tmp_dir) / "account_ledger.jsonl"
        self.test_ledger = AccountLedger(ledger_file=self.ledger_file, ledger_log_file=self.log_file)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_continuous_polling_simulation_no_record_duplication(self):
        """Simulates 100 continuous background polling cycles to guarantee zero token multiplication or list leaks."""
        sid = "sess_longevity_001"
        account = "user@example.com"
        now = datetime.now(timezone.utc)

        # Initial turn
        line_records = [
            (now - timedelta(minutes=10), 100, 50, 25),
            (now - timedelta(minutes=5), 200, 100, 50),
        ]
        stats = {"prompt": 300, "thinking": 150, "candidates": 75, "total": 525}

        # First update
        self.test_ledger.update_session(
            session_id=sid,
            account_email=account,
            stats=stats,
            line_records=line_records,
            first_prompt="Initial prompt",
            last_active="2026-09-01 12:00:00"
        )

        sess = self.test_ledger.sessions[sid]
        self.assertEqual(sess["total"], 525)
        self.assertEqual(len(sess["records"]), 2)
        self.assertEqual(len(sess["account_usage"][account]["records"]), 2)

        # Simulate 50 polling cycles with identical data (session active but idle)
        for _ in range(50):
            self.test_ledger.update_session(
                session_id=sid,
                account_email=account,
                stats=stats,
                line_records=line_records,
                first_prompt="Initial prompt",
                last_active="2026-09-01 12:00:00"
            )

        sess = self.test_ledger.sessions[sid]
        self.assertEqual(sess["total"], 525)
        self.assertEqual(len(sess["records"]), 2)
        self.assertEqual(len(sess["account_usage"][account]["records"]), 2)
        self.assertEqual(sess["account_usage"][account]["total"], 525)

        # Simulate 50 polling cycles with a new turn arriving (streaming tokens)
        line_records_turn3 = list(line_records) + [
            (now, 150, 75, 40)
        ]
        stats_turn3 = {"prompt": 450, "thinking": 225, "candidates": 115, "total": 790}

        for _ in range(50):
            self.test_ledger.update_session(
                session_id=sid,
                account_email=account,
                stats=stats_turn3,
                line_records=line_records_turn3,
                first_prompt="Initial prompt",
                last_active="2026-09-01 12:05:00"
            )

        sess = self.test_ledger.sessions[sid]
        self.assertEqual(sess["total"], 790)
        self.assertEqual(len(sess["records"]), 3)
        self.assertEqual(len(sess["account_usage"][account]["records"]), 3)
        self.assertEqual(sess["account_usage"][account]["total"], 790)

    def test_load_from_disk_idempotency(self):
        """Verifies that repeatedly loading ledger from disk never double-counts or inflates totals."""
        sid = "sess_idempotency_001"
        account = "developer@example.org"
        now = datetime.now(timezone.utc)

        line_records = [
            (now - timedelta(minutes=2), 500, 200, 100)
        ]
        stats = {"prompt": 500, "thinking": 200, "candidates": 100, "total": 800}

        self.test_ledger.update_session(
            session_id=sid,
            account_email=account,
            stats=stats,
            line_records=line_records,
            first_prompt="Testing idempotency"
        )
        self.test_ledger.flush_to_disk(force=True)

        # Confirm files exist on disk
        self.assertTrue(self.ledger_file.exists())
        self.assertTrue(self.log_file.exists())

        initial_total = self.test_ledger.sessions[sid]["total"]
        self.assertEqual(initial_total, 800)

        # Reload from disk 10 times consecutively
        for i in range(10):
            fresh_ledger = AccountLedger(ledger_file=self.ledger_file, ledger_log_file=self.log_file)
            self.assertIn(sid, fresh_ledger.sessions)
            sess = fresh_ledger.sessions[sid]
            self.assertEqual(sess["total"], 800, f"Failed on reload iteration {i+1}")
            self.assertEqual(sess["prompt"], 500)
            self.assertEqual(sess["thinking"], 200)
            self.assertEqual(sess["candidates"], 100)
            self.assertEqual(len(sess["records"]), 1)
            self.assertEqual(sess["account_usage"][account]["total"], 800)
            self.assertEqual(len(sess["account_usage"][account]["records"]), 1)

    def test_watcher_wake_event_and_force_refresh(self):
        """Verifies that SessionWatcher force_refresh triggers wake event without thread thrashing."""
        watcher = SessionWatcher()
        self.assertFalse(watcher._force_requested)
        watcher.force_refresh()
        self.assertTrue(watcher._force_requested)

    def test_watcher_mtime_cache_pruning(self):
        """Verifies that deleted paths are pruned from watcher mtime caches."""
        watcher = SessionWatcher()
        fake_deleted_dir = "C:\\fake\\nonexistent\\brain"
        watcher._last_brain_mtimes[fake_deleted_dir] = 12345.0
        watcher._last_realtime_mtimes[fake_deleted_dir] = 12345.0

        watcher._poll(force=True)
        self.assertNotIn(fake_deleted_dir, watcher._last_brain_mtimes)
        self.assertNotIn(fake_deleted_dir, watcher._last_realtime_mtimes)


class TestLongRunningStabilityAndLeakPrevention(unittest.TestCase):
    """Unit tests ensuring 0% CPU leaks, memory stability, and freeze prevention over long runtimes."""

    def test_ledger_log_rotation_truncates_at_threshold(self):
        """Verifies that _rotate_log_if_needed uses ledger_log_file and truncates when >5000 lines."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            test_ledger_file = td / "test_usage.json"
            test_log_file = td / "test_ledger.jsonl"

            # Create 5,200 lines in test_log_file
            lines = [f'{{"event": "token_update", "line": {i}}}\n' for i in range(5200)]
            test_log_file.write_text("".join(lines), encoding="utf-8")

            ledger_inst = AccountLedger(ledger_file=test_ledger_file, ledger_log_file=test_log_file)
            self.assertTrue(hasattr(ledger_inst, "ledger_log_file"))
            self.assertTrue(hasattr(ledger_inst, "log_file"))

            # Execute rotation
            ledger_inst._rotate_log_if_needed()

            # Confirm file has been truncated to 2,500 lines
            remaining_lines = test_log_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(remaining_lines), 2500)
            self.assertIn('"line": 5199', remaining_lines[-1])

    def test_ledger_flush_to_disk_fast_snapshot(self):
        """Verifies that flush_to_disk uses shallow dictionary snapshotting and produces valid output."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            test_ledger_file = td / "test_usage.json"
            test_log_file = td / "test_ledger.jsonl"

            ledger_inst = AccountLedger(ledger_file=test_ledger_file, ledger_log_file=test_log_file)

            # Insert test sessions
            for i in range(25):
                sid = f"bench_session_{i:03d}"
                ledger_inst.update_session(
                    session_id=sid,
                    account_email="developer@company.org",
                    stats={"prompt": 100 * (i + 1), "thinking": 50, "candidates": 75, "total": 225},
                    line_records=[(datetime.now(timezone.utc), 100, 50, 75)]
                )

            self.assertTrue(ledger_inst._is_dirty)
            # Perform flush
            ledger_inst.flush_to_disk(force=True)
            self.assertFalse(ledger_inst._is_dirty)
            self.assertTrue(test_ledger_file.exists())

            # Read back and verify valid JSON
            content = json.loads(test_ledger_file.read_text(encoding="utf-8"))
            self.assertIn("bench_session_000", content.get("sessions", {}))
            self.assertIn("bench_session_024", content.get("sessions", {}))

    def test_analytics_dialog_active_sid_in_memory(self):
        """Verifies that AnalyticsDialog resolves active_sid from master memory without calling get_all_session_files."""
        from gui.analytics_dialog import AnalyticsDialog
        dialog = AnalyticsDialog.__new__(AnalyticsDialog)

        # Mock master with watcher
        mock_watcher = type("MockWatcher", (), {
            "latest_sessions": [{"session_id": "sid_mem_fast_999", "file": "dummy.jsonl"}],
            "_last_sessions_fingerprint": ("dummy", 123)
        })()
        dialog.master = type("MockMaster", (), {"watcher": mock_watcher})()
        dialog.target_account = "all"
        dialog.target_session_id = None
        dialog.selected_timeframe = "5h"
        dialog.chart = type("MockChart", (), {"set_dual_records": lambda *args, **kwargs: None})()
        dialog._render_table_rows = lambda: None
        dialog._update_summary_card = lambda: None

        mock_card = type("MockCard", (), {"update_values": lambda *args, **kwargs: None})()
        dialog.card_prompt = mock_card
        dialog.card_thinking = mock_card
        dialog.card_candidates = mock_card
        dialog.card_total = mock_card

        # Track calls to get_all_session_files
        with patch("gui.analytics_dialog.get_all_session_files") as mock_get_files:
            dialog._load_data()
            mock_get_files.assert_not_called()

    def test_session_table_in_place_row_updates(self):
        """Verifies that SessionTable reuses existing row widgets in-place when session IDs match."""
        from gui.components.session_table import SessionTable
        table = SessionTable.__new__(SessionTable)
        table.current_page = 1
        table.page_size = 10
        table.search_query = ""
        table.search_var = type("MockVar", (), {"get": lambda *args, **kwargs: ""})()
        table.selected_session_id = "bench_sid_001"
        table.is_all_mode = False
        table.sort_key = "mtime"
        table.sort_reverse = True
        table.sessions = [
            {"session_id": "bench_sid_001", "mtime": 1000.0, "size": 2048, "first_prompt": "Hello", "tokens": 500, "account": "user@example.com"},
            {"session_id": "bench_sid_002", "mtime": 900.0, "size": 1024, "first_prompt": "World", "tokens": 200, "account": "user@example.com"}
        ]

        # Mock widgets for 2 rows
        row_1 = type("MockRow", (), {"configure": MagicMock(), "winfo_exists": lambda: True})()
        id_lbl_1 = type("MockLbl", (), {"configure": MagicMock()})()
        prompt_lbl_1 = type("MockLbl", (), {"configure": MagicMock()})()
        time_lbl_1 = type("MockLbl", (), {"configure": MagicMock()})()
        tok_badge_1 = type("MockLbl", (), {"configure": MagicMock()})()
        size_badge_1 = type("MockLbl", (), {"configure": MagicMock()})()
        dot_lbl_1 = type("MockLbl", (), {"configure": MagicMock()})()

        row_2 = type("MockRow", (), {"configure": MagicMock(), "winfo_exists": lambda: True})()
        id_lbl_2 = type("MockLbl", (), {"configure": MagicMock()})()
        prompt_lbl_2 = type("MockLbl", (), {"configure": MagicMock()})()
        time_lbl_2 = type("MockLbl", (), {"configure": MagicMock()})()
        tok_badge_2 = type("MockLbl", (), {"configure": MagicMock()})()
        size_badge_2 = type("MockLbl", (), {"configure": MagicMock()})()
        dot_lbl_2 = type("MockLbl", (), {"configure": MagicMock()})()

        table.row_frames = [
            ("bench_sid_001", row_1, id_lbl_1, prompt_lbl_1, time_lbl_1, tok_badge_1, size_badge_1, dot_lbl_1),
            ("bench_sid_002", row_2, id_lbl_2, prompt_lbl_2, time_lbl_2, tok_badge_2, size_badge_2, dot_lbl_2)
        ]
        table._update_pagination_bar = MagicMock()
        table._update_row_selection_styles = MagicMock()
        table.scroll_frame = type("MockScroll", (), {"winfo_children": MagicMock(return_value=[])})()

        # Update tokens on bench_sid_001
        table.sessions[0]["tokens"] = 1500
        table._last_rendered_data_fp = None  # Force update check

        table._filter_sessions(reset_page=False)

        # Confirm tok_badge_1 was reconfigured in place without destroying rows
        tok_badge_1.configure.assert_called()
        table.scroll_frame.winfo_children.assert_not_called()

    def test_update_watcher_activity_zoomed_and_minimized_states(self):
        """Verifies that _update_watcher_activity handles zoomed/normal as active, and iconic/withdrawn as paused."""
        from gui.app import GeminiTokenCounterApp
        app = GeminiTokenCounterApp.__new__(GeminiTokenCounterApp)
        app.mini_hud_window = None
        app.analytics_dialog_window = None
        app.cleaner_dialog_window = None
        app.settings_dialog_window = None

        mock_watcher = type("MockWatcher", (), {
            "_paused": False,
            "is_paused": lambda self: self._paused,
            "pause": lambda self: setattr(self, "_paused", True),
            "resume": lambda self: setattr(self, "_paused", False),
        })()
        app.watcher = mock_watcher

        # State 1: Normal and viewable -> watcher should NOT be paused
        app.winfo_exists = lambda: True
        app.state = lambda: "normal"
        app.winfo_viewable = lambda: 1
        app.winfo_children = lambda: []
        app._update_watcher_activity()
        self.assertFalse(mock_watcher.is_paused())

        # State 2: Zoomed (Maximized on Windows) -> watcher should NOT be paused
        app.state = lambda: "zoomed"
        app.winfo_viewable = lambda: 1
        app._update_watcher_activity()
        self.assertFalse(mock_watcher.is_paused())

        # State 3: Iconic (Minimized to taskbar) -> watcher SHOULD be paused (0% CPU)
        app.state = lambda: "iconic"
        app.winfo_viewable = lambda: 0
        app._update_watcher_activity()
        self.assertTrue(mock_watcher.is_paused())

        # State 4: Restored back from minimized -> watcher SHOULD resume immediately
        app.state = lambda: "normal"
        app.winfo_viewable = lambda: 1
        app._update_watcher_activity()
        self.assertFalse(mock_watcher.is_paused())

        # State 5: Main window is hidden in tray, but MiniHUD / Floating Bubble is active on desktop
        app.state = lambda *a: "withdrawn"
        app.winfo_viewable = lambda *a: 0
        mock_hud = type("MockHUD", (), {
            "winfo_exists": lambda *a: True,
            "state": lambda *a: "normal",
            "winfo_viewable": lambda *a: 1
        })()
        app.mini_hud_window = mock_hud
        app._update_watcher_activity()
        self.assertFalse(mock_watcher.is_paused())

        # State 6: MiniHUD is closed (withdrawn), so all windows are hidden -> watcher SHOULD pause
        mock_hud.state = lambda *a: "withdrawn"
        mock_hud.winfo_viewable = lambda *a: 0
        app._update_watcher_activity()
        self.assertTrue(mock_watcher.is_paused())

        # State 7: Main window hidden, MiniHUD hidden, but a child dialog is active on desktop
        import customtkinter as ctk
        mock_child = ctk.CTkToplevel.__new__(ctk.CTkToplevel)
        mock_child.winfo_exists = lambda *a: True
        mock_child.state = lambda *a: "normal"
        mock_child.winfo_viewable = lambda *a: 1
        app.winfo_children = lambda *a: [mock_child]
        app._update_watcher_activity()
        self.assertFalse(mock_watcher.is_paused())

    def test_watcher_periodic_countdown_refresh_when_visible(self):
        """Verifies that watcher polls and refreshes sliding window countdowns every 30s when visible."""
        from core.watcher import SessionWatcher
        watcher = SessionWatcher.__new__(SessionWatcher)
        watcher._paused = False
        watcher._poll_lock = threading.Lock()
        watcher._lock = threading.Lock()
        watcher._selected_session_id = None
        watcher._mode_all = False
        watcher._last_sessions_fingerprint = ()
        watcher._last_brain_mtimes = {}
        watcher._last_realtime_mtimes = {}
        watcher._last_full_scan_time = time.time()
        watcher._last_report_time = time.time() - 35.0  # 35s ago (>30s due)
        watcher.latest_account_report = {"some": "data"}
        watcher.latest_sessions = [{"session_id": "test_sid", "file": "dummy", "mtime": 100.0, "size": 10}]
        watcher.on_update_callback = None

        with patch("core.watcher.get_all_session_files", return_value=watcher.latest_sessions), \
             patch("core.watcher.parse_transcript_file_cached", return_value=({"prompt": 1, "thinking": 1, "candidates": 1}, [], "test")), \
             patch("core.session_finder.find_all_brain_dirs", return_value=[]), \
             patch("core.account_manager.has_auth_credentials_changed", return_value=False):
            watcher._poll(force=False)
            self.assertAlmostEqual(watcher._last_report_time, time.time(), delta=2.0)

    def test_ghost_session_resurrection_prevention(self):
        """Verifies that watcher does not resurrect deleted sessions into ledger if transcript file is gone."""
        from core.watcher import SessionWatcher
        from core.ledger import AccountLedger
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            log_file = tmp_path / "ledger.jsonl"
            ledger_file = tmp_path / "usage.json"
            test_ledger = AccountLedger(ledger_file=ledger_file, ledger_log_file=log_file)
            test_ledger.sessions["ghost_sid"] = {"total": 500, "session_id": "ghost_sid"}

            watcher = SessionWatcher.__new__(SessionWatcher)
            watcher._paused = False
            watcher._poll_lock = threading.Lock()
            watcher._lock = threading.Lock()
            watcher._selected_session_id = None
            watcher._mode_all = False
            watcher._last_sessions_fingerprint = ()
            watcher._last_brain_mtimes = {}
            watcher._last_realtime_mtimes = {}
            watcher._last_full_scan_time = time.time()
            watcher._last_report_time = time.time()
            watcher.latest_account_report = None
            non_existent_file = tmp_path / "deleted_session" / "transcript.jsonl"
            watcher.latest_sessions = [{"session_id": "ghost_sid", "file": non_existent_file, "mtime": 100.0, "size": 10}]
            watcher.on_update_callback = None

            with patch("core.watcher.get_all_session_files", return_value=watcher.latest_sessions), \
                 patch("core.ledger.ledger", test_ledger), \
                 patch("core.session_finder.find_all_brain_dirs", return_value=[]), \
                 patch("core.account_manager.has_auth_credentials_changed", return_value=False):
                watcher._poll(force=True)
                self.assertNotIn("ghost_sid", test_ledger.sessions)
                self.assertEqual(len(watcher.latest_sessions), 0)

    def test_batch_cleaner_single_flush(self):
        """Verifies that prune_sessions_keep_latest only flushes ledger to disk once at the end."""
        from core.cleaner import prune_sessions_keep_latest
        from core.ledger import ledger

        mock_sessions = [
            {"session_id": f"sid_{i}", "folder": f"/dummy/{i}", "file": f"/dummy/{i}/t.jsonl", "mtime": float(i)}
            for i in range(10)
        ]
        with patch("core.cleaner.get_all_session_files", return_value=mock_sessions), \
             patch("core.cleaner.delete_session_files", return_value=(True, 100, "deleted")) as mock_del, \
             patch.object(ledger, "flush_to_disk") as mock_flush:
            res = prune_sessions_keep_latest(n_latest=3, keep_active=False, delete_disk_files=False)
            self.assertEqual(res["deleted_count"], 7)
            for call in mock_del.call_args_list:
                self.assertFalse(call.kwargs.get("flush", True))
            self.assertEqual(mock_flush.call_count, 1)

    def test_realtime_quota_30s_cache_hit(self):
        """Verifies that load_all_realtime_quotas caches within 30 seconds for live datetime lookups."""
        import core.realtime_quota as rq
        rq._CACHED_REALTIME_QUOTAS = {"user@example.com": {"email": "user@example.com", "total": 100}}
        rq._LAST_REALTIME_QUOTAS_TIME = time.time()

        now_utc = datetime.now(timezone.utc)
        quotas = rq.load_all_realtime_quotas(ref_time=now_utc, force_refresh=False)
        self.assertEqual(quotas, rq._CACHED_REALTIME_QUOTAS)

    def test_context_menu_destroyed_on_reopen(self):
        """Verifies that SessionTable destroys any prior context menu before allocating a new one."""
        from gui.components.session_table import SessionTable
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            table = SessionTable(root, on_select_session=lambda sid, is_all: None)
            old_menu = tk.Menu(table, tearoff=0)
            table._active_context_menu = old_menu

            with patch("tkinter.Menu.tk_popup"), patch("tkinter.Menu.grab_release"):
                fake_event = type("Event", (), {"x_root": 100, "y_root": 100})()
                table._show_context_menu(fake_event, {"session_id": "test_s", "folder": ""})

                self.assertNotEqual(table._active_context_menu, old_menu)
                table.destroy()
                self.assertIsNone(table._active_context_menu)
        finally:
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()

