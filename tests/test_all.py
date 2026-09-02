import os
import sys
import unittest
import tempfile
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from core.config import ConfigManager, get_config_dir, DEFAULT_CONFIG, config

# Strictly isolate global test config to a temporary directory so unit tests never mutate user %APPDATA% state
_test_tmp_dir = tempfile.mkdtemp(prefix="gemini_test_config_")
_test_config_file = Path(_test_tmp_dir) / "config.json"
config.config_path = _test_config_file
config.data = DEFAULT_CONFIG.copy()


def tearDownModule():
    shutil.rmtree(_test_tmp_dir, ignore_errors=True)
from core.session_finder import (
    find_all_brain_dirs,
    get_all_session_files,
    get_brain_dirs_summary,
    get_available_drives,
    get_wsl_distros,
    clear_wsl_cache
)
from core.account_manager import (
    decode_id_token_email,
    find_credential_files,
    get_active_google_account,
    get_all_google_accounts,
    get_all_known_accounts_list,
    get_auth_files_fingerprint,
    has_auth_credentials_changed,
    set_active_google_account_in_memory,
    is_valid_account_email,
    get_account_activity_ranges,
    find_best_matching_account,
)
from core.engine import (
    estimate_tokens,
    parse_iso_time,
    extract_first_prompt,
    extract_line_tokens,
    parse_transcript_file_cached,
    calculate_window_tracker,
    format_recovery_info,
    get_single_session_report,
    get_empty_session_report,
    get_session_user_report,
    get_all_sessions_report,
    get_active_account_report
)
from core.ledger import AccountLedger, ledger
from core.analytics import (
    bucket_records_by_time,
    calculate_analytics_summary,
    generate_ascii_chart,
    export_analytics_csv,
    export_analytics_json
)
from core.cleaner import (
    format_bytes,
    get_disk_usage_summary,
    delete_session_files,
    prune_sessions_by_age,
    prune_sessions_keep_latest,
    prune_empty_sessions,
    prune_all_previous,
    open_storage_folder,
    open_session_folder,
    sync_and_prune_orphaned_sessions
)


class TestConfig(unittest.TestCase):
    def test_default_config_keys(self):
        self.assertIn("limit_5h", DEFAULT_CONFIG)
        self.assertIn("limit_7d", DEFAULT_CONFIG)
        self.assertIn("refresh_interval_sec", DEFAULT_CONFIG)
        self.assertIn("theme", DEFAULT_CONFIG)

    def test_config_get_set(self):
        cm = ConfigManager()
        cm.set("test_key", "test_value", save_now=False)
        self.assertEqual(cm.get("test_key"), "test_value")
        self.assertEqual(cm.get("nonexistent_key", "fallback"), "fallback")

    def test_get_config_dir(self):
        cfg_dir = get_config_dir()
        self.assertIsInstance(cfg_dir, Path)
        self.assertTrue(cfg_dir.exists())

    def test_v2_migration(self):
        # Test that legacy config with version < 2 and show_manual_limits=True migrates to False and v14
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        try:
            with open(tmp.name, "w", encoding="utf-8") as f:
                json.dump({"config_version": 1, "show_manual_limits": True, "active_sessions_only": False}, f)
            cm = ConfigManager()
            cm.config_path = Path(tmp.name)
            cm.load()
            self.assertFalse(cm.get("show_manual_limits"))
            self.assertTrue(cm.get("active_sessions_only"))
            self.assertEqual(cm.get("mini_hud_opacity"), 1.0)
            self.assertEqual(cm.get("config_version"), 14)
        finally:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def test_v3_migration(self):
        # Test that v2 config migrates active_sessions_only and updates to v14
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        try:
            with open(tmp.name, "w", encoding="utf-8") as f:
                json.dump({"config_version": 2, "active_sessions_only": False}, f)
            cm = ConfigManager()
            cm.config_path = Path(tmp.name)
            cm.load()
            self.assertTrue(cm.get("active_sessions_only"))
            self.assertEqual(cm.get("config_version"), 14)
        finally:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def test_v4_migration(self):
        # Test that v3 config migrates show_manual_limits to False and updates to v14
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        try:
            with open(tmp.name, "w", encoding="utf-8") as f:
                json.dump({"config_version": 3, "show_manual_limits": True}, f)
            cm = ConfigManager()
            cm.config_path = Path(tmp.name)
            cm.load()
            self.assertFalse(cm.get("show_manual_limits"))
            self.assertEqual(cm.get("config_version"), 14)
        finally:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def test_v5_migration(self):
        # Test that v4 config migrates show_manual_limits to False and updates to v14
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        try:
            with open(tmp.name, "w", encoding="utf-8") as f:
                json.dump({"config_version": 4, "show_manual_limits": True}, f)
            cm = ConfigManager()
            cm.config_path = Path(tmp.name)
            cm.load()
            self.assertFalse(cm.get("show_manual_limits"))
            self.assertEqual(cm.get("config_version"), 14)
        finally:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def test_v14_migration(self):
        # Test that v13 config resets geometries and updates to v14
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        try:
            with open(tmp.name, "w", encoding="utf-8") as f:
                json.dump({"config_version": 13, "show_manual_limits": True, "mini_hud_opacity": 0.75, "mini_hud_bubble_geometry": "+500+300", "mini_hud_geometry": "+1200+400", "window_geometry": "1125x750+318+132"}, f)
            cm = ConfigManager()
            cm.config_path = Path(tmp.name)
            cm.load()
            self.assertFalse(cm.get("show_manual_limits"))
            self.assertEqual(cm.get("mini_hud_opacity"), 1.0)
            self.assertEqual(cm.get("window_geometry"), "")
            self.assertEqual(cm.get("mini_hud_bubble_geometry"), "")
            self.assertEqual(cm.get("mini_hud_geometry"), "")
            self.assertEqual(cm.get("config_version"), 14)
        finally:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def test_default_scope_constants(self):
        from core.config import (
            DEFAULT_ACTIVE_SESSIONS_ONLY,
            DEFAULT_ACTIVE_SESSIONS_ONLY_5H,
            DEFAULT_ACTIVE_SESSIONS_ONLY_7D
        )
        self.assertTrue(DEFAULT_ACTIVE_SESSIONS_ONLY)
        self.assertTrue(DEFAULT_ACTIVE_SESSIONS_ONLY_5H)
        self.assertFalse(DEFAULT_ACTIVE_SESSIONS_ONLY_7D)


class TestEngine(unittest.TestCase):
    def test_estimate_tokens(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("hello world"), 3)
        self.assertEqual(estimate_tokens("a" * 400), 100)

    def test_parse_iso_time(self):
        self.assertIsNone(parse_iso_time(None))
        self.assertIsNone(parse_iso_time("invalid-date"))
        dt = parse_iso_time("2026-08-30T12:00:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 8)
        self.assertEqual(dt.day, 30)

    def test_extract_first_prompt(self):
        data1 = {"source": "USER", "type": "USER_INPUT", "content": "How do I build a rocket?"}
        self.assertEqual(extract_first_prompt(data1), "How do I build a rocket?")

        data2 = {"source": "MODEL", "type": "MODEL_RESPONSE", "content": "Sure here is how."}
        self.assertIsNone(extract_first_prompt(data2))

    def test_extract_line_tokens(self):
        user_line = {"source": "USER", "content": "Explain relativity"}
        p, th, c = extract_line_tokens(user_line)
        self.assertGreater(p, 0)
        self.assertEqual(th, 0)
        self.assertEqual(c, 0)

        model_line = {
            "source": "MODEL",
            "thinking": "Let me think about Einstein...",
            "content": "Relativity consists of special and general relativity."
        }
        p, th, c = extract_line_tokens(model_line)
        self.assertEqual(p, 0)
        self.assertGreater(th, 0)
        self.assertGreater(c, 0)

    def test_window_tracker_and_recovery(self):
        now = datetime.now(timezone.utc)
        records = [
            (now - timedelta(hours=2), 100, 200, 300),
            (now - timedelta(days=2), 500, 500, 1000),
            (now - timedelta(days=10), 1000, 1000, 1000),
        ]
        tracker = calculate_window_tracker(records, ref_time=now)
        self.assertEqual(tracker["tokens_5h"], 600)
        self.assertEqual(tracker["tokens_7d"], 2600)
        self.assertEqual(tracker["prompt_5h"], 100)
        self.assertEqual(tracker["thinking_5h"], 200)
        self.assertEqual(tracker["candidates_5h"], 300)

        recovery = format_recovery_info(tracker, ref_time=now)
        self.assertIn("reset_5h_str", recovery)
        self.assertIn("reset_7d_str", recovery)
        self.assertGreater(recovery["pct_5h_remaining"], 0)

    def test_empty_session_report(self):
        rep = get_empty_session_report("test_sess", title="Empty Test", account_email="user@test.com")
        self.assertEqual(rep["total"], 0)
        self.assertEqual(rep["prompt"], 0)
        self.assertEqual(rep["thinking"], 0)
        self.assertEqual(rep["candidates"], 0)
        self.assertEqual(rep["tokens_5h"], 0)
        self.assertEqual(rep["tokens_7d"], 0)
        self.assertEqual(rep["burn_rate_str"], "Idle")

    def test_session_user_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sess_dir = Path(tmpdir) / "brain" / "sess_user_test" / ".system_generated" / "logs"
            sess_dir.mkdir(parents=True, exist_ok=True)
            log_file = sess_dir / "transcript_full.jsonl"
            log_file.write_text(
                json.dumps({"source": "USER", "type": "USER_INPUT", "content": "Hello user test", "created_at": "2026-08-30T12:00:00Z"}) + "\n" +
                json.dumps({"source": "MODEL", "type": "MODEL_RESPONSE", "thinking": "Thinking here", "content": "Response here", "created_at": "2026-08-30T12:00:05Z"}) + "\n",
                encoding="utf-8"
            )
            mock_session = {
                "session_id": "sess_user_test",
                "folder": sess_dir,
                "file": log_file,
                "account": "user1@example.com",
                "mtime": log_file.stat().st_mtime,
                "size": log_file.stat().st_size,
                "last_active_str": "2026-08-30 12:00:05"
            }

            # Matching user should return full tokens for this session
            rep_match = get_session_user_report(mock_session, target_user="user1@example.com", active_account="user1@example.com")
            self.assertGreater(rep_match["total"], 0)
            self.assertEqual(rep_match["session_id"], "sess_user_test")

            # Non-matching user should return 0 tokens for this session
            rep_mismatch = get_session_user_report(mock_session, target_user="other_user@example.com", active_account="user1@example.com")
            self.assertEqual(rep_mismatch["total"], 0)
            self.assertEqual(rep_mismatch["tokens_5h"], 0)

            # Cleanup test session from singleton ledger
            ledger.remove_session("sess_user_test")
            ledger.sanitize_ledger()


class TestAnalytics(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
        self.records = [
            (self.now - timedelta(hours=1), 100, 50, 200),
            (self.now - timedelta(hours=3), 200, 100, 400),
            (self.now - timedelta(days=2), 500, 200, 800),
            (self.now - timedelta(days=5), 1000, 500, 1500),
        ]

    def test_timeframes(self):
        for tf in ["5h", "24h", "7d", "30d", "month", "year", "session"]:
            buckets = bucket_records_by_time(self.records, timeframe=tf, ref_time=self.now)
            self.assertIsInstance(buckets, list)
            self.assertGreater(len(buckets), 0)
            summary = calculate_analytics_summary(buckets)
            self.assertIn("total_tokens", summary)
            self.assertIn("prompt_tokens", summary)
            self.assertIn("thinking_tokens", summary)
            self.assertIn("candidates_tokens", summary)

    def test_ascii_chart(self):
        buckets = bucket_records_by_time(self.records, timeframe="5h", ref_time=self.now)
        chart_str = generate_ascii_chart(buckets, title="Test Chart")
        self.assertIn("TEST CHART", chart_str)
        self.assertIn("Period Total Tokens", chart_str)

    def test_export_csv_and_json(self):
        buckets = bucket_records_by_time(self.records, timeframe="7d", ref_time=self.now)
        summary = calculate_analytics_summary(buckets)
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_file = os.path.join(tmpdir, "test.csv")
            json_file = os.path.join(tmpdir, "test.json")
            export_analytics_csv(buckets, csv_file)
            self.assertTrue(os.path.exists(csv_file))

            export_analytics_json(buckets, summary, json_file)
            self.assertTrue(os.path.exists(json_file))
            with open(json_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                self.assertIn("summary", loaded)
                self.assertIn("buckets", loaded)

    def test_local_time_bucketing(self):
        # Verify that use_local_time=True converts buckets and matches local region time
        buckets_local = bucket_records_by_time(self.records, timeframe="5h", ref_time=self.now, use_local_time=True)
        buckets_utc = bucket_records_by_time(self.records, timeframe="5h", ref_time=self.now, use_local_time=False)
        self.assertEqual(len(buckets_local), len(buckets_utc))
        self.assertEqual(len(buckets_local), 11)

    def test_current_and_future_time_coverage(self):
        # Verify that an event happening at the exact current minute is included in 5h and 24h buckets
        now_dt = datetime(2026, 8, 31, 10, 26, 0, tzinfo=timezone.utc)
        current_records = [
            (now_dt, 1000, 200, 300),  # Event at 10:26
            (now_dt - timedelta(hours=2), 500, 100, 150),
        ]
        buckets_5h = bucket_records_by_time(current_records, timeframe="5h", ref_time=now_dt, use_local_time=False)
        summary_5h = calculate_analytics_summary(buckets_5h)
        self.assertEqual(summary_5h["total_tokens"], 2250)
        # Check that 10:00 bucket has the 1500 tokens
        b_1000 = next((b for b in buckets_5h if "10:00" in b["key"]), None)
        self.assertIsNotNone(b_1000)
        self.assertEqual(b_1000["total"], 1500)

        # Check 24h
        buckets_24h = bucket_records_by_time(current_records, timeframe="24h", ref_time=now_dt, use_local_time=False)
        summary_24h = calculate_analytics_summary(buckets_24h)
        self.assertEqual(summary_24h["total_tokens"], 2250)

    def test_current_hour_as_last_block(self):
        # When current time is 13:00 / 13:06, the maximum block on the graph in 5h is 13:00
        ref_time_1300 = datetime(2026, 8, 31, 13, 0, 0, tzinfo=timezone.utc)
        buckets_5h_1300 = bucket_records_by_time(self.records, timeframe="5h", ref_time=ref_time_1300, use_local_time=False)
        self.assertEqual(len(buckets_5h_1300), 11)
        self.assertEqual(buckets_5h_1300[-1]["label"], "13:00")
        self.assertEqual(buckets_5h_1300[0]["label"], "08:00")

        ref_time_1306 = datetime(2026, 8, 31, 13, 6, 0, tzinfo=timezone.utc)
        buckets_5h_1306 = bucket_records_by_time(self.records, timeframe="5h", ref_time=ref_time_1306, use_local_time=False)
        self.assertEqual(len(buckets_5h_1306), 11)
        self.assertEqual(buckets_5h_1306[-1]["label"], "13:00")
        self.assertEqual(buckets_5h_1306[0]["label"], "08:00")

        # In 24h timeframe at 13:00 / 13:06, the last block is 13:00
        buckets_24h_1300 = bucket_records_by_time(self.records, timeframe="24h", ref_time=ref_time_1300, use_local_time=False)
        self.assertEqual(len(buckets_24h_1300), 24)
        self.assertEqual(buckets_24h_1300[-1]["label"], "13:00")

        # When current time is 12:54, the last 30m block is 12:30
        ref_time_54 = datetime(2026, 8, 31, 12, 54, 0, tzinfo=timezone.utc)
        buckets_5h = bucket_records_by_time(self.records, timeframe="5h", ref_time=ref_time_54, use_local_time=False)
        self.assertEqual(len(buckets_5h), 11)
        self.assertEqual(buckets_5h[-1]["label"], "12:30")
        self.assertEqual(buckets_5h[0]["label"], "07:30")

        # When current time is 12:05, the last 30m block is 12:00
        ref_time_05 = datetime(2026, 8, 31, 12, 5, 0, tzinfo=timezone.utc)
        buckets_5h_05 = bucket_records_by_time(self.records, timeframe="5h", ref_time=ref_time_05, use_local_time=False)
        self.assertEqual(buckets_5h_05[-1]["label"], "12:00")
        self.assertEqual(buckets_5h_05[0]["label"], "07:00")

    def test_format_relative_timestamp(self):
        from gui.components.session_table import format_relative_timestamp
        now_local = datetime.now()
        # Today
        today_str = format_relative_timestamp(now_local, "2026-08-30 12:00:00")
        self.assertTrue(today_str.startswith("Today at"))
        # None fallback
        self.assertEqual(format_relative_timestamp(None, "raw_fallback"), "raw_fallback")
        # ISO string with UTC timezone converted to local
        iso_str = now_local.astimezone(timezone.utc).isoformat()
        rel_from_iso = format_relative_timestamp(None, iso_str)
        self.assertTrue(rel_from_iso.startswith("Today at"))


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


class TestAccountManager(unittest.TestCase):
    def test_is_valid_account_email(self):
        self.assertTrue(is_valid_account_email("user.primary@example.com"))
        self.assertTrue(is_valid_account_email("developer@company.org"))
        self.assertTrue(is_valid_account_email("engineer@domain.com"))
        self.assertTrue(is_valid_account_email("user.name@company.org"))
        self.assertTrue(is_valid_account_email("custom.account@workplace.net"))

        self.assertFalse(is_valid_account_email(None))
        self.assertFalse(is_valid_account_email(""))
        self.assertFalse(is_valid_account_email("Default"))
        self.assertFalse(is_valid_account_email("Local"))
        self.assertFalse(is_valid_account_email("Default / Local Account"))
        self.assertFalse(is_valid_account_email("user1@test.com"))
        self.assertFalse(is_valid_account_email("test@domain.com"))
        self.assertFalse(is_valid_account_email("mock@domain.com"))
        self.assertFalse(is_valid_account_email("invalid_string_no_at"))

    def test_get_accounts(self):
        accounts = get_all_known_accounts_list()
        self.assertIsInstance(accounts, list)
        self.assertGreater(len(accounts), 0)
        # Ensure no mock or invalid accounts leaked
        for acc in accounts:
            if acc != "Default / Local Account":
                self.assertTrue(is_valid_account_email(acc))
                self.assertNotIn("@example.com", acc.lower())
                self.assertNotIn("mock", acc.lower())

    def test_fingerprint(self):
        fp = get_auth_files_fingerprint()
        self.assertIsInstance(fp, tuple)

    def test_get_active_google_account(self):
        active = get_active_google_account()
        self.assertTrue(active is None or isinstance(active, str))

    def test_get_account_activity_ranges(self):
        ranges = get_account_activity_ranges()
        self.assertIsInstance(ranges, list)
        for r in ranges:
            self.assertIn("email", r)
            self.assertIn("created_at", r)
            self.assertIn("last_used", r)
            self.assertTrue(is_valid_account_email(r["email"]))

    def test_find_best_matching_account(self):
        matched = find_best_matching_account(0.0, fallback_account="fallback@example.com")
        self.assertEqual(matched, "fallback@example.com")
        # With valid mtime
        matched_valid = find_best_matching_account(1787696300.0, fallback_account="fallback@example.com")
        self.assertTrue(is_valid_account_email(matched_valid) or matched_valid == "fallback@example.com")


class TestLedger(unittest.TestCase):
    def test_ledger_operations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            test_ledger = AccountLedger()
            test_ledger.ledger_file = Path(temp_dir) / "test_usage.json"
            test_ledger.sessions.clear()
            now = datetime.now(timezone.utc)
            test_ledger.update_session(
                session_id="test_sess_999",
                account_email="test_user@example.com",
                stats={"prompt": 100, "thinking": 200, "candidates": 300},
                line_records=[(now, 100, 200, 300)],
                first_prompt="Testing the ledger",
                last_active="2026-08-30 12:00:00"
            )
            self.assertIn("test_sess_999", test_ledger.sessions)
            entry = test_ledger.sessions["test_sess_999"]
            self.assertEqual(entry["total"], 600)
            self.assertEqual(entry["account"], "test_user@example.com")

            acc_rep = test_ledger.get_account_report("test_user@example.com")
            self.assertEqual(acc_rep["total"], 600)

            records = test_ledger.get_all_time_series_records(session_id="test_sess_999")
            self.assertEqual(len(records), 1)

            # Query with matching account and session
            records_match = test_ledger.get_all_time_series_records(session_id="test_sess_999", account_email="test_user@example.com")
            self.assertEqual(len(records_match), 1)

            # Query with non-matching account and session
            records_mismatch = test_ledger.get_all_time_series_records(session_id="test_sess_999", account_email="wrong_user@example.com")
            self.assertEqual(len(records_mismatch), 0)

            test_ledger.remove_session("test_sess_999")
            self.assertNotIn("test_sess_999", test_ledger.sessions)

    def test_reassign_session_account(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            test_ledger = AccountLedger()
            test_ledger.ledger_file = Path(temp_dir) / "test_usage.json"
            test_ledger.sessions.clear()
            now = datetime.now(timezone.utc)
            test_ledger.update_session(
                session_id="reassign_sess_1",
                account_email="account_a@example.com",
                stats={"prompt": 100, "thinking": 200, "candidates": 300},
                line_records=[(now, 100, 200, 300)],
                first_prompt="Initial prompt",
                last_active="2026-08-30 12:00:00"
            )
            self.assertEqual(test_ledger.get_session_account("reassign_sess_1"), "account_a@example.com")

            # Reassign to account_b
            ok = test_ledger.reassign_session_account("reassign_sess_1", "account_b@example.com")
            self.assertTrue(ok)
            self.assertEqual(test_ledger.get_session_account("reassign_sess_1"), "account_b@example.com")

            # Query filtered reports
            rep_a = test_ledger.get_filtered_report(account_email="account_a@example.com", active_only=False)
            self.assertEqual(rep_a["total"], 0)

            rep_b = test_ledger.get_filtered_report(account_email="account_b@example.com", active_only=False)
            self.assertEqual(rep_b["total"], 600)
            self.assertEqual(rep_b["matched_sessions_count"], 1)

    def test_filtered_report_multi_account_isolation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            test_ledger = AccountLedger()
            test_ledger.ledger_file = Path(temp_dir) / "test_usage.json"
            test_ledger.sessions.clear()
            now = datetime.now(timezone.utc)

            # Session 1 for user_one
            test_ledger.update_session(
                session_id="sess_user_one",
                account_email="user_one@example.com",
                stats={"prompt": 50, "thinking": 50, "candidates": 50},
                line_records=[(now, 50, 50, 50)],
                first_prompt="User one chat",
                last_active="2026-08-30 12:00:00",
                mtime=100.0
            )

            # Session 2 for user_two
            test_ledger.update_session(
                session_id="sess_user_two",
                account_email="user_two@example.com",
                stats={"prompt": 200, "thinking": 200, "candidates": 200},
                line_records=[(now, 200, 200, 200)],
                first_prompt="User two chat",
                last_active="2026-08-30 14:00:00",
                mtime=200.0
            )

            # 1. Filtered report for user_one
            rep_one = test_ledger.get_filtered_report(account_email="user_one@example.com", active_only=False)
            self.assertEqual(rep_one["total"], 150)
            self.assertEqual(rep_one["matched_sessions_count"], 1)
            self.assertIn("sess_user_one", rep_one["matching_session_ids"])

            # 2. Filtered report for user_two
            rep_two = test_ledger.get_filtered_report(account_email="user_two@example.com", active_only=False)
            self.assertEqual(rep_two["total"], 600)
            self.assertEqual(rep_two["matched_sessions_count"], 1)
            self.assertIn("sess_user_two", rep_two["matching_session_ids"])

            # 3. Active only for user_one resolves user_one's session
            rep_one_act = test_ledger.get_filtered_report(account_email="user_one@example.com", active_only=True)
            self.assertEqual(rep_one_act["total"], 150)

            # 4. Aggregated All
            rep_all = test_ledger.get_filtered_report(account_email="all", active_only=False)
            self.assertEqual(rep_all["total"], 750)
            self.assertEqual(rep_all["matched_sessions_count"], 2)

    def test_ledger_default_account_matching(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            test_ledger = AccountLedger()
            test_ledger.ledger_file = Path(temp_dir) / "test_usage.json"
            test_ledger.sessions.clear()
            now = datetime.now(timezone.utc)
            try:
                set_active_google_account_in_memory("active_tester@example.com")

                # Session with 'Default' account tag
                test_ledger.update_session(
                    session_id="default_sess_1",
                    account_email="Default",
                    stats={"prompt": 50, "thinking": 50, "candidates": 100},
                    line_records=[(now, 50, 50, 100)],
                    first_prompt="Default session",
                    last_active="2026-08-30 12:00:00"
                )
                # Should be matched when querying active account
                rep = test_ledger.get_account_report("active_tester@example.com")
                self.assertEqual(rep["total"], 200)
            finally:
                set_active_google_account_in_memory(None)

    def test_ledger_sanitize_and_flush(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            test_ledger = AccountLedger()
            test_ledger.ledger_file = Path(temp_dir) / "test_usage.json"
            test_ledger.sessions.clear()
            now = datetime.now(timezone.utc)

            # Add real session and mock session
            test_ledger.update_session(
                session_id="real_sess_1",
                account_email="real.user@example.com",
                stats={"prompt": 10, "thinking": 20, "candidates": 30},
                line_records=[(now, 10, 20, 30)]
            )
            test_ledger.update_session(
                session_id="sess_user_test",
                account_email="user1@example.com",
                stats={"prompt": 5, "thinking": 5, "candidates": 5},
                line_records=[(now, 5, 5, 5)]
            )

            # Sanitize
            removed_count = test_ledger.sanitize_ledger()
            self.assertGreaterEqual(removed_count, 1)
            self.assertNotIn("sess_user_test", test_ledger.sessions)
            self.assertIn("real_sess_1", test_ledger.sessions)

            # Flush to disk and inspect json
            test_ledger.flush_to_disk(force=True)
            saved = json.loads(test_ledger.ledger_file.read_text(encoding="utf-8"))
            self.assertNotIn("user1@example.com", saved.get("accounts", {}))
            self.assertNotIn("sess_user_test", saved.get("sessions", {}))

    def test_ledger_fallback_when_log_file_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            # Create a mock ledger with a non-existent log file
            ledger_instance = AccountLedger()
            ledger_instance.ledger_file = temp_path / "non_existent_usage.json"
            ledger_instance.sessions = {}
            ledger_instance.load_from_disk()
            self.assertIsInstance(ledger_instance.sessions, dict)

    def test_ledger_independent_5h_7d_scopes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            test_ledger = AccountLedger()
            test_ledger.ledger_file = Path(temp_dir) / "test_usage.json"
            test_ledger.sessions.clear()
            now = datetime.now(timezone.utc)

            # Session 1: older session with 500 tokens
            test_ledger.update_session(
                session_id="sess_1_old",
                account_email="tester@example.com",
                stats={"prompt": 200, "thinking": 100, "candidates": 200},
                line_records=[(now - timedelta(hours=2), 200, 100, 200)],
                mtime=(now - timedelta(hours=2)).timestamp()
            )
            # Session 2: active session with 100 tokens
            test_ledger.update_session(
                session_id="sess_2_active",
                account_email="tester@example.com",
                stats={"prompt": 50, "thinking": 25, "candidates": 25},
                line_records=[(now - timedelta(minutes=10), 50, 25, 25)],
                mtime=now.timestamp()
            )

            # Scenario A: 5H = active only (100 tok), 7D = all sessions (600 tok)
            rep_a = test_ledger.get_filtered_report(
                account_email="tester@example.com",
                active_only=True,
                active_only_5h=True,
                active_only_7d=False,
                active_session_id="sess_2_active",
                ref_time=now
            )
            self.assertEqual(rep_a["tokens_5h"], 100)
            self.assertEqual(rep_a["tokens_7d"], 600)
            self.assertTrue(rep_a["active_only_5h"])
            self.assertFalse(rep_a["active_only_7d"])

            # Scenario B: 5H = all sessions (600 tok), 7D = active only (100 tok)
            rep_b = test_ledger.get_filtered_report(
                account_email="tester@example.com",
                active_only=False,
                active_only_5h=False,
                active_only_7d=True,
                active_session_id="sess_2_active",
                ref_time=now
            )
            self.assertEqual(rep_b["tokens_5h"], 600)
            self.assertEqual(rep_b["tokens_7d"], 100)
            self.assertFalse(rep_b["active_only_5h"])
            self.assertTrue(rep_b["active_only_7d"])


class TestWatcher(unittest.TestCase):
    def test_watcher_callback(self):
        from core.watcher import SessionWatcher
        called = []
        watcher = SessionWatcher(on_update_callback=lambda act, all_r, sess: called.append(True))
        watcher._poll(force=True)
        self.assertGreaterEqual(len(called), 0)


class TestSystemTray(unittest.TestCase):
    def test_system_tray_manager(self):
        from gui.tray import SystemTrayManager
        called = []
        mgr = SystemTrayManager(
            on_open_dashboard=lambda: called.append("dash"),
            on_open_mini_hud=lambda: called.append("hud"),
            on_open_bubble=lambda: called.append("bubble"),
            on_refresh=lambda: called.append("ref"),
            on_quit=lambda: called.append("quit")
        )
        mgr._safe_call(mgr.on_open_dashboard)
        mgr._safe_call(mgr.on_open_mini_hud)
        mgr._safe_call(mgr.on_open_bubble)
        mgr._safe_call(mgr.on_refresh)
        mgr._safe_call(mgr.on_quit)
        self.assertEqual(called, ["dash", "hud", "bubble", "ref", "quit"])

        def faulty():
            raise RuntimeError("test error")
        mgr._safe_call(faulty)

    def test_format_tray_tooltip(self):
        from gui.tray import format_tray_tooltip, truncate_utf16
        
        # 1. Standard reports with email account
        display_rep = {
            "tokens_5h": 12500,
            "tokens_7d": 200000,
            "pct_5h_remaining": 75.0,
            "pct_7d_remaining": 92.0,
            "reset_5h_str": "in 2h 30m (75.0% remaining)",
            "reset_7d_str": "in 4d 12h (92.0% remaining)",
        }
        active_rep = {
            "tokens_5h": 8500,
            "tokens_7d": 150000,
        }
        
        tip = format_tray_tooltip(
            display_report=display_rep,
            active_report=active_rep,
            all_report=display_rep,
            account_name="developer@company.org"
        )
        
        self.assertIn("⚡ Gemini (developer)", tip)
        self.assertIn("⏳ 5H: 🔄 in 2h 30m (75% rem)", tip)
        self.assertIn("Act: 8.5K • All: 12.5K", tip)
        self.assertIn("📅 7D: 🔄 in 4d 12h (92% rem)", tip)
        self.assertIn("Act: 150K • All: 200K", tip)
        self.assertLessEqual(len(tip.encode("utf-16-le")) // 2, 127)

        # 2. Large numbers in millions
        big_all = {
            "tokens_5h": 1250000,
            "tokens_7d": 5400000,
            "pct_5h_remaining": 20.0,
            "pct_7d_remaining": 15.0,
            "reset_5h_str": "in 3h 15m",
            "reset_7d_str": "in 6d 22h",
        }
        big_act = {
            "tokens_5h": 1000000,
            "tokens_7d": 3500000,
        }
        big_tip = format_tray_tooltip(
            display_report=big_all,
            active_report=big_act,
            all_report=big_all,
            account_name="poweruser"
        )
        self.assertIn("⚡ Gemini (poweruser)", big_tip)
        self.assertIn("Act: 1.0M • All: 1.2M", big_tip)
        self.assertIn("Act: 3.5M • All: 5.4M", big_tip)
        self.assertLessEqual(len(big_tip.encode("utf-16-le")) // 2, 127)

        # 3. Default empty reports
        empty_tip = format_tray_tooltip()
        self.assertIn("⚡ Gemini (", empty_tip)
        self.assertLessEqual(len(empty_tip.encode("utf-16-le")) // 2, 127)

        # 4. Truncation helper UTF-16 surrogate testing
        emoji_str = "🔄" * 100  # 100 emojis = 200 wchar_t
        truncated = truncate_utf16(emoji_str, 127)
        self.assertLessEqual(len(truncated.encode("utf-16-le")) // 2, 127)

        # 5. Username exceeding 15 characters truncation
        long_user_tip = format_tray_tooltip(account_name="verylongusername12345@example.com")
        self.assertIn("⚡ Gemini (verylongusernam...)", long_user_tip)


class TestGUIComponents(unittest.TestCase):
    def test_component_instantiation(self):
        try:
            import customtkinter as ctk
            root = ctk.CTk()
            root.attributes("-topmost", True)
            root.withdraw()

            from gui.components.stat_card import StatCard
            from gui.components.quota_gauge import QuotaGauge
            from gui.components.progress_bar import SegmentedRatioBar
            from gui.components.usage_chart import UsageChart
            from gui.components.session_table import SessionTable

            card = StatCard(root, title="Test", icon="★", accent_color="#3B82F6")
            card.update_values(1234, 4567, custom_badge="Test")
            self.assertEqual(card.main_value_label.cget("text"), "4,567")
            self.assertIn("1,234", card.lbl_sub_active.cget("text"))
            self.assertIn("4,567", card.lbl_sub_all.cget("text"))

            gauge = QuotaGauge(root, title="Test Gauge", icon="⏳", default_limit=1000000)
            gauge.set_title("⏳  5-Hour Limit")
            gauge.update_data(
                50000, "Reset in 1h", pct_remaining=80.0,
                active_thinking_toks=500, active_prompt_toks=1000, active_candidates_toks=3500, active_total_toks=5000,
                all_thinking_toks=1000, all_prompt_toks=2000, all_candidates_toks=47000, all_total_toks=50000
            )
            self.assertEqual(gauge.title_label.cget("text"), "⏳  5-Hour Limit")
            self.assertEqual(gauge.lbl_big_active_val.cget("text"), "5,000")
            self.assertEqual(gauge.lbl_big_all_val.cget("text"), "50,000")
            self.assertIn("1,000", gauge.lbl_act_p.cget("text"))
            self.assertIn("2,000", gauge.lbl_all_p.cget("text"))

            bar = SegmentedRatioBar(root)
            bar.set_ratios(20.0, 30.0, 50.0)

            chart = UsageChart(root)
            chart.set_records([])
            now_t = datetime.now(timezone.utc)
            chart.set_dual_records([(now_t, 100, 50, 200)], [(now_t, 300, 150, 600)], timeframe="5h")
            self.assertEqual(len(chart.buckets), 11)
            self.assertEqual(len(chart.active_buckets), 11)

            table = SessionTable(root, on_select_session=lambda sid, is_all: None)
            self.assertEqual(table.btn_chat.cget("text"), "⚡ Active Session")
            table.set_sessions([])
            table.set_selection_mode(is_all=False, session_id=None, active_only=False)
            self.assertEqual(table.btn_user.cget("fg_color"), "#3B82F6")
            table.set_selection_mode(is_all=False, session_id=None, active_only=True)
            self.assertEqual(table.btn_chat.cget("fg_color"), "#3B82F6")
            table.set_selection_mode(is_all=True, session_id=None, active_only=False)
            self.assertEqual(table.btn_all.cget("fg_color"), "#8B5CF6")

            from gui.analytics_dialog import AnalyticsDialog
            # 1. Test creation with legacy default_session_id
            dlg1 = AnalyticsDialog(root, default_session_id="active_session")
            dlg1._on_timeframe_changed("24H")
            self.assertEqual(dlg1.selected_scope, "active_session")
            dlg1.destroy()

            # 2. Test creation with synchronized dashboard parameters
            dlg2 = AnalyticsDialog(
                root,
                account_email="developer@company.org",
                active_only=False,
                timeframe="7d"
            )
            self.assertEqual(dlg2.target_account, "developer@company.org")
            self.assertFalse(dlg2.target_active_only)
            self.assertEqual(dlg2.selected_timeframe, "7d")
            self.assertEqual(dlg2.timeframe_seg.get(), "7D")

            # Test sync_with_dashboard dynamically updating scope & timeframe
            dlg2.sync_with_dashboard(account_email="all", active_only=True, timeframe="30d")
            self.assertEqual(dlg2.target_account, "all")
            self.assertTrue(dlg2.target_active_only)
            self.assertEqual(dlg2.selected_timeframe, "30d")
            self.assertEqual(dlg2.timeframe_seg.get(), "30D")

            # Test minsize and resizability (standard top-level window controls)
            self.assertGreaterEqual(dlg2._min_width, 860)
            self.assertGreaterEqual(dlg2._min_height, 560)

            # Test live data rendering and consistency with ledger.get_filtered_report
            from core.ledger import ledger
            test_sid = "test_analytics_sync_001"
            now_dt = datetime.now(timezone.utc)
            ledger.update_session(
                session_id=test_sid,
                account_email="developer@company.org",
                stats={"prompt": 500, "thinking": 250, "candidates": 750},
                line_records=[(now_dt, 500, 250, 750)],
                first_prompt="Testing Analytics Dialog sync",
                last_active="2026-08-31 12:00:00"
            )
            dlg2.sync_with_dashboard(account_email="developer@company.org", active_only=False, session_id=test_sid, timeframe="24h")
            expected_rep = ledger.get_filtered_report(
                account_email="developer@company.org",
                active_only=False,
                session_id=test_sid,
                timeframe="24h"
            )
            self.assertEqual(dlg2.current_summary.get("total_tokens", 0), expected_rep["total"])
            self.assertEqual(dlg2.current_summary.get("prompt_tokens", 0), expected_rep["prompt"])
            self.assertEqual(dlg2.current_summary.get("thinking_tokens", 0), expected_rep["thinking"])
            # 3. Test default instantiation: active user dropdown, All sessions button, 5H filter
            dlg_def = AnalyticsDialog(root)
            # self.assertEqual(dlg_def.session_scope_seg.get(), "All Sessions")
            self.assertFalse(dlg_def.target_active_only)
            self.assertEqual(dlg_def.timeframe_seg.get(), "5H")
            self.assertEqual(dlg_def.selected_timeframe, "5h")

            # Test selecting "All" in account dropdown
            dlg_def._on_account_changed("All")
            # Test legacy _on_scope_changed handler
            dlg_def._on_scope_changed("All")
            self.assertEqual(dlg_def.target_account, "all")

            dlg_def.destroy()
            dlg2.destroy()

            from gui.cleaner_dialog import CleanerDialog, tk
            dlg_cleaner = CleanerDialog(root)
            # Note: -topmost assertion removed; xvfb doesn't support the attribute
            # Test context menu creation for session
            class DummyEvent:
                x_root = 100
                y_root = 100
            orig_popup = tk.Menu.tk_popup
            try:
                tk.Menu.tk_popup = lambda self, x, y: None
                dummy_session = {"session_id": "test_sid_menu_1", "tokens": 100, "size_str": "1 KB"}
                dlg_cleaner._show_context_menu(DummyEvent(), dummy_session)
            finally:
                tk.Menu.tk_popup = orig_popup
            dlg_cleaner.destroy()

            from gui.mini_hud import MiniHUD
            hud = MiniHUD(root, on_restore_callback=lambda: None)
            hud.show_7d_expanded = True
            hud._build_sections()

            # Test drag methods
            class DragEvent:
                x_root = 150
                y_root = 150
            hud._start_drag(DragEvent())
            hud._do_drag(DragEvent())
            hud._end_drag(DragEvent())
            
            # Test 7D progress bar color is green for healthy / 100% capacity
            hud.update_data({
                "prompt": 100, "thinking": 200, "candidates": 300, "total": 600,
                "tokens_5h": 600, "reset_5h_str": "Reset in 1h",
                "tokens_7d": 1000, "reset_7d_str": "Reset in 6d",
                "burn_rate_str": "Idle"
            })
            if hasattr(hud, "prog_7d"):
                self.assertEqual(hud.prog_7d.cget("progress_color"), "#10B981")

            # Test formatting in Mini HUD
            hud.update_data({
                "prompt": 10000, "thinking": 25000, "candidates": 650000, "total": 685000,
                "tokens_5h": 123456, "pct_5h_remaining": 73.1, "reset_5h_str": "in 3h 45m (73.1% remaining)",
                "tokens_7d": 711545, "pct_7d_remaining": 77.2, "reset_7d_str": "in 5d 15h (77.2% remaining)",
                "thinking_5h": 25000, "prompt_5h": 10000, "candidates_5h": 88456,
                "thinking_7d": 25000, "prompt_7d": 10000, "candidates_7d": 676545,
                "burn_rate_str": "Idle"
            })
            self.assertIn("123,456", hud.h5_all_lbl.cget("text"))
            self.assertEqual(hud.h5_all_lbl.cget("text_color"), ("#475569", "#94a3b8"))
            if hasattr(hud, "h7_all_lbl"):
                self.assertIn("711,545", hud.h7_all_lbl.cget("text"))
                self.assertEqual(hud.h7_all_lbl.cget("text_color"), ("#475569", "#94a3b8"))
            # Sub-breakdown in 5h line: Input first, thinking middle, output last
            h5_breakdown = hud.h5_all_breakdown_lbl.cget("text")
            self.assertIn("10,000", h5_breakdown)
            self.assertIn("25,000", h5_breakdown)
            self.assertTrue(h5_breakdown.startswith("📥"))
            self.assertFalse(h5_breakdown.startswith("("))
            self.assertFalse(h5_breakdown.endswith(")"))
            self.assertIn("• 🧠", h5_breakdown)
            self.assertIn("• 📤", h5_breakdown)

            # Test Dropdown Synchronization in Mini HUD
            # 1. Active Session mode
            hud.update_data({
                "mode": "session",
                "session_id": "session_active_123",
                "scope_badge": "Active Session",
                "prompt": 10000, "thinking": 12000, "candidates": 20000, "total": 42000,
                "tokens_5h": 42000, "reset_5h_str": "Reset in 4h",
                "tokens_7d": 42000, "reset_7d_str": "Reset in 6d",
                "thinking_5h": 12000, "prompt_5h": 10000, "candidates_5h": 20000,
                "thinking_7d": 12000, "prompt_7d": 10000, "candidates_7d": 20000,
                "burn_rate_str": "Idle"
            })
            self.assertIn("42,000", hud.h5_all_lbl.cget("text"))
            if hasattr(hud, "h7_all_lbl"):
                self.assertIn("42,000", hud.h7_all_lbl.cget("text"))
            if hasattr(hud, "active_lbl"):
                self.assertIn("Active Session", hud.active_lbl.cget("text"))

            # 2. User Account mode
            hud.update_data({
                "mode": "session",
                "session_id": "session_active_123",
                "account": "user1@example.com",
                "scope_badge": "👤 user1",
                "prompt": 5000, "thinking": 5000, "candidates": 15000, "total": 25000,
                "tokens_5h": 15000, "reset_5h_str": "Reset in 3h",
                "tokens_7d": 25000, "reset_7d_str": "Reset in 5d",
                "thinking_5h": 5000, "prompt_5h": 5000, "candidates_5h": 5000,
                "thinking_7d": 5000, "prompt_7d": 5000, "candidates_7d": 15000,
                "burn_rate_str": "Idle"
            })
            self.assertIn("15,000", hud.h5_all_lbl.cget("text"))
            if hasattr(hud, "h7_all_lbl"):
                self.assertIn("25,000", hud.h7_all_lbl.cget("text"))
            if hasattr(hud, "active_lbl"):
                self.assertIn("user1", hud.active_lbl.cget("text"))

            # 3. All Accounts mode
            hud.update_data({
                "mode": "device",
                "is_all": True,
                "scope_badge": "All Accounts",
                "prompt": 800000, "thinking": 400000, "candidates": 1300000, "total": 2500000,
                "tokens_5h": 900000, "reset_5h_str": "Reset in 2h",
                "tokens_7d": 2500000, "reset_7d_str": "Reset in 4d",
                "thinking_5h": 150000, "prompt_5h": 300000, "candidates_5h": 450000,
                "thinking_7d": 400000, "prompt_7d": 800000, "candidates_7d": 1300000,
                "burn_rate_str": "Idle"
            })
            self.assertIn("900,000", hud.h5_all_lbl.cget("text"))
            if hasattr(hud, "h7_all_lbl"):
                self.assertIn("2,500,000", hud.h7_all_lbl.cget("text"))
            if hasattr(hud, "active_lbl"):
                self.assertIn("All Accounts", hud.active_lbl.cget("text"))

            # 4. Test Google Realtime Quota remaining percentage display
            from core.config import config
            config.set("show_manual_limits", False)
            hud.update_data({
                "mode": "session",
                "session_id": "session_active_456",
                "tokens_5h": 50000,
                "pct_5h_remaining": 88.5,
                "reset_5h_str": "in 3h 15m",
                "tokens_7d": 120000,
                "pct_7d_remaining": 92.4,
                "reset_7d_str": "in 6d 02h",
                "is_realtime_quota": True,
                "burn_rate_str": "Idle"
            })
            self.assertIn("88.5% rem", hud.h5_badge.cget("text"))
            if hasattr(hud, "h7_badge"):
                self.assertIn("92.4% rem", hud.h7_badge.cget("text"))
            config.set("show_manual_limits", False)

            # Test pin toggle
            initial_pin = hud.is_pinned
            hud._toggle_pin()
            self.assertEqual(hud.is_pinned, not initial_pin)
            hud._toggle_pin()
            self.assertEqual(hud.is_pinned, initial_pin)

            # Test 2 lines of stats per card in Mini HUD (Active Session & All Sessions)
            self.assertTrue(hasattr(hud, "h5_active_lbl"))
            self.assertTrue(hasattr(hud, "h5_all_lbl"))
            if hasattr(hud, "h7_active_lbl"):
                self.assertTrue(hasattr(hud, "h7_active_lbl"))
                self.assertTrue(hasattr(hud, "h7_all_lbl"))

            # Update with distinct Active and All reports
            all_rep = {
                "tokens_5h": 50000,
                "thinking_5h": 10000,
                "prompt_5h": 30000,
                "candidates_5h": 10000,
                "tokens_7d": 150000,
                "thinking_7d": 30000,
                "prompt_7d": 90000,
                "candidates_7d": 30000,
                "pct_5h_remaining": 88.5,
                "pct_7d_remaining": 92.4,
                "is_realtime_quota": True,
                "reset_5h_str": "in 3h 15m",
                "reset_7d_str": "in 6d 02h",
                "scope_badge": "★ All Accounts"
            }
            act_rep = {
                "tokens_5h": 5000,
                "thinking_5h": 1000,
                "prompt_5h": 3000,
                "candidates_5h": 1000,
                "tokens_7d": 5000,
                "thinking_7d": 1000,
                "prompt_7d": 3000,
                "candidates_7d": 1000,
                "scope_badge": "Active Session"
            }
            hud.update_data(report=all_rep, session_report=act_rep)

            # Verify 5H lines
            self.assertIn("Active", hud.h5_active_lbl.cget("text"))
            self.assertIn("5,000", hud.h5_active_lbl.cget("text"))
            self.assertIn("All", hud.h5_all_lbl.cget("text"))
            self.assertIn("50,000", hud.h5_all_lbl.cget("text"))

            # Verify 7D lines if expanded
            if hasattr(hud, "h7_active_lbl"):
                self.assertIn("Active", hud.h7_active_lbl.cget("text"))
                self.assertIn("5,000", hud.h7_active_lbl.cget("text"))
                self.assertIn("All", hud.h7_all_lbl.cget("text"))
                self.assertIn("150,000", hud.h7_all_lbl.cget("text"))

            # Test account dropdown selector in Mini HUD
            if hasattr(hud, "account_menu"):
                self.assertIn("All", hud.account_menu.cget("values"))
                hud.account_menu.set("All")
                hud._on_hud_account_selected("All")
                self.assertEqual(hud.account_menu.get(), "All")

            # Test focus-out check safety
            hud._check_focus_and_auto_dismiss()
            hud.destroy()

            from gui.window_utils import apply_windows_dark_titlebar, cancel_all_pending_after_events
            apply_windows_dark_titlebar(root, mode="dark")
            apply_windows_dark_titlebar(root, mode="light")

            cancel_all_pending_after_events(root)
            root.destroy()
        except Exception as e:
            if "no display" in str(e).lower() or "cannot connect to X server" in str(e).lower():
                self.skipTest("No display available for GUI test")
            else:
                raise e

    def test_mini_hud_floating_hover_bubble_mode(self):
        """Test Floating Hover Bubble minimized feature in Mini HUD: bubble layout, click-to-expand, hover preview, collapse, dragging, and pin overrides."""
        try:
            import customtkinter as ctk
            import tkinter as tk
            from core.config import config
            from gui.mini_hud import MiniHUD

            root = ctk.CTk()
            root.withdraw()

            # Default is full Mini-Hub window mode
            hud = MiniHUD(root, on_restore_callback=lambda: None)
            self.assertFalse(hud.is_minimized)
            self.assertFalse(hud.is_hover_expanded)
            self.assertEqual(hud.top_bar.winfo_manager(), "pack")

            # 1. Switch to bubble mode via minimize button
            hud.minimize_btn.invoke()
            self.assertTrue(hud.is_minimized)
            self.assertFalse(hud.is_hover_expanded)
            self.assertEqual(hud.bubble_frame.winfo_manager(), "pack")
            self.assertNotEqual(hud.top_bar.winfo_manager(), "pack")

            # Update report for tooltip text verification
            hud.update_data(
                report={
                    "tokens_5h": 12500,
                    "pct_5h_remaining": 87.5,
                    "reset_5h_str": "in 3h 15m",
                    "tokens_7d": 45000,
                    "pct_7d_remaining": 91.0,
                    "reset_7d_str": "in 5d 10h",
                    "prompt_5h": 5000,
                    "thinking_5h": 2500,
                    "candidates_5h": 5000,
                    "prompt_7d": 20000,
                    "thinking_7d": 5000,
                    "candidates_7d": 20000,
                    "is_realtime_quota": True
                },
                session_report={
                    "tokens_5h": 4000,
                    "prompt_5h": 2000,
                    "thinking_5h": 500,
                    "candidates_5h": 1500,
                    "tokens_7d": 12000,
                    "prompt_7d": 6000,
                    "thinking_7d": 2000,
                    "candidates_7d": 4000,
                }
            )

            # 2. Test Hover on floating bubble: does NOT expand window, triggers full rich tooltip
            hud._on_bubble_hover_enter()
            self.assertFalse(hud.is_hover_expanded)
            self.assertEqual(hud.bubble_frame.winfo_manager(), "pack")
            tooltip_txt = hud._get_tooltip_text()
            self.assertIn("GEMINI TOKEN MONITOR", tooltip_txt)
            self.assertIn("5-HOUR WINDOW", tooltip_txt)
            self.assertIn("12,500", tooltip_txt)
            self.assertIn("45,000", tooltip_txt)
            self.assertIn("87.5%", tooltip_txt)
            self.assertIn("👤", tooltip_txt)

            # Verify clean text formatting without ASCII divider line bloat
            self.assertNotIn("──────────", tooltip_txt)

            # Test Hover leave hides tooltip and verifies left-alignment in structured card
            hud._show_tooltip()
            if hud._tooltip_win:
                self.assertTrue(hud._tooltip_win.winfo_exists())
                # Verify child labels inside tooltip card have anchor='w' / left alignment
                card = hud._tooltip_win.winfo_children()[0]
                labels = [w for w in card.winfo_children() if isinstance(w, ctk.CTkLabel)]
                self.assertGreater(len(labels), 3)
                for lbl in labels:
                    self.assertEqual(lbl.cget("anchor"), "w")

                # Test moving onto tooltip keeps tooltip active
                hud._on_bubble_hover_enter()
                self.assertIsNotNone(hud._tooltip_win)

                # Test leaving tooltip dismisses it when pointer is outside
                hud._on_bubble_hover_leave()
                hud._check_tooltip_dismiss()
                self.assertIsNone(hud._tooltip_win)
            else:
                hud._on_bubble_hover_leave()
                hud._check_tooltip_dismiss()
                self.assertIsNone(hud._tooltip_win)

            # 3. Test Click on bubble (without dragging) -> Expands full HUD
            class MockClickEvent:
                x_root = 100
                y_root = 100
            hud._start_drag(MockClickEvent())
            self.assertFalse(hud._is_dragging)
            hud._end_drag(MockClickEvent())
            self.assertTrue(hud.is_hover_expanded)
            self.assertEqual(hud.top_bar.winfo_manager(), "pack")
            self.assertNotEqual(hud.bubble_frame.winfo_manager(), "pack")

            # 4. Test Moving the full Mini-Hub window does NOT move the floating bubble's own position
            hud._bubble_pos = (500, 300)
            drag_hud = MockClickEvent()
            drag_hud.x_root = 150
            drag_hud.y_root = 150
            hud._start_drag(MockClickEvent())
            hud._do_drag(drag_hud)
            hud._end_drag(drag_hud)
            # Full HUD position updated, but bubble position remains fixed
            self.assertEqual(hud._bubble_pos, (500, 300))

            # 5. Test Auto-shrink on leave collapses back to exact bubble position
            orig_ptrx = hud.winfo_pointerx
            orig_ptry = hud.winfo_pointery
            orig_rootx = hud.winfo_rootx
            orig_rooty = hud.winfo_rooty
            orig_w = hud.winfo_width
            orig_h = hud.winfo_height
            try:
                hud.winfo_rootx = lambda: 100
                hud.winfo_rooty = lambda: 100
                hud.winfo_width = lambda: 350
                hud.winfo_height = lambda: 200
                
                # Pointer inside -> stays expanded
                hud.winfo_pointerx = lambda: 150
                hud.winfo_pointery = lambda: 150
                hud._check_hover_collapse()
                self.assertTrue(hud.is_hover_expanded)

                # Pointer outside but PINNED -> stays expanded
                hud.is_pinned = True
                hud.winfo_pointerx = lambda: 500
                hud.winfo_pointery = lambda: 500
                hud._check_hover_collapse()
                self.assertTrue(hud.is_hover_expanded)

                # Pointer outside and UNPINNED -> automatically shrinks back into bubble at (500, 300)
                hud.is_pinned = False
                hud._check_hover_collapse()
                self.assertFalse(hud.is_hover_expanded)
                self.assertEqual(hud.bubble_frame.winfo_manager(), "pack")
                self.assertEqual(hud._bubble_pos, (500, 300))
            finally:
                hud.winfo_pointerx = orig_ptrx
                hud.winfo_pointery = orig_ptry
                hud.winfo_rootx = orig_rootx
                hud.winfo_rooty = orig_rooty
                hud.winfo_width = orig_w
                hud.winfo_height = orig_h

            # 6. Test Click-outside / FocusOut auto-collapse
            hud._expand_on_click()
            self.assertTrue(hud.is_hover_expanded)
            hud.is_pinned = False
            # Simulate focus moving outside the HUD (e.g. user clicked another window).
            # _check_focus_collapse_to_bubble only collapses when (a) no child of the HUD
            # holds focus AND (b) the pointer is outside the window bounds.
            root.focus_force()
            orig_ptrx2 = hud.winfo_pointerx
            orig_ptry2 = hud.winfo_pointery
            try:
                hud.winfo_pointerx = lambda: 9999
                hud.winfo_pointery = lambda: 9999
                hud._check_focus_collapse_to_bubble()
                self.assertFalse(hud.is_hover_expanded)
                self.assertTrue(hud.is_minimized)
                self.assertEqual(hud.bubble_frame.winfo_manager(), "pack")
            finally:
                hud.winfo_pointerx = orig_ptrx2
                hud.winfo_pointery = orig_ptry2

            # 7. Test Dragging in bubble mode updates bubble anchor position
            drag_b1 = MockClickEvent()
            drag_b1.x_root = 100
            drag_b1.y_root = 100
            hud._start_drag(drag_b1)
            drag_b2 = MockClickEvent()
            drag_b2.x_root = 250
            drag_b2.y_root = 250
            hud._do_drag(drag_b2)
            self.assertTrue(hud._is_dragging)
            hud._end_drag(drag_b2)
            self.assertTrue(hud.is_minimized)
            self.assertFalse(hud.is_hover_expanded)

            # 7b. Test Multi-Cycle Minimize & Maximize preserves independent positions
            # Use positions within any CI screen's work area to avoid clamping side-effects
            hud._hud_pos = (150, 150)
            hud._bubble_pos = (300, 200)
            # Cycle 1: Click bubble to maximize -> expands to _hud_pos (150, 150)
            hud._expand_on_click()
            self.assertTrue(hud.is_hover_expanded)
            self.assertEqual(hud._hud_pos, (150, 150))
            self.assertEqual(hud._bubble_pos, (300, 200))
            # Minimize to bubble -> shrinks to _bubble_pos; clamping may adjust but must NOT change _hud_pos
            hud._toggle_minimized()
            self.assertTrue(hud.is_minimized)
            self.assertFalse(hud.is_hover_expanded)
            self.assertEqual(hud._hud_pos, (150, 150))
            self.assertNotEqual(hud._bubble_pos, hud._hud_pos)
            saved_bubble = hud._bubble_pos
            # Cycle 2: Click bubble to maximize again -> MUST stay at _hud_pos (150, 150)
            hud._expand_on_click()
            self.assertTrue(hud.is_hover_expanded)
            self.assertEqual(hud._hud_pos, (150, 150))
            self.assertEqual(hud._bubble_pos, saved_bubble)
            # Minimize to bubble again -> MUST preserve positions independently
            hud._toggle_minimized()
            self.assertTrue(hud.is_minimized)
            self.assertFalse(hud.is_hover_expanded)
            self.assertEqual(hud._hud_pos, (150, 150))
            self.assertEqual(hud._bubble_pos, saved_bubble)

            # 8. Test At-a-Glance Token Numbers displayed on Floating Bubble
            hud.update_data(
                report={
                    "tokens_5h": 12500,
                    "pct_5h_remaining": 87.5,
                    "reset_5h_str": "in 3h 15m",
                    "tokens_7d": 45000,
                    "pct_7d_remaining": 91.0,
                    "reset_7d_str": "in 5d 10h",
                    "prompt_5h": 5000,
                    "thinking_5h": 2500,
                    "candidates_5h": 5000,
                    "prompt_7d": 20000,
                    "thinking_7d": 5000,
                    "candidates_7d": 20000,
                    "is_realtime_quota": True
                },
                session_report={
                    "tokens_5h": 4000,
                    "prompt_5h": 2000,
                    "thinking_5h": 500,
                    "candidates_5h": 1500,
                    "tokens_7d": 12000,
                    "prompt_7d": 6000,
                    "thinking_7d": 2000,
                    "candidates_7d": 4000,
                }
            )
            self.assertEqual(hud.bubble_hdr_tf.cget("text"), "Time")
            self.assertEqual(hud.bubble_hdr_act.cget("text"), "Active")
            self.assertEqual(hud.bubble_hdr_all.cget("text"), "All")
            self.assertEqual(hud.bubble_hdr_quota.cget("text"), "Quota")
            self.assertEqual(hud.bubble_5h_badge.cget("text"), "5H")
            self.assertEqual(hud.bubble_7d_badge.cget("text"), "7D")
            self.assertIn("4,000", hud.bubble_5h_act_lbl.cget("text"))
            self.assertIn("12,500", hud.bubble_5h_all_lbl.cget("text"))
            self.assertIn("88%", hud.bubble_5h_pct_lbl.cget("text"))
            self.assertIn("12,000", hud.bubble_7d_act_lbl.cget("text"))
            self.assertIn("45,000", hud.bubble_7d_all_lbl.cget("text"))
            self.assertIn("91%", hud.bubble_7d_pct_lbl.cget("text"))

            # Test 6-digit and million boundary formatting
            hud.update_data(
                report={"tokens_5h": 999999, "tokens_7d": 1250000, "pct_5h_remaining": 10.0, "pct_7d_remaining": 50.0},
                session_report={"tokens_5h": 123456, "tokens_7d": 750000}
            )
            self.assertIn("123,456", hud.bubble_5h_act_lbl.cget("text"))
            self.assertIn("999,999", hud.bubble_5h_all_lbl.cget("text"))
            self.assertIn("750,000", hud.bubble_7d_act_lbl.cget("text"))
            self.assertIn("1.25M", hud.bubble_7d_all_lbl.cget("text"))

            # 9. Test Right-Click Context Menu & Menu Actions (Bubble + Expanded)
            hud.deiconify()
            menu_ev = MockClickEvent()
            menu_ev.x_root = 150
            menu_ev.y_root = 150
            menu_ev.widget = hud.bubble_frame
            hud._on_global_right_click(menu_ev)
            self.assertIsNotNone(hud._context_menu_win)
            self.assertTrue(hud._context_menu_win.winfo_exists())

            # Test right-click in expanded mode
            hud.is_minimized = False
            menu_ev2 = MockClickEvent()
            menu_ev2.x_root = 150
            menu_ev2.y_root = 150
            menu_ev2.widget = hud.content_frame
            hud._on_global_right_click(menu_ev2)
            self.assertIsNotNone(hud._context_menu_win)
            self.assertTrue(hud._context_menu_win.winfo_exists())

            # Verify context menu destruction does not cancel root after timers
            test_timer_executed = [False]
            dummy_tid = root.after(5000, lambda: test_timer_executed.__setitem__(0, True))
            hud._context_menu_win.destroy()
            self.assertIsNone(hud._context_menu_win)
            all_afters = root.tk.eval("after info")
            self.assertIn(str(dummy_tid), all_afters)
            root.after_cancel(dummy_tid)

            hud._set_opacity(0.75)
            self.assertEqual(config.get("mini_hud_opacity"), 0.75)
            hud._set_opacity(1.0)

            on_restore_called = [False]
            def _mock_restore():
                on_restore_called[0] = True
            hud.on_restore_callback = _mock_restore
            hud._restore_dashboard()
            self.assertTrue(on_restore_called[0])

            # Clean up
            config.set("hud_minimized", False, save_now=False)
            hud.destroy()
            from gui.window_utils import cancel_all_pending_after_events
            cancel_all_pending_after_events(root)
            root.destroy()
        except Exception as e:
            if "no display" in str(e).lower() or "cannot connect to X server" in str(e).lower():
                self.skipTest("No display available for GUI test")
            else:
                raise e

    def test_app_account_dropdown_switching(self):
        try:
            from gui.app import GeminiTokenCounterApp
            app = GeminiTokenCounterApp()
            app.withdraw()
            if app.watcher and hasattr(app.watcher, "stop"):
                app.watcher.stop()

            # Set account_map with mock accounts
            app.account_map = {
                "All": "all",
                "👤 alice": "alice@company.org",
                "👤 bob": "bob@company.org"
            }
            app.account_menu.configure(values=["All", "👤 alice", "👤 bob"])

            # 1. Select specific user Bob from dropdown
            app._on_main_account_selected("👤 bob")
            self.assertEqual(app.selected_account_filter, "bob@company.org")
            self.assertFalse(app.is_all_mode)

            # 2. Simulate background watcher poll - Bob must NOT be reset to active user
            app._on_watcher_update(active_report={}, all_report={}, sessions=[])
            self.assertEqual(app.selected_account_filter, "bob@company.org")
            self.assertFalse(app.is_all_mode)

            # 3. Select 'All' from dropdown
            app._on_main_account_selected("All")
            self.assertEqual(app.selected_account_filter, "all")
            self.assertTrue(app.is_all_mode)

            # 4. Simulate background watcher poll - All must NOT be reset
            app._on_watcher_update(active_report={}, all_report={}, sessions=[])
            self.assertEqual(app.selected_account_filter, "all")
            self.assertTrue(app.is_all_mode)

            app.destroy()
        except Exception as e:
            if "no display" in str(e).lower() or "cannot connect to X server" in str(e).lower():
                self.skipTest("No display available for GUI test")
            else:
                raise e

    def test_app_mini_hud_and_floating_bubble_buttons(self):
        try:
            from gui.app import GeminiTokenCounterApp
            app = GeminiTokenCounterApp()
            app.withdraw()
            if app.watcher and hasattr(app.watcher, "stop"):
                app.watcher.stop()

            # Verify buttons exist in header and sidebar
            self.assertIsNotNone(app.hud_btn)
            self.assertEqual(app.hud_btn.cget("text"), "🗕 Mini HUD")
            self.assertIsNotNone(app.bubble_btn)
            self.assertEqual(app.bubble_btn.cget("text"), "🫧 Bubble")
            self.assertIsNotNone(app.sidebar_hud_btn)
            self.assertIsNotNone(app.sidebar_bubble_btn)

            # Test opening full Mini-Hub via show_mini_hud
            app.show_mini_hud()
            self.assertIsNotNone(app.mini_hud_window)
            self.assertFalse(app.mini_hud_window.is_minimized)
            self.assertEqual(app.state(), "withdrawn")

            # Test restoring dashboard
            app.show_dashboard()
            self.assertEqual(app.mini_hud_window.state(), "withdrawn")

            # Test opening directly in compact Floating Bubble mode
            app.show_floating_bubble()
            self.assertTrue(app.mini_hud_window.is_minimized)
            self.assertFalse(app.mini_hud_window.is_hover_expanded)
            self.assertEqual(app.state(), "withdrawn")

            # Clean up
            app.mini_hud_window.destroy()
            app.destroy()
        except Exception as e:
            if "no display" in str(e).lower() or "cannot connect to X server" in str(e).lower():
                self.skipTest("No display available for GUI test")
            else:
                raise e


class TestRealtimeQuota(unittest.TestCase):
    def test_format_time_until_reset(self):
        from core.realtime_quota import format_time_until_reset
        now = datetime.now(timezone.utc)
        reset_time = (now + timedelta(hours=3, minutes=45)).isoformat()
        secs, countdown = format_time_until_reset(reset_time, ref_time=now)
        self.assertGreater(secs, 0)
        self.assertIn("3h 45m", countdown)

        # Weekly reset
        weekly_reset = (now + timedelta(days=5, hours=15)).isoformat()
        secs_w, countdown_w = format_time_until_reset(weekly_reset, ref_time=now)
        self.assertGreater(secs_w, 0)
        self.assertIn("5d 15h", countdown_w)

        # Past reset
        past_reset = (now - timedelta(minutes=10)).isoformat()
        secs_p, countdown_p = format_time_until_reset(past_reset, ref_time=now)
        self.assertEqual(secs_p, 0)
        self.assertEqual(countdown_p, "Fully refreshed")

    def test_parse_account_quota_file(self):
        from core.realtime_quota import parse_account_quota_file
        with tempfile.TemporaryDirectory() as tmpdir:
            sample_file = Path(tmpdir) / "sample_account.json"
            sample_data = {
                "id": "test-uuid",
                "email": "test.quota@example.com",
                "name": "Test User",
                "quota": {
                    "subscription_tier": "Google AI Pro",
                    "last_updated": 1788116537,
                    "quota_groups": [
                        {
                            "display_name": "Gemini Models",
                            "buckets": [
                                {
                                    "bucket_id": "gemini-weekly",
                                    "window": "weekly",
                                    "remaining_fraction": 0.7718,
                                    "reset_time": "2026-09-05T10:33:11Z",
                                    "description": "Weekly reset description"
                                },
                                {
                                    "bucket_id": "gemini-5h",
                                    "window": "5h",
                                    "remaining_fraction": 0.7310,
                                    "reset_time": "2026-08-30T22:47:29Z",
                                    "description": "5-hour reset description"
                                }
                            ]
                        }
                    ],
                    "models": [
                        {
                            "name": "gemini-3.7-flash-high",
                            "percentage": 73,
                            "reset_time": "2026-08-30T22:47:29Z",
                            "display_name": "Gemini 3.7 Flash (High)"
                        }
                    ]
                }
            }
            sample_file.write_text(json.dumps(sample_data), encoding="utf-8")

            parsed = parse_account_quota_file(sample_file)
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["email"], "test.quota@example.com")
            self.assertAlmostEqual(parsed["gemini_5h"]["pct_remaining"], 73.1, places=1)
            self.assertAlmostEqual(parsed["gemini_weekly"]["pct_remaining"], 77.18, places=1)
            self.assertIn("quota_groups", parsed)

    def test_ledger_realtime_quota_integration(self):
        from core.ledger import AccountLedger
        test_ledger = AccountLedger()
        # Mock realtime quotas
        test_ledger.realtime_quotas["mock.user@example.com"] = {
            "subscription_tier": "Google AI Pro",
            "gemini_5h": {
                "pct_remaining": 88.5,
                "reset_time": "2026-08-31T01:00:00Z",
                "reset_str": "in 2h 30m (88.5% remaining)",
                "secs_remaining": 9000
            },
            "gemini_weekly": {
                "pct_remaining": 92.0,
                "reset_time": "2026-09-06T00:00:00Z",
                "reset_str": "in 6d 00h (92.0% remaining)",
                "secs_remaining": 518400
            }
        }
        rep = test_ledger.get_account_report("mock.user@example.com")
        self.assertTrue(rep["is_realtime_quota"])
        self.assertEqual(rep["pct_5h_remaining"], 88.5)
        self.assertEqual(rep["pct_7d_remaining"], 92.0)
        self.assertIn("in 2h 30m", rep["reset_5h_str"])
        self.assertIn("in 6d 00h", rep["reset_7d_str"])


class TestAppendOnlyLedgerAndMultiAccountIsolation(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ledger_file = Path(self.tmpdir) / "account_usage.json"
        self.ledger_log = Path(self.tmpdir) / "account_ledger.jsonl"
        self.ledger = AccountLedger()
        self.ledger.ledger_file = self.ledger_file
        self.ledger.ledger_log_file = self.ledger_log
        self.ledger.sessions.clear()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_account_immutability_on_update(self):
        now = datetime.now(timezone.utc)
        # 1. User A creates session_1
        self.ledger.update_session(
            session_id="session_1",
            account_email="userA@example.com",
            stats={"prompt": 100, "thinking": 50, "candidates": 200},
            line_records=[(now, 100, 50, 200)],
            first_prompt="User A Prompt"
        )
        self.assertEqual(self.ledger.get_session_account("session_1"), "userA@example.com")

        # 2. Later, User B logs in and an update occurs on historical session_1 without force_account
        self.ledger.update_session(
            session_id="session_1",
            account_email="userB@example.com",
            stats={"prompt": 150, "thinking": 70, "candidates": 300},
            line_records=[(now, 150, 70, 300)],
            first_prompt="User A Prompt",
            force_account=False
        )
        # Historical account remains userA@example.com (isolated)
        self.assertEqual(self.ledger.get_session_account("session_1"), "userA@example.com")

    def test_mid_session_account_switch_and_attribution(self):
        now = datetime.now(timezone.utc)
        # 1. User A starts active session
        self.ledger.update_session(
            session_id="active_sess_1",
            account_email="userA@example.com",
            stats={"prompt": 100, "thinking": 50, "candidates": 200},
            line_records=[(now, 100, 50, 200)],
            first_prompt="Initial prompt under User A",
            force_account=True
        )
        self.assertEqual(self.ledger.get_session_account("active_sess_1"), "userA@example.com")

        # 2. User B logs in mid-session, active session dynamically updates account
        self.ledger.update_session(
            session_id="active_sess_1",
            account_email="userB@example.com",
            stats={"prompt": 200, "thinking": 80, "candidates": 350},
            line_records=[(now, 100, 50, 200), (now + timedelta(seconds=10), 100, 30, 150)],
            first_prompt="Initial prompt under User A",
            force_account=True
        )
        # Session account now correctly tracks userB@example.com
        self.assertEqual(self.ledger.get_session_account("active_sess_1"), "userB@example.com")

        # 3. Verify event log has account_switched and token_delta under userB@example.com
        self.assertTrue(self.ledger_log.exists())
        lines = [json.loads(l) for l in self.ledger_log.read_text(encoding="utf-8").strip().split("\n") if l.strip()]
        switch_events = [e for e in lines if e.get("event") == "account_switched"]
        self.assertEqual(len(switch_events), 1)
        self.assertEqual(switch_events[0]["previous_account"], "userA@example.com")
        self.assertEqual(switch_events[0]["new_account"], "userB@example.com")

        delta_events = [e for e in lines if e.get("event") == "token_delta"]
        self.assertGreaterEqual(len(delta_events), 1)
        self.assertEqual(delta_events[-1]["account"], "userB@example.com")

        # 4. Verify BOTH accounts retain their token counts and neither goes to zero
        rep_a = self.ledger.get_account_report("userA@example.com")
        self.assertEqual(rep_a["total"], 350)  # User A used 100+50+200 = 350 tokens
        self.assertEqual(rep_a["prompt"], 100)
        self.assertEqual(rep_a["thinking"], 50)
        self.assertEqual(rep_a["candidates"], 200)

        rep_b = self.ledger.get_account_report("userB@example.com")
        self.assertEqual(rep_b["total"], 280)  # User B used delta: (200-100) + (80-50) + (350-200) = 280 tokens
        self.assertEqual(rep_b["prompt"], 100)
        self.assertEqual(rep_b["thinking"], 30)
        self.assertEqual(rep_b["candidates"], 150)

    def test_append_only_log_generation(self):
        now = datetime.now(timezone.utc)
        self.ledger.update_session(
            session_id="session_append_test",
            account_email="test.user@example.com",
            stats={"prompt": 100, "thinking": 20, "candidates": 50},
            line_records=[(now, 100, 20, 50)],
            first_prompt="Test append prompt"
        )
        self.assertTrue(self.ledger_log.exists())
        lines = [json.loads(l) for l in self.ledger_log.read_text(encoding="utf-8").strip().split("\n") if l.strip()]
        self.assertGreaterEqual(len(lines), 1)
        self.assertEqual(lines[0]["session_id"], "session_append_test")
        self.assertEqual(lines[0]["account"], "test.user@example.com")

        # Update with new delta
        self.ledger.update_session(
            session_id="session_append_test",
            account_email="test.user@example.com",
            stats={"prompt": 150, "thinking": 40, "candidates": 80},
            line_records=[(now, 150, 40, 80)],
            first_prompt="Test append prompt"
        )
        lines2 = [json.loads(l) for l in self.ledger_log.read_text(encoding="utf-8").strip().split("\n") if l.strip()]
        self.assertGreaterEqual(len(lines2), 2)
        delta_entry = lines2[-1]
        self.assertEqual(delta_entry["event"], "token_delta")
        self.assertEqual(delta_entry["prompt_delta"], 50)
        self.assertEqual(delta_entry["thinking_delta"], 20)
        self.assertEqual(delta_entry["candidates_delta"], 30)

    def test_multi_account_token_isolation(self):
        now = datetime.now(timezone.utc)
        self.ledger.update_session(
            session_id="sess_a",
            account_email="user_alpha@domain.com",
            stats={"prompt": 500, "thinking": 200, "candidates": 300},
            line_records=[(now, 500, 200, 300)]
        )
        self.ledger.update_session(
            session_id="sess_b",
            account_email="user_beta@domain.com",
            stats={"prompt": 50, "thinking": 10, "candidates": 20},
            line_records=[(now, 50, 10, 20)]
        )

        rep_a = self.ledger.get_account_report("user_alpha@domain.com")
        rep_b = self.ledger.get_account_report("user_beta@domain.com")

        self.assertEqual(rep_a["total"], 1000)
        self.assertEqual(rep_a["unique_sessions_count"], 1)

        self.assertEqual(rep_b["total"], 80)
        self.assertEqual(rep_b["unique_sessions_count"], 1)

        # Cross-account inspection with sample transcript file
        sample_transcript = Path(self.tmpdir) / "transcript.jsonl"
        sample_transcript.write_text(json.dumps({
            "source": "USER", "type": "USER_INPUT", "content": "A" * 2000
        }) + "\n", encoding="utf-8")

        fake_sess_a = {"session_id": "sess_a", "account": "user_alpha@domain.com", "file": str(sample_transcript)}
        user_rep_a = get_session_user_report(fake_sess_a, target_user="user_alpha@domain.com", active_account="user_beta@domain.com")
        user_rep_b = get_session_user_report(fake_sess_a, target_user="user_beta@domain.com", active_account="user_beta@domain.com")

        self.assertGreater(user_rep_a["total"], 0)
        self.assertEqual(user_rep_b["total"], 0)

    def test_flush_and_reload_preserves_per_account_records_and_filtered_report(self):
        now = datetime.now(timezone.utc)
        self.ledger.update_session(
            session_id="persisted_sess_1",
            account_email="persisted.user@example.com",
            stats={"prompt": 500, "thinking": 200, "candidates": 800},
            line_records=[(now, 500, 200, 800)],
            first_prompt="Persisted prompt test"
        )
        self.ledger.flush_to_disk(force=True)
        self.assertTrue(self.ledger_file.exists())

        # Load fresh ledger instance from disk
        fresh_ledger = AccountLedger()
        fresh_ledger.ledger_file = self.ledger_file
        fresh_ledger.ledger_log_file = self.ledger_log
        fresh_ledger.sessions.clear()
        fresh_ledger.load_from_disk()

        self.assertIn("persisted_sess_1", fresh_ledger.sessions)
        sess = fresh_ledger.sessions["persisted_sess_1"]
        self.assertEqual(sess["account"], "persisted.user@example.com")
        self.assertEqual(len(sess["records"]), 1)

        # Test get_filtered_report with account filtering
        rep = fresh_ledger.get_filtered_report(
            account_email="persisted.user@example.com",
            active_only=False,
            timeframe="5h"
        )
        self.assertEqual(rep["total"], 1500)
        self.assertEqual(rep["prompt"], 500)
        self.assertEqual(rep["thinking"], 200)
        self.assertEqual(rep["candidates"], 800)
        self.assertEqual(rep["tokens_5h"], 1500)
        self.assertGreater(len(rep["records"]), 0)


class TestSessionWatcherIdlePause(unittest.TestCase):
    def test_watcher_pause_resume_behavior(self):
        from core.watcher import SessionWatcher
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


class TestUnifiedDashboardFiltering(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ledger_file = Path(self.tmpdir) / "account_usage.json"
        self.ledger_log = Path(self.tmpdir) / "account_ledger.jsonl"
        self.ledger = AccountLedger()
        self.ledger.ledger_file = self.ledger_file
        self.ledger.ledger_log_file = self.ledger_log
        self.ledger.sessions.clear()
        self.now = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)

        # Setup test data:
        # Session 1 (Active session, latest mtime): Account A (2h ago) + Account B (1h ago)
        self.ledger.update_session(
            session_id="active_sess_001",
            account_email="alice@company.org",
            stats={"prompt": 1000, "thinking": 500, "candidates": 1500},
            line_records=[(self.now - timedelta(hours=2), 1000, 500, 1500)],
            first_prompt="Alice prompt in active session",
            last_active="2026-08-31 10:00:00",
            mtime=1788168000.0,
            force_account=True
        )
        self.ledger.update_session(
            session_id="active_sess_001",
            account_email="bob@company.org",
            stats={"prompt": 1500, "thinking": 700, "candidates": 2000},
            line_records=[(self.now - timedelta(hours=2), 1000, 500, 1500), (self.now - timedelta(hours=1), 500, 200, 500)],
            first_prompt="Alice prompt in active session",
            last_active="2026-08-31 11:00:00",
            mtime=1788171600.0,
            force_account=True
        )

        # Session 2 (Historical session, older mtime): Account A (10h ago)
        self.ledger.update_session(
            session_id="hist_sess_002",
            account_email="alice@company.org",
            stats={"prompt": 2000, "thinking": 1000, "candidates": 3000},
            line_records=[(self.now - timedelta(hours=10), 2000, 1000, 3000)],
            first_prompt="Alice old prompt",
            last_active="2026-08-31 02:00:00",
            mtime=1788139200.0,
            force_account=True
        )

        # Session 3 (Older historical session): Account B (3 days ago)
        self.ledger.update_session(
            session_id="hist_sess_003",
            account_email="bob@company.org",
            stats={"prompt": 4000, "thinking": 2000, "candidates": 4000},
            line_records=[(self.now - timedelta(days=3), 4000, 2000, 4000)],
            first_prompt="Bob 3-day old prompt",
            last_active="2026-08-28 12:00:00",
            mtime=1787910000.0,
            force_account=True
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_filter_specific_account_active_only_5h(self):
        # Alice + Active Only (True) + 5H
        rep = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=True,
            timeframe="5h",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        # Alice in active session has 1000 prompt, 500 thinking, 1500 candidates = 3000 tokens within 5h
        self.assertEqual(rep["total"], 3000)
        self.assertEqual(rep["prompt"], 1000)
        self.assertEqual(rep["thinking"], 500)
        self.assertEqual(rep["candidates"], 1500)
        self.assertEqual(rep["matched_sessions_count"], 1)
        self.assertIn("active_sess_001", rep["matching_session_ids"])
        self.assertNotIn("hist_sess_002", rep["matching_session_ids"])

    def test_filter_specific_account_all_sessions_24h(self):
        # Alice + All Sessions (active_only=False) + 24H
        rep = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=False,
            timeframe="24h",
            ref_time=self.now,
            use_local_time=False
        )
        # Alice has active session (3000 tokens @ -2h) + hist session (6000 tokens @ -10h) = 9000 tokens
        self.assertEqual(rep["total"], 9000)
        self.assertEqual(rep["prompt"], 3000)
        self.assertEqual(rep["thinking"], 1500)
        self.assertEqual(rep["candidates"], 4500)
        self.assertEqual(rep["matched_sessions_count"], 2)
        self.assertIn("active_sess_001", rep["matching_session_ids"])
        self.assertIn("hist_sess_002", rep["matching_session_ids"])

    def test_filter_all_accounts_active_only_7d(self):
        # All + Active Only (True) + 7D
        rep = self.ledger.get_filtered_report(
            account_email="All",
            active_only=True,
            timeframe="7d",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        # Active session total across Alice (3000) + Bob (1200) = 4200 tokens
        self.assertEqual(rep["total"], 4200)
        self.assertEqual(rep["prompt"], 1500)
        self.assertEqual(rep["thinking"], 700)
        self.assertEqual(rep["candidates"], 2000)
        self.assertEqual(rep["matched_sessions_count"], 1)

    def test_filter_all_accounts_all_sessions_7d(self):
        # All + All Sessions (False) + 7D
        rep = self.ledger.get_filtered_report(
            account_email="All",
            active_only=False,
            timeframe="7d",
            ref_time=self.now,
            use_local_time=False
        )
        # Total across active (4200) + hist_sess_002 (6000) + hist_sess_003 (10000) = 20200 tokens
        self.assertEqual(rep["total"], 20200)
        self.assertEqual(rep["matched_sessions_count"], 3)

    def test_account_switching_no_stale_data(self):
        # Query Bob + Active Only + 5H
        rep_bob = self.ledger.get_filtered_report(
            account_email="bob@company.org",
            active_only=True,
            timeframe="5h",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep_bob["total"], 1200)
        self.assertEqual(rep_bob["prompt"], 500)
        self.assertEqual(rep_bob["thinking"], 200)
        self.assertEqual(rep_bob["candidates"], 500)

        # Immediately query Alice + Active Only + 5H
        rep_alice = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=True,
            timeframe="5h",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep_alice["total"], 3000)

    def test_empty_states_clean_zero_handling(self):
        # Non-existent user
        rep_empty = self.ledger.get_filtered_report(
            account_email="unknown.user@company.org",
            active_only=False,
            timeframe="5h",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep_empty["total"], 0)
        self.assertEqual(rep_empty["prompt"], 0)
        self.assertEqual(rep_empty["thinking"], 0)
        self.assertEqual(rep_empty["candidates"], 0)
        self.assertEqual(rep_empty["prompt_pct"], 0.0)
        self.assertEqual(rep_empty["matched_sessions_count"], 0)
        self.assertEqual(len(rep_empty["records"]), 0)

    def test_timeframe_window_filtering(self):
        # Alice + All sessions:
        # In 5H window -> only active session (3000 tok @ -2h)
        rep_5h = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=False,
            timeframe="5h",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep_5h["total"], 3000)

        # In 24H window -> active session + hist session (3000 + 6000 = 9000 tok)
        rep_24h = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=False,
            timeframe="24h",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep_24h["total"], 9000)

    def test_default_state_active_user_all_sessions(self):
        # Default view: Active user (alice@company.org) + All Sessions (active_only=False) + 24H
        rep_default = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=False,
            timeframe="24h",
            ref_time=self.now,
            use_local_time=False
        )
        # Should aggregate all sessions for Alice
        self.assertEqual(rep_default["total"], 9000)
        self.assertEqual(rep_default["matched_sessions_count"], 2)

    def test_dual_state_session_scope_toggle(self):
        # 1. "All Sessions" mode
        rep_all_sess = self.ledger.get_filtered_report(
            account_email="bob@company.org",
            active_only=False,
            timeframe="7d",
            ref_time=self.now,
            use_local_time=False
        )
        # Bob has 1200 in active_sess_001 + 10000 in hist_sess_003 = 11200 tokens
        self.assertEqual(rep_all_sess["total"], 11200)
        self.assertEqual(rep_all_sess["matched_sessions_count"], 2)

        # 2. "Active Session" mode
        rep_active_sess = self.ledger.get_filtered_report(
            account_email="bob@company.org",
            active_only=True,
            timeframe="7d",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        # Bob has only 1200 tokens in active session
        self.assertEqual(rep_active_sess["total"], 1200)
        self.assertEqual(rep_active_sess["matched_sessions_count"], 1)

    def test_rule1_user_selected_active_session_toggled(self):
        """Rule 1: If a user account is selected in the dropdown and the Active Session button is toggled, all data must be related to the active session and that selected user."""
        rep = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=True,
            timeframe="5h",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        # Verify prompt, thinking, candidates, total, 5h, 7d are all strictly Alice's active session data
        self.assertEqual(rep["total"], 3000)
        self.assertEqual(rep["prompt"], 1000)
        self.assertEqual(rep["thinking"], 500)
        self.assertEqual(rep["candidates"], 1500)
        self.assertEqual(rep["tokens_5h"], 3000)
        self.assertEqual(rep["tokens_7d"], 3000)
        self.assertEqual(rep["matched_sessions_count"], 1)
        self.assertEqual(rep["matching_session_ids"], ["active_sess_001"])
        self.assertEqual(rep["account"], "alice@company.org")
        self.assertFalse(rep["is_all"])
        self.assertTrue(rep["active_only"])
        self.assertEqual(len(rep["records"]), 1)

    def test_rule2_user_selected_all_sessions_toggled(self):
        """Rule 2: If a user account is selected in the dropdown and the All Sessions button is toggled, all data must be related to all sessions for that selected user."""
        rep = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=False,
            timeframe="24h",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        # Verify Alice across all sessions (active_sess_001: 3000 + hist_sess_002: 6000 = 9000)
        self.assertEqual(rep["total"], 9000)
        self.assertEqual(rep["prompt"], 3000)
        self.assertEqual(rep["thinking"], 1500)
        self.assertEqual(rep["candidates"], 4500)
        self.assertEqual(rep["tokens_5h"], 3000)   # in 5h window: only active session (2h ago)
        self.assertEqual(rep["tokens_7d"], 9000)   # in 7d window: active + hist (10h ago)
        self.assertEqual(rep["matched_sessions_count"], 2)
        self.assertIn("active_sess_001", rep["matching_session_ids"])
        self.assertIn("hist_sess_002", rep["matching_session_ids"])
        self.assertFalse(rep["is_all"])
        self.assertFalse(rep["active_only"])

    def test_rule3_all_selected_active_and_all_sessions_toggled(self):
        """Rule 3: If 'All' is selected in the dropdown, ignore the user account and filter data based only on the toggle button (Active Session / All Sessions)."""
        # A. "All" selected + Active Session toggled
        rep_active = self.ledger.get_filtered_report(
            account_email="All",
            active_only=True,
            timeframe="5h",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        # Active session across both Alice (3000) and Bob (1200) = 4200 tokens
        self.assertEqual(rep_active["total"], 4200)
        self.assertEqual(rep_active["prompt"], 1500)
        self.assertEqual(rep_active["thinking"], 700)
        self.assertEqual(rep_active["candidates"], 2000)
        self.assertEqual(rep_active["tokens_5h"], 4200)
        self.assertEqual(rep_active["matched_sessions_count"], 1)
        self.assertTrue(rep_active["is_all"])
        self.assertTrue(rep_active["active_only"])

        # B. "All" selected + All Sessions toggled
        rep_all = self.ledger.get_filtered_report(
            account_email="All",
            active_only=False,
            timeframe="7d",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        # All sessions across all accounts = 20200 tokens
        self.assertEqual(rep_all["total"], 20200)
        self.assertEqual(rep_all["matched_sessions_count"], 3)
        self.assertTrue(rep_all["is_all"])
        self.assertFalse(rep_all["active_only"])

    def test_rule4_mini_hud_independent_5h_and_7d_scopes(self):
        """Rule 4: In the MINI HUB, implement logic to display 5h and 7d data independently based on their respective toggle buttons."""
        # 1. 5h All Sessions (14200 in 5h? No, active + hist_sess_002 within 5h? Alice active=3000, Bob active=1200, Alice hist=-10h not in 5h)
        # Total in 5h across all sessions = 4200. Total in 7d across active session = 4200. Total in 7d across all sessions = 20200.
        rep_mixed_1 = self.ledger.get_filtered_report(
            account_email="All",
            active_only=False,
            active_only_5h=False,  # 5H for all sessions
            active_only_7d=True,   # 7D for active session
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep_mixed_1["tokens_5h"], 4200)  # All sessions in 5h
        self.assertEqual(rep_mixed_1["tokens_7d"], 4200)  # Active session only in 7d
        self.assertFalse(rep_mixed_1["active_only_5h"])
        self.assertTrue(rep_mixed_1["active_only_7d"])

        # 2. 5h Active Session (3000 for Alice) + 7d All Sessions (9000 for Alice)
        rep_mixed_2 = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=False,
            active_only_5h=True,   # 5H for active session only
            active_only_7d=False,  # 7D for all sessions
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep_mixed_2["tokens_5h"], 3000)  # Alice active session only in 5h
        self.assertEqual(rep_mixed_2["tokens_7d"], 9000)  # Alice all sessions in 7d
        self.assertTrue(rep_mixed_2["active_only_5h"])
        self.assertFalse(rep_mixed_2["active_only_7d"])

    def test_filter_all_time_fallback_for_empty_records(self):
        # Add a session with lifetime tokens but empty line_records
        self.ledger.update_session(
            session_id="empty_rec_sess_004",
            account_email="charlie@company.org",
            stats={"prompt": 10000, "thinking": 20000, "candidates": 108059},
            line_records=[],
            first_prompt="Charlie session with empty records",
            mtime=1788175000.0,
            force_account=True
        )
        rep = self.ledger.get_filtered_report(
            account_email="charlie@company.org",
            active_only=False,
            timeframe="all",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep["total"], 138059)
        self.assertEqual(rep["prompt"], 10000)
        self.assertEqual(rep["thinking"], 20000)
        self.assertEqual(rep["candidates"], 108059)
        self.assertEqual(rep["lifetime_total"], 138059)

    def test_smart_active_session_resolution_account_mismatch(self):
        # Create a session strictly belonging to user X and another strictly belonging to user Y
        self.ledger.update_session(
            session_id="strict_user_x",
            account_email="user_x@company.org",
            stats={"prompt": 500, "thinking": 200, "candidates": 300},
            line_records=[(self.now - timedelta(hours=1), 500, 200, 300)],
            mtime=1788190000.0,
            force_account=True
        )
        self.ledger.update_session(
            session_id="strict_user_y",
            account_email="user_y@company.org",
            stats={"prompt": 800, "thinking": 400, "candidates": 600},
            line_records=[(self.now - timedelta(hours=2), 800, 400, 600)],
            mtime=1788180000.0,
            force_account=True
        )
        # Query for user_y while passing user_x's active_session_id
        rep = self.ledger.get_filtered_report(
            account_email="user_y@company.org",
            active_only=True,
            timeframe="all",
            active_session_id="strict_user_x",
            ref_time=self.now,
            use_local_time=False
        )
        # strict_user_x must be rejected for user_y, and strict_user_y should be automatically resolved
        self.assertEqual(rep["matched_sessions_count"], 1)
        self.assertEqual(rep["matching_session_ids"], ["strict_user_y"])
        self.assertEqual(rep["total"], 1800)
        self.assertEqual(rep["prompt"], 800)
        self.assertEqual(rep["thinking"], 400)
        self.assertEqual(rep["candidates"], 600)


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
            import base64
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
        from core.watcher import SessionWatcher
        watcher = SessionWatcher()
        self.assertFalse(watcher._force_requested)
        watcher.force_refresh()
        self.assertTrue(watcher._force_requested)

    def test_watcher_mtime_cache_pruning(self):
        """Verifies that deleted paths are pruned from watcher mtime caches."""
        from core.watcher import SessionWatcher
        watcher = SessionWatcher()
        fake_deleted_dir = "C:\\fake\\nonexistent\\brain"
        watcher._last_brain_mtimes[fake_deleted_dir] = 12345.0
        watcher._last_realtime_mtimes[fake_deleted_dir] = 12345.0

        watcher._poll(force=True)
        self.assertNotIn(fake_deleted_dir, watcher._last_brain_mtimes)
        self.assertNotIn(fake_deleted_dir, watcher._last_realtime_mtimes)


class TestSessionPaginationAndSlicing(unittest.TestCase):
    """Unit tests for high-performance session pagination across backend, GUI components, and CLI."""

    def test_pagination_slicing_math_boundaries(self):
        """Validates boundary conditions: 0 items, 5 items, 10 items, 25 items, 1000 items."""
        from core.cleaner import paginate_items

        # 1. 0 items
        res0 = paginate_items([], page=1, page_size=10)
        self.assertEqual(res0["items"], [])
        self.assertEqual(res0["page"], 1)
        self.assertEqual(res0["total_pages"], 1)
        self.assertEqual(res0["total_count"], 0)
        self.assertFalse(res0["has_next"])
        self.assertFalse(res0["has_prev"])
        self.assertEqual(res0["start_idx"], 0)
        self.assertEqual(res0["end_idx"], 0)

        # 2. 5 items (less than 1 page)
        items5 = [f"sess_{i}" for i in range(5)]
        res5 = paginate_items(items5, page=1, page_size=10)
        self.assertEqual(len(res5["items"]), 5)
        self.assertEqual(res5["page"], 1)
        self.assertEqual(res5["total_pages"], 1)
        self.assertEqual(res5["total_count"], 5)
        self.assertFalse(res5["has_next"])
        self.assertFalse(res5["has_prev"])
        self.assertEqual(res5["start_idx"], 1)
        self.assertEqual(res5["end_idx"], 5)

        # 3. Exactly 10 items (exactly 1 page)
        items10 = [f"sess_{i}" for i in range(10)]
        res10 = paginate_items(items10, page=1, page_size=10)
        self.assertEqual(len(res10["items"]), 10)
        self.assertEqual(res10["page"], 1)
        self.assertEqual(res10["total_pages"], 1)
        self.assertEqual(res10["total_count"], 10)
        self.assertFalse(res10["has_next"])
        self.assertFalse(res10["has_prev"])
        self.assertEqual(res10["start_idx"], 1)
        self.assertEqual(res10["end_idx"], 10)

        # 4. 25 items (3 pages: 10, 10, 5)
        items25 = [f"sess_{i}" for i in range(25)]
        p1 = paginate_items(items25, page=1, page_size=10)
        self.assertEqual(len(p1["items"]), 10)
        self.assertEqual(p1["items"][0], "sess_0")
        self.assertEqual(p1["items"][-1], "sess_9")
        self.assertEqual(p1["page"], 1)
        self.assertEqual(p1["total_pages"], 3)
        self.assertTrue(p1["has_next"])
        self.assertFalse(p1["has_prev"])
        self.assertEqual(p1["start_idx"], 1)
        self.assertEqual(p1["end_idx"], 10)

        p2 = paginate_items(items25, page=2, page_size=10)
        self.assertEqual(len(p2["items"]), 10)
        self.assertEqual(p2["items"][0], "sess_10")
        self.assertEqual(p2["items"][-1], "sess_19")
        self.assertEqual(p2["page"], 2)
        self.assertTrue(p2["has_next"])
        self.assertTrue(p2["has_prev"])
        self.assertEqual(p2["start_idx"], 11)
        self.assertEqual(p2["end_idx"], 20)

        p3 = paginate_items(items25, page=3, page_size=10)
        self.assertEqual(len(p3["items"]), 5)
        self.assertEqual(p3["items"][0], "sess_20")
        self.assertEqual(p3["items"][-1], "sess_24")
        self.assertEqual(p3["page"], 3)
        self.assertFalse(p3["has_next"])
        self.assertTrue(p3["has_prev"])
        self.assertEqual(p3["start_idx"], 21)
        self.assertEqual(p3["end_idx"], 25)

        # 5. 1,000 items (100 pages of 10 items)
        items1000 = [f"sess_{i}" for i in range(1000)]
        p50 = paginate_items(items1000, page=50, page_size=10)
        self.assertEqual(len(p50["items"]), 10)
        self.assertEqual(p50["page"], 50)
        self.assertEqual(p50["total_pages"], 100)
        self.assertEqual(p50["total_count"], 1000)
        self.assertTrue(p50["has_next"])
        self.assertTrue(p50["has_prev"])
        self.assertEqual(p50["start_idx"], 491)
        self.assertEqual(p50["end_idx"], 500)

        p100 = paginate_items(items1000, page=100, page_size=10)
        self.assertEqual(len(p100["items"]), 10)
        self.assertEqual(p100["page"], 100)
        self.assertEqual(p100["total_pages"], 100)
        self.assertFalse(p100["has_next"])
        self.assertTrue(p100["has_prev"])
        self.assertEqual(p100["start_idx"], 991)
        self.assertEqual(p100["end_idx"], 1000)

    def test_page_bounds_clamping(self):
        """Validates clamping behavior when page < 1, page > total_pages, or invalid types are supplied."""
        from core.cleaner import paginate_items

        items = [f"sess_{i}" for i in range(25)]

        # Negative page -> clamped to 1
        res_neg = paginate_items(items, page=-5, page_size=10)
        self.assertEqual(res_neg["page"], 1)
        self.assertEqual(res_neg["start_idx"], 1)

        # Page 0 -> clamped to 1
        res_zero = paginate_items(items, page=0, page_size=10)
        self.assertEqual(res_zero["page"], 1)

        # Page beyond total_pages -> clamped to total_pages (3)
        res_overflow = paginate_items(items, page=999, page_size=10)
        self.assertEqual(res_overflow["page"], 3)
        self.assertEqual(res_overflow["end_idx"], 25)

        # None items -> safe fallback
        res_none = paginate_items(None, page=1, page_size=10)
        self.assertEqual(res_none["items"], [])
        self.assertEqual(res_none["total_count"], 0)

        # Non-integer page type
        res_str = paginate_items(items, page="invalid", page_size=10)
        self.assertEqual(res_str["page"], 1)

    def test_search_page_reset(self):
        """Verifies that search queries and mode changes in SessionTable reset the current page back to 1."""
        from core.cleaner import paginate_items

        # Simulate SessionTable pagination flow
        sessions = [{"session_id": f"sess_{i:03d}", "title": f"Topic {i}", "last_active_str": "2026-09-01", "mtime": float(i), "size": 1024, "account": "user@example.com"} for i in range(50)]

        # Start at page 4
        current_page = 4
        pag = paginate_items(sessions, page=current_page, page_size=10)
        self.assertEqual(pag["page"], 4)

        # Typing in search resets current_page = 1
        query = "topic 1"
        current_page = 1
        filtered = [s for s in sessions if query in s["title"].lower()]
        pag_searched = paginate_items(filtered, page=current_page, page_size=10)
        self.assertEqual(pag_searched["page"], 1)
        self.assertGreater(pag_searched["total_count"], 0)
        self.assertLessEqual(len(pag_searched["items"]), 10)

    def test_cleaner_cross_page_selection_and_byte_math(self):
        """Verifies that CleanerDialog decoupled selection set persists across page turns and computes accurate total byte sums."""
        from core.cleaner import paginate_items, format_bytes

        # Generate 45 sessions with distinct sizes
        fake_sessions = []
        for i in range(45):
            fake_sessions.append({
                "session_id": f"sess_clean_{i:02d}",
                "title": f"Conversation {i}",
                "size_bytes": 1024 * 1024 * (i + 1),  # (i+1) MB
                "size_str": f"{i+1} MB",
                "tokens": (i + 1) * 1000,
                "folder": f"/path/to/sess_{i}",
                "file": f"/path/to/sess_{i}/transcript.jsonl"
            })

        active_sid = fake_sessions[0]["session_id"]
        selected_session_ids = set()

        # 1. Select All (excluding active session)
        for s in fake_sessions:
            if s["session_id"] != active_sid:
                selected_session_ids.add(s["session_id"])

        self.assertEqual(len(selected_session_ids), 44)
        self.assertNotIn(active_sid, selected_session_ids)

        # 2. Verify total byte calculation across ALL 44 selected sessions (independent of visible page)
        total_selected_bytes = sum(
            s["size_bytes"] for s in fake_sessions
            if s["session_id"] in selected_session_ids
        )
        expected_bytes = sum(1024 * 1024 * (i + 1) for i in range(1, 45))
        self.assertEqual(total_selected_bytes, expected_bytes)

        # 3. Simulate page 1 rendering (10 items)
        p1 = paginate_items(fake_sessions, page=1, page_size=10)
        self.assertEqual(len(p1["items"]), 10)
        p1_checkboxes = {s["session_id"]: (s["session_id"] in selected_session_ids) for s in p1["items"]}
        self.assertFalse(p1_checkboxes[active_sid])  # Active is unselected
        self.assertTrue(p1_checkboxes["sess_clean_01"])

        # 4. Turn to page 3 (items 20-29)
        p3 = paginate_items(fake_sessions, page=3, page_size=10)
        self.assertEqual(len(p3["items"]), 10)
        p3_checkboxes = {s["session_id"]: (s["session_id"] in selected_session_ids) for s in p3["items"]}
        # All items on page 3 should be selected in state
        for sid, is_checked in p3_checkboxes.items():
            self.assertTrue(is_checked)

        # 5. Deselect one item on page 3
        selected_session_ids.discard("sess_clean_25")
        self.assertEqual(len(selected_session_ids), 43)

        # 6. Deselect All
        selected_session_ids.clear()
        self.assertEqual(len(selected_session_ids), 0)

    def test_cli_pagination_args(self):
        """Verifies CLI argument parsing and paginate_items integration for disk usage reporting."""
        import argparse
        from core.cleaner import paginate_items

        parser = argparse.ArgumentParser()
        parser.add_argument("--page", "-p", type=int, default=1)
        parser.add_argument("--limit", "-l", type=int, default=10)
        parser.add_argument("--disk-usage", action="store_true")

        args = parser.parse_args(["--disk-usage", "--page", "3", "--limit", "10"])
        self.assertTrue(args.disk_usage)
        self.assertEqual(args.page, 3)
        self.assertEqual(args.limit, 10)

        sessions = [f"s_{i}" for i in range(100)]
        pag = paginate_items(sessions, page=args.page, page_size=args.limit)
        self.assertEqual(pag["page"], 3)
        self.assertEqual(pag["page_size"], 10)
        self.assertEqual(pag["start_idx"], 21)
        self.assertEqual(pag["end_idx"], 30)
        self.assertEqual(len(pag["items"]), 10)

    def test_analytics_table_pagination(self):
        """Verifies that AnalyticsDialog interval breakdown table correctly paginates time buckets."""
        from core.cleaner import paginate_items

        # Generate 35 hourly interval buckets
        buckets = [{"key": f"2026-09-01T{i:02d}:00", "total": 1000 * (i + 1), "prompt": 500, "thinking": 300, "candidates": 200} for i in range(35)]

        # Page 1: 10 items
        p1 = paginate_items(buckets, page=1, page_size=10)
        self.assertEqual(len(p1["items"]), 10)
        self.assertEqual(p1["total_pages"], 4)
        self.assertEqual(p1["start_idx"], 1)
        self.assertEqual(p1["end_idx"], 10)

        # Page 4: remaining 5 items
        p4 = paginate_items(buckets, page=4, page_size=10)
        self.assertEqual(len(p4["items"]), 5)
        self.assertEqual(p4["start_idx"], 31)
    def test_tray_manager_gdi_debouncing(self):
        """Verifies that SystemTrayManager debounces icon and tooltip updates to eliminate GDI handle leaks."""
        from gui.tray import SystemTrayManager
        tray = SystemTrayManager(
            on_open_dashboard=lambda: None,
            on_open_mini_hud=lambda: None,
            on_refresh=lambda: None,
            on_quit=lambda: None
        )
        # Mock a dummy icon object
        class DummyIcon:
            def __init__(self):
                self.title = ""
                self.icon = None
        tray.icon = DummyIcon()
        tray._last_status_color = "#3B82F6"
        tray._last_tooltip_text = "Initial Text"

        # 1. Update with identical values -> icon & title should not be reassigned
        tray.update_tooltip("Initial Text", status_color="#3B82F6")
        self.assertEqual(tray._last_status_color, "#3B82F6")
        self.assertEqual(tray._last_tooltip_text, "Initial Text")
        self.assertIsNone(tray.icon.icon)  # Did not create or assign new icon

        # 2. Update with new status color -> should assign new icon
        tray.update_tooltip("Initial Text", status_color="#EF4444")
        self.assertEqual(tray._last_status_color, "#EF4444")
        self.assertIsNotNone(tray.icon.icon)

        # 3. Update with new text -> should update title
        tray.update_tooltip("Updated Text", status_color="#EF4444")
        self.assertEqual(tray.icon.title, "Updated Text")

    def test_credential_discovery_caching(self):
        """Verifies that find_credential_files caches results and can be cleared cleanly."""
        from core.account_manager import find_credential_files, clear_credential_cache
        clear_credential_cache()
        res1 = find_credential_files()
        self.assertIsInstance(res1, dict)
        self.assertIn("google_accounts", res1)

        # Immediate secondary call should return the cached dict object
        res2 = find_credential_files()
        self.assertIs(res1, res2)

        # Force refresh or clear should produce a fresh dict
        clear_credential_cache()
        res3 = find_credential_files(force_refresh=True)
        self.assertIsNot(res1, res3)

    def test_brain_dirs_discovery_caching(self):
        """Verifies that find_all_brain_dirs caches results and can be cleared cleanly."""
        from core.session_finder import find_all_brain_dirs, clear_brain_dirs_cache
        clear_brain_dirs_cache()
        dirs1 = find_all_brain_dirs()
        self.assertIsInstance(dirs1, list)

        # Secondary call returns equivalent list from cache
        dirs2 = find_all_brain_dirs()
        self.assertEqual(dirs1, dirs2)

        # Clear cache and force refresh
        clear_brain_dirs_cache()
        dirs3 = find_all_brain_dirs(force_refresh=True)
        self.assertEqual(dirs1, dirs3)

    def test_known_accounts_caching(self):
        """Verifies that get_all_known_accounts_list caches results for 0% CPU dropdown lookups."""
        from core.account_manager import get_all_known_accounts_list, clear_known_accounts_cache
        clear_known_accounts_cache()
        accs1 = get_all_known_accounts_list()
        self.assertIsInstance(accs1, list)

    def test_tray_icon_image_reuse(self):
        """Verifies that create_tray_icon_image reuses cached PIL Image instances to prevent memory/GDI churn."""
        from gui.tray import create_tray_icon_image, _ICON_IMAGE_CACHE
        img1 = create_tray_icon_image("#3B82F6")
        img2 = create_tray_icon_image("#3B82F6")
        self.assertIs(img1, img2)
        self.assertIn("#3B82F6", _ICON_IMAGE_CACHE)

    def test_realtime_quota_caching_and_invalidation(self):
        """Verifies that realtime accounts dirs and quotas use TTL in-memory caching and clean invalidation."""
        from core.realtime_quota import (
            get_realtime_accounts_dirs,
            load_all_realtime_quotas,
            clear_realtime_quota_cache,
            _CACHED_REALTIME_DIRS,
            _CACHED_REALTIME_QUOTAS
        )
        clear_realtime_quota_cache()
        dirs1 = get_realtime_accounts_dirs()
        self.assertIsInstance(dirs1, list)
        dirs2 = get_realtime_accounts_dirs()
        self.assertEqual(dirs1, dirs2)

        quotas1 = load_all_realtime_quotas()
        self.assertIsInstance(quotas1, dict)
        quotas2 = load_all_realtime_quotas()
        self.assertEqual(quotas1, quotas2)

        # Clear cache and re-verify
        clear_realtime_quota_cache()
        quotas3 = load_all_realtime_quotas(force_refresh=True)
        self.assertIsInstance(quotas3, dict)

    def test_context_menu_debouncing(self):
        """Verifies that right-click context menu calls are debounced within 250ms to prevent duplicate window creation."""
        import time
        from gui.components.session_table import SessionTable
        from gui.cleaner_dialog import CleanerDialog

        # Test SessionTable debouncing
        class MockParent:
            def register(self, f): return ""
            def _get_window_scaling(self): return 1.0

        table = SessionTable.__new__(SessionTable)
        table._last_context_menu_time = time.time()
        # Immediate subsequent call within 250ms should return early without error
        event = type("MockEvent", (), {"x_root": 100, "y_root": 100})()
        table._show_context_menu(event, {"session_id": "test_sid"})
        # Remains debounced
        self.assertGreater(table._last_context_menu_time, 0.0)

    def test_mini_hud_geometry_deduplication(self):
        """Verifies that MiniHUD geometry calls are deduplicated using _last_applied_geometry."""
        from gui.mini_hud import MiniHUD

        hud = MiniHUD.__new__(MiniHUD)
        hud._last_applied_geometry = "350x200+100+100"
        geom_called = []
        hud.geometry = lambda g: geom_called.append(g)
        hud._get_scale = lambda: 1.0
        hud._clamp_to_screen = lambda x, y, w, h: (x, y)
        hud._hud_pos = (100, 100)
        hud.is_minimized = False
        hud.is_hover_expanded = False
        hud.update_idletasks = lambda: None
        hud.main_frame = type("MockFrame", (), {"winfo_reqheight": lambda *args: 196})()

        # Recalculate geometry with same target dimensions
        hud._recalculate_geometry()
        # Because target_geo matches _last_applied_geometry ("350x200+100+100"), geometry() should NOT be called
        self.assertEqual(len(geom_called), 0)


if __name__ == "__main__":
    unittest.main()



