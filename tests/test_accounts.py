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

from core.account_manager import (
    is_valid_account_email,
    get_all_known_accounts_list,
    get_auth_files_fingerprint,
    get_active_google_account,
    get_account_activity_ranges,
    find_best_matching_account,
)


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


if __name__ == "__main__":
    unittest.main()
