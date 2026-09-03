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

from core.ledger import AccountLedger, ledger
from core.account_manager import set_active_google_account_in_memory
from core.engine import get_session_user_report


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


if __name__ == "__main__":
    unittest.main()
