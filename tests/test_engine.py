import os
import sys
import unittest
import tempfile
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from core.engine import (
    estimate_tokens,
    parse_iso_time,
    extract_first_prompt,
    extract_line_tokens,
    calculate_window_tracker,
    format_recovery_info,
    get_empty_session_report,
    get_session_user_report,
)
from core.analytics import (
    bucket_records_by_time,
    calculate_analytics_summary,
    generate_ascii_chart,
    export_analytics_csv,
    export_analytics_json,
)
from core.ledger import ledger


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


if __name__ == "__main__":
    unittest.main()
