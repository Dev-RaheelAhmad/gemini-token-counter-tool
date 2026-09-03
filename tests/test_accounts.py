import os
import sys
import time
import unittest
import tempfile
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from unittest.mock import patch
import base64

from core.account_manager import (
    is_valid_account_email,
    get_all_known_accounts_list,
    get_auth_files_fingerprint,
    get_active_google_account,
    set_active_google_account_in_memory,
    get_account_activity_ranges,
    find_best_matching_account,
    has_auth_credentials_changed,
    decode_id_token_email,
    get_all_google_accounts,
    clear_credential_cache,
)
from core.realtime_quota import (
    format_time_until_reset,
    parse_account_quota_file,
    get_account_realtime_quota,
    load_all_realtime_quotas,
    clear_realtime_quota_cache,
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

    def test_find_best_matching_account_synthetic(self):
        fake_ranges = [
            {
                "email": "primary.developer@company.org",
                "created_at": 10000.0,
                "last_used": 20000.0,
                "last_updated": 20000.0,
            }
        ]
        with patch("core.account_manager.get_account_activity_ranges", return_value=fake_ranges):
            # 1. Inside window [10000 - 1800, 20000 + 1800] = [8200, 21800]
            matched_inside = find_best_matching_account(15000.0, fallback_account="fallback@company.org")
            self.assertEqual(matched_inside, "primary.developer@company.org")

            # 2. Proximity window within 48h (172800s) of last_used (e.g. 50000.0)
            matched_prox = find_best_matching_account(50000.0, fallback_account="fallback@company.org")
            self.assertEqual(matched_prox, "primary.developer@company.org")

            # 3. Far out of range (> 48h away, e.g. 500000.0) -> returns fallback
            matched_far = find_best_matching_account(500000.0, fallback_account="fallback@company.org")
            self.assertEqual(matched_far, "fallback@company.org")

    def test_has_auth_credentials_changed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "oauth_creds.json"
            f.write_text('{"id_token": "token1"}\n', encoding="utf-8")

            fake_files = {
                "google_accounts": [],
                "oauth_creds": [f],
                "jetski_tokens": []
            }

            with patch("core.account_manager.find_credential_files", return_value=fake_files):
                clear_credential_cache()
                # 1. Initial check records fingerprint -> returns True (state established)
                ch1 = has_auth_credentials_changed()
                self.assertTrue(ch1)

                # 2. Immediate second check without file modification -> returns False
                ch2 = has_auth_credentials_changed()
                self.assertFalse(ch2)

                # 3. Modify file (write new content and update mtime)
                time.sleep(0.05)
                f.write_text('{"id_token": "token2_updated"}\n', encoding="utf-8")
                ch3 = has_auth_credentials_changed()
                self.assertTrue(ch3)

                # 4. Immediate fourth check -> returns False
                ch4 = has_auth_credentials_changed()
                self.assertFalse(ch4)

    def test_decode_id_token_email_malformed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Non-existent file
            non_exist = Path(tmpdir) / "does_not_exist.json"
            self.assertIsNone(decode_id_token_email(non_exist))

            # 2. JSON without id_token
            f1 = Path(tmpdir) / "no_token.json"
            f1.write_text('{"other": 123}', encoding="utf-8")
            self.assertIsNone(decode_id_token_email(f1))

            # 3. id_token with no dots
            f2 = Path(tmpdir) / "no_dots.json"
            f2.write_text('{"id_token": "nodotsinthisstring"}', encoding="utf-8")
            self.assertIsNone(decode_id_token_email(f2))

            # 4. Corrupted base64 payload
            f3 = Path(tmpdir) / "bad_b64.json"
            f3.write_text('{"id_token": "header.!!!invalid_base64!!!.sig"}', encoding="utf-8")
            self.assertIsNone(decode_id_token_email(f3))

            # 5. Non-JSON decoded payload
            bad_payload = base64.urlsafe_b64encode(b"not json at all").decode("utf-8").rstrip("=")
            f4 = Path(tmpdir) / "non_json_payload.json"
            f4.write_text(f'{{"id_token": "header.{bad_payload}.sig"}}', encoding="utf-8")
            self.assertIsNone(decode_id_token_email(f4))

            # 6. JSON payload missing email field
            no_email_payload = base64.urlsafe_b64encode(b'{"name": "No Email"}').decode("utf-8").rstrip("=")
            f5 = Path(tmpdir) / "no_email_field.json"
            f5.write_text(f'{{"id_token": "header.{no_email_payload}.sig"}}', encoding="utf-8")
            self.assertIsNone(decode_id_token_email(f5))

    def test_get_all_google_accounts_parsing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ga_file = Path(tmpdir) / "google_accounts.json"
            ga_data = {
                "active": "active.user@company.org",
                "old": [
                    "historical.one@company.org",
                    {"email": "historical.two@company.org"},
                    "mock@test.com",  # Should be filtered out by is_valid_account_email
                    "invalid_string"
                ]
            }
            ga_file.write_text(json.dumps(ga_data), encoding="utf-8")

            fake_files = {
                "google_accounts": [ga_file],
                "oauth_creds": [],
                "jetski_tokens": []
            }
            try:
                set_active_google_account_in_memory("active.user@company.org")
                with patch("core.account_manager.find_credential_files", return_value=fake_files):
                    clear_credential_cache()
                    res = get_all_google_accounts()
                    self.assertEqual(res["active_account"], "active.user@company.org")
                    self.assertTrue(res["has_active"])
                    self.assertIn("historical.one@company.org", res["old_accounts"])
                    self.assertIn("historical.two@company.org", res["old_accounts"])
                    self.assertNotIn("mock@test.com", res["old_accounts"])
                    self.assertNotIn("invalid_string", res["old_accounts"])
            finally:
                set_active_google_account_in_memory(None)


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

    def test_get_account_realtime_quota(self):
        fake_quotas = {
            "developer@company.org": {
                "email": "developer@company.org",
                "gemini_5h": {"pct_remaining": 95.0},
            }
        }
        with patch("core.realtime_quota.load_all_realtime_quotas", return_value=fake_quotas):
            # 1. Exact match
            q_exact = get_account_realtime_quota("developer@company.org")
            self.assertIsNotNone(q_exact)
            self.assertEqual(q_exact["email"], "developer@company.org")

            # 2. Case insensitive match
            q_case = get_account_realtime_quota("DEVELOPER@COMPANY.ORG")
            self.assertIsNotNone(q_case)

            # 3. Username prefix match
            q_prefix = get_account_realtime_quota("developer")
            self.assertIsNotNone(q_prefix)

            # 4. Non-matching email returns None
            self.assertIsNone(get_account_realtime_quota("other@company.org"))

            # 5. Empty or None returns None
            self.assertIsNone(get_account_realtime_quota(""))
            self.assertIsNone(get_account_realtime_quota(None))

    def test_load_all_realtime_quotas_and_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            acc_dir = Path(tmpdir) / "accounts"
            acc_dir.mkdir()

            # Account 1: email in root
            acc1 = acc_dir / "acc1.json"
            acc1.write_text(json.dumps({
                "email": "primary@company.org",
                "quota": {"quota_groups": []}
            }), encoding="utf-8")

            # Account 2: email in token block
            acc2 = acc_dir / "acc2.json"
            acc2.write_text(json.dumps({
                "token": {"email": "secondary@company.org"},
                "quota": {"quota_groups": []}
            }), encoding="utf-8")

            # Account 3: malformed JSON (should be skipped gracefully)
            acc3 = acc_dir / "corrupt.json"
            acc3.write_text("{malformed: json", encoding="utf-8")

            with patch("core.realtime_quota.get_realtime_accounts_dirs", return_value=[acc_dir]):
                clear_realtime_quota_cache()
                # Initial load
                quotas = load_all_realtime_quotas(force_refresh=True)
                self.assertIn("primary@company.org", quotas)
                self.assertIn("secondary@company.org", quotas)
                self.assertEqual(len(quotas), 2)

                # Cached load without force_refresh
                cached = load_all_realtime_quotas(force_refresh=False)
                self.assertEqual(len(cached), 2)

                clear_realtime_quota_cache()

    def test_parse_account_quota_file_third_party_and_clamping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "third_party.json"
            data = {
                "email": "engineer@company.org",
                "quota": {
                    "quota_groups": [
                        {
                            "display_name": "Claude and GPT Models",
                            "buckets": [
                                {
                                    "bucket_id": "claude-5h",
                                    "window": "5h",
                                    "remaining_fraction": 1.5,  # Exceeds 1.0 -> should clamp to 100.0
                                    "reset_time": "2026-09-01T12:00:00Z"
                                },
                                {
                                    "bucket_id": "claude-weekly",
                                    "window": "weekly",
                                    "remaining_fraction": -0.2,  # Negative -> should clamp to 0.0
                                    "reset_time": "2026-09-07T12:00:00Z"
                                }
                            ]
                        }
                    ]
                }
            }
            f.write_text(json.dumps(data), encoding="utf-8")

            parsed = parse_account_quota_file(f)
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["third_party_5h"]["pct_remaining"], 100.0)
            self.assertEqual(parsed["third_party_weekly"]["pct_remaining"], 0.0)
            self.assertEqual(parsed["third_party_5h"]["reset_time"], "2026-09-01T12:00:00Z")
            self.assertEqual(parsed["third_party_weekly"]["reset_time"], "2026-09-07T12:00:00Z")

    def test_recency_based_account_resolution(self):
        from core.account_manager import get_active_google_account, clear_credential_cache
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            ga_file = tmp / "google_accounts.json"
            oc_file = tmp / "oauth_creds.json"

            ga_file.write_text(json.dumps({"active": "older.user@company.org"}), encoding="utf-8")
            # Create a dummy JWT with newer.user@company.org
            payload = base64.urlsafe_b64encode(json.dumps({"email": "newer.user@company.org"}).encode("utf-8")).decode("utf-8").rstrip("=")
            oc_file.write_text(json.dumps({"id_token": f"header.{payload}.sig"}), encoding="utf-8")

            # Set mtime so oc_file is newer than ga_file
            t_now = time.time()
            os.utime(ga_file, (t_now - 100, t_now - 100))
            os.utime(oc_file, (t_now - 10, t_now - 10))

            fake_files = {
                "google_accounts": [ga_file],
                "oauth_creds": [oc_file],
                "jetski_tokens": [],
                "antigravity_accounts": []
            }
            with patch("core.account_manager.find_credential_files", return_value=fake_files):
                clear_credential_cache()
                resolved = get_active_google_account(force_reload=True)
                self.assertEqual(resolved, "newer.user@company.org")

            # Now update ga_file to be newer than oc_file
            os.utime(ga_file, (t_now + 50, t_now + 50))
            with patch("core.account_manager.find_credential_files", return_value=fake_files):
                clear_credential_cache()
                resolved_ga = get_active_google_account(force_reload=True)
                self.assertEqual(resolved_ga, "older.user@company.org")

    def test_antigravity_accounts_extraction(self):
        from core.account_manager import extract_antigravity_active_account, get_active_google_account, clear_credential_cache
        with tempfile.TemporaryDirectory() as tmpdir:
            ag_file = Path(tmpdir) / "accounts.json"
            data = {
                "current_account_id": "uuid-2",
                "accounts": [
                    {"id": "uuid-1", "email": "user1@company.org"},
                    {"id": "uuid-2", "email": "user2@company.org"}
                ]
            }
            ag_file.write_text(json.dumps(data), encoding="utf-8")

            extracted = extract_antigravity_active_account(ag_file)
            self.assertEqual(extracted, "user2@company.org")

            fake_files = {
                "google_accounts": [],
                "oauth_creds": [],
                "jetski_tokens": [],
                "antigravity_accounts": [ag_file]
            }
            with patch("core.account_manager.find_credential_files", return_value=fake_files):
                clear_credential_cache()
                resolved = get_active_google_account(force_reload=True)
                self.assertEqual(resolved, "user2@company.org")

    def test_get_realtime_quota_fingerprint(self):
        from core.realtime_quota import get_realtime_quota_fingerprint
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            f = tmp / "acc1.json"
            f.write_text('{"email": "user@company.org"}', encoding="utf-8")

            with patch("core.realtime_quota.get_realtime_accounts_dirs", return_value=[tmp]):
                fp1 = get_realtime_quota_fingerprint()
                self.assertIsInstance(fp1, tuple)
                self.assertEqual(len(fp1), 1)

                time.sleep(0.05)
                f.write_text('{"email": "user@company.org", "last_used": 12345}', encoding="utf-8")
                fp2 = get_realtime_quota_fingerprint()
                self.assertNotEqual(fp1, fp2)


if __name__ == "__main__":
    unittest.main()
