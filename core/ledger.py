import json
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

from core.config import get_config_dir
from core.engine import calculate_window_tracker, format_recovery_info, parse_iso_time
from core.realtime_quota import load_all_realtime_quotas, get_account_realtime_quota


def paginate_items(items: list, page: int = 1, page_size: int = 10) -> Dict[str, Any]:
    """Slices an in-memory list into a paginated subset and returns pagination metadata."""
    total_count = len(items) if items is not None else 0
    try:
        page_size = max(1, int(page_size))
    except (ValueError, TypeError):
        page_size = 10

    total_pages = max(1, (total_count + page_size - 1) // page_size) if total_count > 0 else 1

    try:
        req_page = int(page)
    except (ValueError, TypeError):
        req_page = 1

    clamped_page = max(1, min(req_page, total_pages))

    if total_count == 0 or items is None:
        return {
            "items": [],
            "page": 1,
            "page_size": page_size,
            "total_pages": 1,
            "total_count": 0,
            "has_next": False,
            "has_prev": False,
            "start_idx": 0,
            "end_idx": 0,
        }

    start = (clamped_page - 1) * page_size
    end = start + page_size
    sliced = items[start:end]

    start_idx = start + 1
    end_idx = min(start + len(sliced), total_count)

    return {
        "items": sliced,
        "page": clamped_page,
        "page_size": page_size,
        "total_pages": total_pages,
        "total_count": total_count,
        "has_next": clamped_page < total_pages,
        "has_prev": clamped_page > 1,
        "start_idx": start_idx,
        "end_idx": end_idx,
    }


def get_ledger_file() -> Path:
    return get_config_dir() / "account_usage.json"


def get_ledger_log_file() -> Path:
    return get_config_dir() / "account_ledger.jsonl"


class AccountLedger:
    """
    App Database & In-Memory State Layer with Append-Only Event Log.
    Acts as the single source of truth for all token metrics, per-account quotas,
    session histories, time-series data, and sliding window recovery statistics.
    Uses an append-only JSONL event log (account_ledger.jsonl) for atomic, immutable
    persistence, plus periodic debounced state snapshots.
    """

    def __init__(self, ledger_file: Optional[Path] = None, ledger_log_file: Optional[Path] = None):
        self._lock = threading.RLock()
        self._is_dirty = False
        self._last_flush_time = 0.0
        self.ledger_file = ledger_file or get_ledger_file()
        self.ledger_log_file = ledger_log_file or get_ledger_log_file()
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.realtime_quotas: Dict[str, Dict[str, Any]] = {}
        self.load_from_disk()

    def get_session_account(self, session_id: str) -> Optional[str]:
        """Returns the registered immutable account for a session, if present."""
        with self._lock:
            s = self.sessions.get(session_id)
            if s:
                act = str(s.get("account", "")).strip()
                if act and act not in ("Default", "Local", "None", "Unassigned"):
                    return act
            return None

    def _append_to_log(self, event_type: str, session_id: str, account_email: str, data: Dict[str, Any]):
        """Appends an immutable event record to account_ledger.jsonl in append mode."""
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            entry = {
                "ts": now_iso,
                "event": event_type,
                "session_id": session_id,
                "account": account_email,
                **data
            }
            with open(self.ledger_log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def sanitize_ledger(self) -> int:
        """Purges any mock/test accounts and test sessions from the in-memory database and disk."""
        with self._lock:
            from core.account_manager import is_valid_account_email
            to_remove = []
            for sid, sinfo in list(self.sessions.items()):
                act = str(sinfo.get("account", "")).strip()
                if (
                    sid.startswith("test_")
                    or sid.startswith("sess_user_test")
                    or sid.startswith("mock_")
                    or (act and not is_valid_account_email(act) and act.lower() not in ("default", "local", "default / local account"))
                ):
                    to_remove.append(sid)

            for sid in to_remove:
                del self.sessions[sid]

            if to_remove:
                self._is_dirty = True
                self.flush_to_disk(force=True)
            return len(to_remove)

    def load_from_disk(self):
        """Loads persisted ledger from account_usage.json/account_ledger.jsonl, bootstrapping if needed."""
        with self._lock:
            if not self.ledger_file.exists():
                self._bootstrap_from_disk()
                self.sanitize_ledger()
                return
            try:
                from core.account_manager import is_valid_account_email
                content = self.ledger_file.read_text(encoding="utf-8", errors="ignore")
                data = json.loads(content)
                cleaned_any = False
                if isinstance(data, dict) and "sessions" in data:
                    loaded_sessions = data["sessions"]
                    for sid, sinfo in loaded_sessions.items():
                        act = str(sinfo.get("account", "Default")).strip()
                        # Filter out test/mock sessions
                        if (
                            sid.startswith("test_")
                            or sid.startswith("sess_user_test")
                            or sid.startswith("mock_")
                            or (act and not is_valid_account_email(act) and act.lower() not in ("default", "local", "default / local account"))
                        ):
                            cleaned_any = True
                            continue

                        records: List[Tuple[Optional[datetime], int, int, int]] = []
                        raw_recs = sinfo.get("records") or sinfo.get("time_series_records", [])
                        for rec in raw_recs:
                            if isinstance(rec, (list, tuple)) and len(rec) >= 4:
                                dt = parse_iso_time(rec[0]) if isinstance(rec[0], str) else None
                                records.append((dt, int(rec[1]), int(rec[2]), int(rec[3])))

                        lifetime = sinfo.get("lifetime_tokens", {})
                        prompt = int(lifetime.get("prompt") if lifetime else sinfo.get("prompt", 0))
                        thinking = int(lifetime.get("thinking") if lifetime else sinfo.get("thinking", 0))
                        candidates = int(lifetime.get("candidates") if lifetime else sinfo.get("candidates", 0))
                        total = int(lifetime.get("total") if lifetime else sinfo.get("total", prompt + thinking + candidates))
                        raw_account_usage = sinfo.get("account_breakdown") or sinfo.get("account_usage")
                        account_usage = {}
                        if isinstance(raw_account_usage, dict):
                            for u_act, udata in raw_account_usage.items():
                                if isinstance(udata, dict):
                                    u_records = []
                                    for rec in udata.get("records", []):
                                        if isinstance(rec, (list, tuple)) and len(rec) >= 4:
                                            dt = parse_iso_time(rec[0]) if isinstance(rec[0], str) else None
                                            u_records.append((dt, int(rec[1]), int(rec[2]), int(rec[3])))
                                    if not u_records and records and (len(raw_account_usage) == 1 or u_act == act):
                                        u_records = list(records)
                                    account_usage[u_act] = {
                                        "prompt": int(udata.get("prompt", 0)),
                                        "thinking": int(udata.get("thinking", 0)),
                                        "candidates": int(udata.get("candidates", 0)),
                                        "total": int(udata.get("total", 0)),
                                        "records": u_records,
                                    }
                        if not account_usage:
                            account_usage = {
                                act: {
                                    "prompt": prompt,
                                    "thinking": thinking,
                                    "candidates": candidates,
                                    "total": total,
                                    "records": list(records),
                                }
                            }

                        self.sessions[sid] = {
                            "session_id": sid,
                            "account": act,
                            "prompt": prompt,
                            "thinking": thinking,
                            "candidates": candidates,
                            "total": total,
                            "first_prompt": sinfo.get("first_prompt", "") or sinfo.get("title", ""),
                            "title": sinfo.get("title", "") or sinfo.get("first_prompt", ""),
                            "last_active": sinfo.get("last_active", "Unknown"),
                            "mtime": float(sinfo.get("mtime", 0.0)),
                            "size": int(sinfo.get("size_bytes") if "size_bytes" in sinfo else sinfo.get("size", 0)),
                            "folder": sinfo.get("folder_path", ""),
                            "file": sinfo.get("file_path", ""),
                            "records": records,
                            "account_usage": account_usage,
                        }

                # Reconstruct per-account attribution from event log only if missing in snapshot
                if self.ledger_log_file.exists():
                    try:
                        for line in self.ledger_log_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                            line_str = line.strip()
                            if not line_str:
                                continue
                            try:
                                entry = json.loads(line_str)
                                evt = entry.get("event")
                                sid = entry.get("session_id")
                                log_act = entry.get("account")
                                if sid and log_act and sid in self.sessions:
                                    sess = self.sessions[sid]
                                    acc_usage = sess.setdefault("account_usage", {})
                                    # Only replay from event log if account_usage was not already present in the JSON snapshot
                                    if not acc_usage or (len(acc_usage) == 1 and "Default" in acc_usage and log_act != "Default"):
                                        u = acc_usage.setdefault(log_act, {
                                            "prompt": 0, "thinking": 0, "candidates": 0, "total": 0, "records": []
                                        })
                                        if evt == "token_delta":
                                            p_d = int(entry.get("prompt_delta", 0))
                                            th_d = int(entry.get("thinking_delta", 0))
                                            c_d = int(entry.get("candidates_delta", 0))
                                            tot_d = int(entry.get("total_delta", p_d + th_d + c_d))
                                            u["prompt"] += p_d
                                            u["thinking"] += th_d
                                            u["candidates"] += c_d
                                            u["total"] += tot_d
                            except Exception:
                                continue
                    except Exception:
                        pass

                if cleaned_any or self._is_dirty:
                    self._is_dirty = True
                    self.flush_to_disk(force=True)

            except Exception:
                self._bootstrap_from_disk()
                self.sanitize_ledger()

    def _bootstrap_from_disk(self):
        """Populates initial in-memory ledger from available disk transcripts."""
        try:
            from core.session_finder import get_all_session_files
            from core.engine import parse_transcript_file_cached
            from core.account_manager import get_active_google_account, find_best_matching_account

            sessions = get_all_session_files()
            active_account = get_active_google_account() or "Default"
            for idx, s in enumerate(sessions):
                sid = s.get("session_id", "unknown")
                stats, records, fp = parse_transcript_file_cached(s["file"])
                prompt = stats.get("prompt", 0)
                thinking = stats.get("thinking", 0)
                candidates = stats.get("candidates", 0)
                total = prompt + thinking + candidates

                if idx == 0 and active_account and active_account not in ("Default", "Local"):
                    sess_account = active_account
                else:
                    sess_account = find_best_matching_account(s.get("mtime", 0.0), fallback_account=active_account)

                self.sessions[sid] = {
                    "session_id": sid,
                    "account": sess_account,
                    "prompt": prompt,
                    "thinking": thinking,
                    "candidates": candidates,
                    "total": total,
                    "first_prompt": fp,
                    "title": fp or sid,
                    "last_active": s.get("last_active_str", "Unknown"),
                    "mtime": s.get("mtime", 0.0),
                    "size": s.get("size", 0),
                    "folder": str(s.get("folder", "")),
                    "file": str(s.get("file", "")),
                    "records": records,
                    "account_usage": {
                        sess_account: {
                            "prompt": prompt,
                            "thinking": thinking,
                            "candidates": candidates,
                            "total": total,
                            "records": list(records),
                        }
                    }
                }
            self._is_dirty = True
        except Exception:
            pass

    def flush_to_disk(self, force: bool = False):
        """
        Comprehensive Database Serializer.
        Writes all session metrics, account summaries, rolling 5h/7d quotas,
        recovery countdowns, and time-series records to account_usage.json.
        Debounced to prevent SSD wear (only writes when dirty or forced).
        """
        with self._lock:
            if not self._is_dirty and not force:
                return
            import copy
            sessions_snapshot = copy.deepcopy(self.sessions)
            rt_quotas_snapshot = dict(self.realtime_quotas)
            self._is_dirty = False

        try:
            from core.account_manager import get_active_google_account, is_valid_account_email
            active_google_account = get_active_google_account() or "Default"
            now_utc = datetime.now(timezone.utc)

            # 1. Build Session Database & Group by Account
            serialized_sessions = {}
            account_groups: Dict[str, List[Dict[str, Any]]] = {}

            for sid, sinfo in sessions_snapshot.items():
                act = sinfo.get("account", "Default")
                if sid.startswith("sess_user_test") or sid.startswith("test_") or sid.startswith("mock_"):
                    continue

                acc_usage = sinfo.get("account_usage")
                if acc_usage and isinstance(acc_usage, dict):
                    for user_acc, udata in acc_usage.items():
                        if udata.get("total", 0) > 0 and (is_valid_account_email(user_acc) or user_acc.lower() in ("default", "local", "default / local account")):
                            if user_acc not in account_groups:
                                account_groups[user_acc] = []
                            account_groups[user_acc].append({
                                "session_id": sid,
                                "account": user_acc,
                                "prompt": udata.get("prompt", 0),
                                "thinking": udata.get("thinking", 0),
                                "candidates": udata.get("candidates", 0),
                                "total": udata.get("total", 0),
                                "records": udata.get("records", []),
                                "first_prompt": sinfo.get("first_prompt", ""),
                                "title": sinfo.get("title", ""),
                                "last_active": sinfo.get("last_active", "Unknown"),
                                "mtime": sinfo.get("mtime", 0.0),
                                "size": sinfo.get("size", 0),
                                "folder": sinfo.get("folder", ""),
                                "file": sinfo.get("file", ""),
                            })
                else:
                    if act not in account_groups:
                        account_groups[act] = []
                    account_groups[act].append(sinfo)

                # Compute session-level window quotas
                records = sinfo.get("records", [])
                window_tracker = calculate_window_tracker(records, ref_time=now_utc)
                recovery = format_recovery_info(window_tracker, ref_time=now_utc)

                p = sinfo.get("prompt", 0)
                th = sinfo.get("thinking", 0)
                c = sinfo.get("candidates", 0)
                tot = sinfo.get("total", p + th + c)

                p_pct = (p / tot * 100) if tot > 0 else 0.0
                th_pct = (th / tot * 100) if tot > 0 else 0.0
                c_pct = (c / tot * 100) if tot > 0 else 0.0

                raw_records = []
                for dt, rp, rth, rc in records:
                    dt_str = dt.isoformat() if dt is not None else None
                    raw_records.append([dt_str, rp, rth, rc])

                serialized_breakdown = {}
                if acc_usage and isinstance(acc_usage, dict):
                    for u_act, udata in acc_usage.items():
                        u_recs_raw = []
                        for r_item in udata.get("records", []):
                            if isinstance(r_item, (list, tuple)) and len(r_item) >= 4:
                                dt_val = r_item[0]
                                dt_str = dt_val.isoformat() if isinstance(dt_val, datetime) else (str(dt_val) if dt_val else None)
                                u_recs_raw.append([dt_str, int(r_item[1]), int(r_item[2]), int(r_item[3])])
                        serialized_breakdown[u_act] = {
                            "prompt": udata.get("prompt", 0),
                            "thinking": udata.get("thinking", 0),
                            "candidates": udata.get("candidates", 0),
                            "total": udata.get("total", 0),
                            "records": u_recs_raw,
                        }

                serialized_sessions[sid] = {
                    "session_id": sid,
                    "account": act,
                    "title": sinfo.get("title") or sinfo.get("first_prompt") or sid,
                    "first_prompt": sinfo.get("first_prompt", ""),
                    "folder_path": sinfo.get("folder", ""),
                    "file_path": sinfo.get("file", ""),
                    "last_active": sinfo.get("last_active", "Unknown"),
                    "mtime": sinfo.get("mtime", 0.0),
                    "size_bytes": sinfo.get("size", 0),
                    "records": raw_records,
                    "account_breakdown": serialized_breakdown,
                    "lifetime_tokens": {
                        "prompt": p,
                        "thinking": th,
                        "candidates": c,
                        "total": tot,
                        "prompt_pct": round(p_pct, 2),
                        "thinking_pct": round(th_pct, 2),
                        "candidates_pct": round(c_pct, 2),
                    },
                    "quota_5h": {
                        "tokens_burned": recovery["tokens_5h"],
                        "prompt_tokens": recovery["prompt_5h"],
                        "thinking_tokens": recovery["thinking_5h"],
                        "candidate_tokens": recovery["candidates_5h"],
                        "reset_str": recovery["reset_5h_str"],
                        "pct_remaining": round(recovery["pct_5h_remaining"], 2),
                        "secs_remaining": recovery["secs_5h_remaining"],
                        "recovery_time": recovery["recovery_5h_time"].isoformat() if recovery["recovery_5h_time"] else None,
                    },
                    "quota_7d": {
                        "tokens_burned": recovery["tokens_7d"],
                        "prompt_tokens": recovery["prompt_7d"],
                        "thinking_tokens": recovery["thinking_7d"],
                        "candidate_tokens": recovery["candidates_7d"],
                        "reset_str": recovery["reset_7d_str"],
                        "pct_remaining": round(recovery["pct_7d_remaining"], 2),
                        "secs_remaining": recovery["secs_7d_remaining"],
                        "recovery_time": recovery["recovery_7d_time"].isoformat() if recovery["recovery_7d_time"] else None,
                    },
                    "burn_velocity": {
                        "tokens_15m": recovery["tokens_15m"],
                        "tokens_1h": recovery["tokens_1h"],
                        "burn_rate_hr": recovery["burn_rate_hr"],
                        "burn_rate_str": recovery["burn_rate_str"],
                    },
                    "time_series_records": raw_records,
                }

            # 3. Build Account Database
            serialized_accounts = {}
            for act, s_list in account_groups.items():
                if not is_valid_account_email(act) and act.lower() not in ("default", "local", "default / local account"):
                    continue
                act_records: List[Tuple[Optional[datetime], int, int, int]] = []
                act_p, act_th, act_c = 0, 0, 0
                for s in s_list:
                    act_p += s.get("prompt", 0)
                    act_th += s.get("thinking", 0)
                    act_c += s.get("candidates", 0)
                    act_records.extend(s.get("records", []))

                act_tot = act_p + act_th + act_c
                act_w = calculate_window_tracker(act_records, ref_time=now_utc)
                act_rec = format_recovery_info(act_w, ref_time=now_utc)

                acc_data = {
                    "account_email": act,
                    "is_currently_active": (act.lower() == active_google_account.lower()),
                    "total_sessions_count": len(s_list),
                    "session_ids": [s["session_id"] for s in s_list],
                    "lifetime_tokens": {
                        "prompt": act_p,
                        "thinking": act_th,
                        "candidates": act_c,
                        "total": act_tot,
                        "prompt_pct": round((act_p / act_tot * 100) if act_tot > 0 else 0.0, 2),
                        "thinking_pct": round((act_th / act_tot * 100) if act_tot > 0 else 0.0, 2),
                        "candidates_pct": round((act_c / act_tot * 100) if act_tot > 0 else 0.0, 2),
                    },
                    "quota_5h": {
                        "tokens_burned": act_rec["tokens_5h"],
                        "prompt_tokens": act_rec["prompt_5h"],
                        "thinking_tokens": act_rec["thinking_5h"],
                        "candidate_tokens": act_rec["candidates_5h"],
                        "reset_str": act_rec["reset_5h_str"],
                        "pct_remaining": round(act_rec["pct_5h_remaining"], 2),
                        "secs_remaining": act_rec["secs_5h_remaining"],
                        "recovery_time": act_rec["recovery_5h_time"].isoformat() if act_rec["recovery_5h_time"] else None,
                    },
                    "quota_7d": {
                        "tokens_burned": act_rec["tokens_7d"],
                        "prompt_tokens": act_rec["prompt_7d"],
                        "thinking_tokens": act_rec["thinking_7d"],
                        "candidate_tokens": act_rec["candidates_7d"],
                        "reset_str": act_rec["reset_7d_str"],
                        "pct_remaining": round(act_rec["pct_7d_remaining"], 2),
                        "secs_remaining": act_rec["secs_7d_remaining"],
                        "recovery_time": act_rec["recovery_7d_time"].isoformat() if act_rec["recovery_7d_time"] else None,
                    },
                    "burn_velocity": {
                        "tokens_15m": act_rec["tokens_15m"],
                        "tokens_1h": act_rec["tokens_1h"],
                        "burn_rate_hr": act_rec["burn_rate_hr"],
                        "burn_rate_str": act_rec["burn_rate_str"],
                    }
                }

                # Attach synced real-time Google quota if available
                rt_info = rt_quotas_snapshot.get(act.lower().strip())
                if rt_info and rt_info.get("email", "").lower().strip() == act.lower().strip():
                    acc_data["google_live_quota"] = {
                        "5h_pct_remaining": rt_info["gemini_5h"]["pct_remaining"],
                        "5h_reset_time": rt_info["gemini_5h"]["reset_time"],
                        "5h_reset_str": rt_info["gemini_5h"]["reset_str"],
                        "7d_pct_remaining": rt_info["gemini_weekly"]["pct_remaining"],
                        "7d_reset_time": rt_info["gemini_weekly"]["reset_time"],
                        "7d_reset_str": rt_info["gemini_weekly"]["reset_str"],
                        "3p_5h_pct_remaining": rt_info["third_party_5h"]["pct_remaining"],
                        "3p_5h_reset_time": rt_info["third_party_5h"]["reset_time"],
                        "3p_weekly_pct_remaining": rt_info["third_party_weekly"]["pct_remaining"],
                        "3p_weekly_reset_time": rt_info["third_party_weekly"]["reset_time"],
                        "quota_groups": rt_info.get("quota_groups", []),
                    }

                serialized_accounts[act] = acc_data

            # Also ensure all accounts from rt_quotas_snapshot are represented
            existing_acc_keys = {k.lower().strip() for k in serialized_accounts.keys()}
            for rt_email, rt_info in rt_quotas_snapshot.items():
                if is_valid_account_email(rt_email) and rt_email.lower().strip() not in existing_acc_keys:
                    full_email = rt_info.get("email", rt_email)
                    serialized_accounts[full_email] = {
                        "account_email": full_email,
                        "is_currently_active": (full_email.lower() == active_google_account.lower()),
                        "total_sessions_count": 0,
                        "session_ids": [],
                        "lifetime_tokens": {
                            "prompt": 0,
                            "thinking": 0,
                            "candidates": 0,
                            "total": 0,
                            "prompt_pct": 0.0,
                            "thinking_pct": 0.0,
                            "candidates_pct": 0.0,
                        },
                        "quota_5h": {
                            "tokens_burned": 0,
                            "prompt_tokens": 0,
                            "thinking_tokens": 0,
                            "candidate_tokens": 0,
                            "reset_str": rt_info["gemini_5h"]["reset_str"],
                            "pct_remaining": round(rt_info["gemini_5h"]["pct_remaining"], 2),
                            "secs_remaining": rt_info["gemini_5h"]["secs_remaining"],
                            "recovery_time": rt_info["gemini_5h"]["reset_time"],
                        },
                        "quota_7d": {
                            "tokens_burned": 0,
                            "prompt_tokens": 0,
                            "thinking_tokens": 0,
                            "candidate_tokens": 0,
                            "reset_str": rt_info["gemini_weekly"]["reset_str"],
                            "pct_remaining": round(rt_info["gemini_weekly"]["pct_remaining"], 2),
                            "secs_remaining": rt_info["gemini_weekly"]["secs_remaining"],
                            "recovery_time": rt_info["gemini_weekly"]["reset_time"],
                        },
                        "burn_velocity": {
                            "tokens_15m": 0,
                            "tokens_1h": 0,
                            "burn_rate_hr": 0,
                            "burn_rate_str": "Idle",
                        },
                        "google_live_quota": {
                            "5h_pct_remaining": rt_info["gemini_5h"]["pct_remaining"],
                            "5h_reset_time": rt_info["gemini_5h"]["reset_time"],
                            "5h_reset_str": rt_info["gemini_5h"]["reset_str"],
                            "7d_pct_remaining": rt_info["gemini_weekly"]["pct_remaining"],
                            "7d_reset_time": rt_info["gemini_weekly"]["reset_time"],
                            "7d_reset_str": rt_info["gemini_weekly"]["reset_str"],
                            "3p_5h_pct_remaining": rt_info["third_party_5h"]["pct_remaining"],
                            "3p_5h_reset_time": rt_info["third_party_5h"]["reset_time"],
                            "3p_weekly_pct_remaining": rt_info["third_party_weekly"]["pct_remaining"],
                            "3p_weekly_reset_time": rt_info["third_party_weekly"]["reset_time"],
                            "quota_groups": rt_info.get("quota_groups", []),
                        }
                    }
                    existing_acc_keys.add(rt_email.lower().strip())

            # 4. Global Device Summary
            all_dev_records: List[Tuple[Optional[datetime], int, int, int]] = []
            dev_p, dev_th, dev_c = 0, 0, 0
            for s in sessions_snapshot.values():
                dev_p += s.get("prompt", 0)
                dev_th += s.get("thinking", 0)
                dev_c += s.get("candidates", 0)
                all_dev_records.extend(s.get("records", []))

            dev_tot = dev_p + dev_th + dev_c
            dev_w = calculate_window_tracker(all_dev_records, ref_time=now_utc)
            dev_rec = format_recovery_info(dev_w, ref_time=now_utc)

            active_rt = rt_quotas_snapshot.get(active_google_account.lower().strip())
            google_live = None
            if active_rt:
                google_live = {
                    "account_email": active_google_account,
                    "subscription_tier": active_rt.get("subscription_tier", "Google AI Pro"),
                    "5h_pct_remaining": active_rt["gemini_5h"]["pct_remaining"],
                    "5h_reset_time": active_rt["gemini_5h"]["reset_time"],
                    "5h_reset_str": active_rt["gemini_5h"]["reset_str"],
                    "7d_pct_remaining": active_rt["gemini_weekly"]["pct_remaining"],
                    "7d_reset_time": active_rt["gemini_weekly"]["reset_time"],
                    "7d_reset_str": active_rt["gemini_weekly"]["reset_str"],
                    "last_updated": active_rt.get("last_updated", 0),
                }

            payload = {
                "database_meta": {
                    "schema_version": 2,
                    "app_name": "Gemini Token Counter & Live Quota Monitor",
                    "last_updated_utc": now_utc.isoformat(),
                    "active_google_account": active_google_account,
                    "google_realtime_quota_synced": bool(rt_quotas_snapshot),
                    "total_sessions_tracked": len(serialized_sessions),
                    "total_accounts_tracked": len(serialized_accounts),
                },
                "device_summary": {
                    "lifetime_tokens": {
                        "prompt": dev_p,
                        "thinking": dev_th,
                        "candidates": dev_c,
                        "total": dev_tot,
                        "prompt_pct": round((dev_p / dev_tot * 100) if dev_tot > 0 else 0.0, 2),
                        "thinking_pct": round((dev_th / dev_tot * 100) if dev_tot > 0 else 0.0, 2),
                        "candidates_pct": round((dev_c / dev_tot * 100) if dev_tot > 0 else 0.0, 2),
                    },
                    "quota_5h": {
                        "tokens_burned": dev_rec["tokens_5h"],
                        "prompt_tokens": dev_rec["prompt_5h"],
                        "thinking_tokens": dev_rec["thinking_5h"],
                        "candidate_tokens": dev_rec["candidates_5h"],
                        "reset_str": dev_rec["reset_5h_str"],
                        "pct_remaining": round(dev_rec["pct_5h_remaining"], 2),
                        "secs_remaining": dev_rec["secs_5h_remaining"],
                    },
                    "quota_7d": {
                        "tokens_burned": dev_rec["tokens_7d"],
                        "prompt_tokens": dev_rec["prompt_7d"],
                        "thinking_tokens": dev_rec["thinking_7d"],
                        "candidate_tokens": dev_rec["candidates_7d"],
                        "reset_str": dev_rec["reset_7d_str"],
                        "pct_remaining": round(dev_rec["pct_7d_remaining"], 2),
                        "secs_remaining": dev_rec["secs_7d_remaining"],
                    },
                    "burn_velocity": {
                        "tokens_15m": dev_rec["tokens_15m"],
                        "tokens_1h": dev_rec["tokens_1h"],
                        "burn_rate_hr": dev_rec["burn_rate_hr"],
                        "burn_rate_str": dev_rec["burn_rate_str"],
                    },
                    "google_live_quota": google_live,
                },
                "accounts": serialized_accounts,
                "sessions": serialized_sessions,
            }

            temp_file = self.ledger_file.with_suffix(".tmp")
            temp_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        
            max_attempts = 5
            for attempt in range(max_attempts):
                try:
                    temp_file.replace(self.ledger_file)
                    break
                except OSError:
                    if attempt == max_attempts - 1:
                        try:
                            self.ledger_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                            temp_file.unlink(missing_ok=True)
                        except Exception:
                            pass
                    else:
                        import time
                        time.sleep(0.05 * (2 ** attempt))
        except Exception:
                pass

        self._rotate_log_if_needed()

    def _rotate_log_if_needed(self):
        """Rotates account_ledger.jsonl when it exceeds 5000 lines to prevent unbounded growth."""
        try:
            if not self.log_file.exists():
                return
            content = self.log_file.read_text(encoding='utf-8', errors='ignore')
            lines = content.splitlines()
            if len(lines) > 5000:
                self.log_file.write_text('\n'.join(lines[-2500:]) + '\n', encoding='utf-8')
        except Exception:
            pass

    def update_session(
        self,
        session_id: str,
        account_email: str,
        stats: Dict[str, int],
        line_records: List[Tuple[Optional[datetime], int, int, int]],
        first_prompt: str = "",
        last_active: str = "Unknown",
        mtime: float = 0.0,
        size: int = 0,
        folder_path: str = "",
        file_path: str = "",
        force_account: bool = False
    ):
        """Updates or adds session token records into the in-memory ledger with per-account delta attribution."""
        with self._lock:
            existing = self.sessions.get(session_id)
            prompt = stats.get("prompt", 0)
            thinking = stats.get("thinking", 0)
            candidates = stats.get("candidates", 0)
            total = prompt + thinking + candidates

            if existing:
                if force_account and account_email and account_email not in ("Default", "Local"):
                    act = account_email
                else:
                    curr_act = str(existing.get("account", "")).strip()
                    if curr_act and curr_act not in ("Default", "Local", "None", "Unassigned"):
                        act = curr_act
                    else:
                        act = account_email if (account_email and account_email not in ("Default", "Local")) else (curr_act or "Default")

                account_usage = existing.setdefault("account_usage", {})
                if not account_usage:
                    old_acc = existing.get("account") or "Default"
                    account_usage[old_acc] = {
                        "prompt": existing.get("prompt", 0),
                        "thinking": existing.get("thinking", 0),
                        "candidates": existing.get("candidates", 0),
                        "total": existing.get("total", 0),
                        "records": list(existing.get("records", [])),
                    }

                delta_p = max(0, prompt - existing.get("prompt", 0))
                delta_th = max(0, thinking - existing.get("thinking", 0))
                delta_c = max(0, candidates - existing.get("candidates", 0))
                delta_tot = delta_p + delta_th + delta_c

                fp = first_prompt or existing.get("first_prompt", "")
                la = last_active if last_active != "Unknown" else existing.get("last_active", "Unknown")
                fld = folder_path or existing.get("folder", "")
                fl = file_path or existing.get("file", "")

                old_act = existing.get("account", "")
                account_changed = (old_act != act and act not in ("Default", "Local", ""))

                if len(account_usage) <= 1 and (not account_usage or act in account_usage):
                    # Single account session: directly assign exact session stats and line_records
                    u = account_usage.setdefault(act, {
                        "prompt": 0,
                        "thinking": 0,
                        "candidates": 0,
                        "total": 0,
                        "records": []
                    })
                    u["prompt"] = prompt
                    u["thinking"] = thinking
                    u["candidates"] = candidates
                    u["total"] = total
                    u["records"] = list(line_records)
                else:
                    # Multi-account session (user switched Google accounts within the same conversation session)
                    if delta_tot > 0:
                        u = account_usage.setdefault(act, {
                            "prompt": 0,
                            "thinking": 0,
                            "candidates": 0,
                            "total": 0,
                            "records": []
                        })
                        u["prompt"] += delta_p
                        u["thinking"] += delta_th
                        u["candidates"] += delta_c
                        u["total"] += delta_tot
                        prev_len = len(existing.get("records", []))
                        if len(line_records) > prev_len:
                            u["records"].extend(line_records[prev_len:])
                        elif len(line_records) == prev_len and u.get("records") and delta_tot > 0:
                            last_rec = u["records"][-1]
                            u["records"][-1] = (
                                last_rec[0],
                                last_rec[1] + delta_p,
                                last_rec[2] + delta_th,
                                last_rec[3] + delta_c
                            )
                        elif len(line_records) < prev_len:
                            u["records"] = list(line_records)

                if (existing["total"] != total or
                    existing["prompt"] != prompt or
                    existing["size"] != size or
                    len(existing["records"]) != len(line_records) or
                    existing["account"] != act):

                    existing.update({
                        "account": act,
                        "prompt": prompt,
                        "thinking": thinking,
                        "candidates": candidates,
                        "total": total,
                        "first_prompt": fp,
                        "title": fp or session_id,
                        "last_active": la,
                        "mtime": mtime,
                        "size": size,
                        "folder": fld,
                        "file": fl,
                        "records": line_records,
                        "account_usage": account_usage,
                    })
                    self._is_dirty = True

                    if account_changed:
                        self._append_to_log("account_switched", session_id, act, {
                            "previous_account": old_act or "Default",
                            "new_account": act,
                            "session_total": total,
                        })

                    if delta_tot > 0:
                        self._append_to_log("token_delta", session_id, act, {
                            "prompt_delta": delta_p,
                            "thinking_delta": delta_th,
                            "candidates_delta": delta_c,
                            "total_delta": delta_tot,
                            "session_total": total,
                        })
            else:
                act = account_email if (account_email and account_email not in ("Default", "Local", "")) else "Default"
                account_usage = {
                    act: {
                        "prompt": prompt,
                        "thinking": thinking,
                        "candidates": candidates,
                        "total": total,
                        "records": list(line_records),
                    }
                }
                self.sessions[session_id] = {
                    "session_id": session_id,
                    "account": act,
                    "prompt": prompt,
                    "thinking": thinking,
                    "candidates": candidates,
                    "total": total,
                    "first_prompt": first_prompt,
                    "title": first_prompt or session_id,
                    "last_active": last_active,
                    "mtime": mtime,
                    "size": size,
                    "folder": folder_path,
                    "file": file_path,
                    "records": line_records,
                    "account_usage": account_usage,
                }
                self._is_dirty = True
                if total > 0:
                    self._append_to_log("session_registered", session_id, act, {
                        "prompt": prompt,
                        "thinking": thinking,
                        "candidates": candidates,
                        "total": total,
                        "first_prompt": first_prompt[:60] if first_prompt else "",
                    })

    def get_account_report(self, account_email: str, ref_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Calculates 5h, 7d, and total usage strictly for the specified Google Account.
        Accurately mirrors Google server quotas without cross-account contamination or resetting previous account usage.
        """
        with self._lock:
            from core.account_manager import get_active_google_account
            active_act = (get_active_google_account() or "").strip().lower()
            target_act = (account_email or "").strip().lower()
            acc_records: List[Tuple[Optional[datetime], int, int, int]] = []
            total_prompt = 0
            total_thinking = 0
            total_candidates = 0
            matched_sessions = 0

            for s in self.sessions.values():
                acc_usage = s.get("account_usage")
                if acc_usage and isinstance(acc_usage, dict):
                    has_match = False
                    for act_k, udata in acc_usage.items():
                        k_clean = act_k.strip().lower()
                        is_default = not k_clean or k_clean in ("default", "local", "default / local account")
                        match = (
                            not target_act
                            or k_clean == target_act
                            or (target_act in ("default", "local", "default / local account") and is_default)
                            or (target_act == active_act and is_default)
                            or ('@' in k_clean and target_act == k_clean.split('@')[0])
                            or ('@' in target_act and k_clean == target_act.split('@')[0])
                        )
                        if match and udata.get("total", 0) > 0:
                            total_prompt += udata.get("prompt", 0)
                            total_thinking += udata.get("thinking", 0)
                            total_candidates += udata.get("candidates", 0)
                            acc_records.extend(udata.get("records", []))
                            has_match = True
                    if has_match:
                        matched_sessions += 1
                else:
                    s_act = s.get("account", "").strip().lower()
                    is_default_s = not s_act or s_act in ("default", "local", "default / local account")
                    match = (
                        not target_act
                        or s_act == target_act
                        or (target_act in ("default", "local", "default / local account") and is_default_s)
                        or (target_act == active_act and is_default_s)
                        or ('@' in s_act and target_act == s_act.split('@')[0])
                        or ('@' in target_act and s_act == target_act.split('@')[0])
                    )
                    if match:
                        total_prompt += s.get("prompt", 0)
                        total_thinking += s.get("thinking", 0)
                        total_candidates += s.get("candidates", 0)
                        acc_records.extend(s.get("records", []))
                        matched_sessions += 1

            grand_total = total_prompt + total_thinking + total_candidates
            window_tracker = calculate_window_tracker(acc_records, ref_time=ref_time)
            recovery = format_recovery_info(window_tracker, ref_time=ref_time)

            # Enrich with real-time Google quota if available
            lookup_act = target_act if (target_act and target_act not in ("default", "local", "active account", "active")) else active_act
            rt = self.realtime_quotas.get(lookup_act)
            if not rt:
                try:
                    rt = get_account_realtime_quota(lookup_act, ref_time=ref_time)
                    if rt:
                        self.realtime_quotas[lookup_act] = rt
                except Exception:
                    rt = None

            is_rt = False
            sub_tier = "Google AI Pro"
            if rt:
                is_rt = True
                sub_tier = rt.get("subscription_tier", "Google AI Pro")
                g5 = rt.get("gemini_5h", {})
                gw = rt.get("gemini_weekly", {})
                recovery["pct_5h_remaining"] = g5.get("pct_remaining", recovery["pct_5h_remaining"])
                recovery["reset_5h_str"] = g5.get("reset_str", recovery["reset_5h_str"])
                recovery["secs_5h_remaining"] = g5.get("secs_remaining", recovery["secs_5h_remaining"])
                recovery["recovery_5h_time"] = g5.get("reset_time") or recovery["recovery_5h_time"]

                recovery["pct_7d_remaining"] = gw.get("pct_remaining", recovery["pct_7d_remaining"])
                recovery["reset_7d_str"] = gw.get("reset_str", recovery["reset_7d_str"])
                recovery["secs_7d_remaining"] = gw.get("secs_remaining", recovery["secs_7d_remaining"])
                recovery["recovery_7d_time"] = gw.get("reset_time") or recovery["recovery_7d_time"]

            prompt_pct = (total_prompt / grand_total * 100) if grand_total > 0 else 0.0
            thinking_pct = (total_thinking / grand_total * 100) if grand_total > 0 else 0.0
            candidates_pct = (total_candidates / grand_total * 100) if grand_total > 0 else 0.0

            act_name = account_email or "Active Account"
            return {
                "is_all": True,
                "mode": "account",
                "account": act_name,
                "session_id": f"Account: {act_name} ({matched_sessions} chats)",
                "unique_sessions_count": matched_sessions,
                "total_sessions_found": len(self.sessions),
                "prompt": total_prompt,
                "thinking": total_thinking,
                "candidates": total_candidates,
                "total": grand_total,
                "prompt_pct": prompt_pct,
                "thinking_pct": thinking_pct,
                "candidates_pct": candidates_pct,
                "is_realtime_quota": is_rt,
                "subscription_tier": sub_tier,
                **recovery,
            }

    def get_device_report(self, ref_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Calculates global device grand total across all tracked sessions and accounts."""
        with self._lock:
            all_records: List[Tuple[Optional[datetime], int, int, int]] = []
            total_prompt = 0
            total_thinking = 0
            total_candidates = 0
            count = 0

            for s in self.sessions.values():
                total_prompt += s.get("prompt", 0)
                total_thinking += s.get("thinking", 0)
                total_candidates += s.get("candidates", 0)
                all_records.extend(s.get("records", []))
                count += 1

            grand_total = total_prompt + total_thinking + total_candidates
            window_tracker = calculate_window_tracker(all_records, ref_time=ref_time)
            recovery = format_recovery_info(window_tracker, ref_time=ref_time)

            from core.account_manager import get_active_google_account
            active_act = (get_active_google_account() or "").strip().lower()
            rt = self.realtime_quotas.get(active_act)
            if not rt:
                try:
                    rt = get_account_realtime_quota(active_act, ref_time=ref_time)
                    if rt:
                        self.realtime_quotas[active_act] = rt
                except Exception:
                    rt = None

            is_rt = False
            sub_tier = "Google AI Pro"
            if rt:
                is_rt = True
                sub_tier = rt.get("subscription_tier", "Google AI Pro")
                g5 = rt.get("gemini_5h", {})
                gw = rt.get("gemini_weekly", {})
                recovery["pct_5h_remaining"] = g5.get("pct_remaining", recovery["pct_5h_remaining"])
                recovery["reset_5h_str"] = g5.get("reset_str", recovery["reset_5h_str"])
                recovery["secs_5h_remaining"] = g5.get("secs_remaining", recovery["secs_5h_remaining"])
                recovery["recovery_5h_time"] = g5.get("reset_time") or recovery["recovery_5h_time"]

                recovery["pct_7d_remaining"] = gw.get("pct_remaining", recovery["pct_7d_remaining"])
                recovery["reset_7d_str"] = gw.get("reset_str", recovery["reset_7d_str"])
                recovery["secs_7d_remaining"] = gw.get("secs_remaining", recovery["secs_7d_remaining"])
                recovery["recovery_7d_time"] = gw.get("reset_time") or recovery["recovery_7d_time"]

            prompt_pct = (total_prompt / grand_total * 100) if grand_total > 0 else 0.0
            thinking_pct = (total_thinking / grand_total * 100) if grand_total > 0 else 0.0
            candidates_pct = (total_candidates / grand_total * 100) if grand_total > 0 else 0.0

            return {
                "is_all": True,
                "mode": "device",
                "session_id": f"All Sessions ({count} tracked)",
                "unique_sessions_count": count,
                "total_sessions_found": count,
                "prompt": total_prompt,
                "thinking": total_thinking,
                "candidates": total_candidates,
                "total": grand_total,
                "prompt_pct": prompt_pct,
                "thinking_pct": thinking_pct,
                "candidates_pct": candidates_pct,
                "is_realtime_quota": is_rt,
                "subscription_tier": sub_tier,
                **recovery,
            }

    def reassign_session_account(self, session_id: str, new_account_email: str) -> bool:
        """
        Manually reassigns a session to a specified Google Account in the ledger.
        Transfers current session lifetime tokens and historical records under the new account.
        """
        with self._lock:
            s = self.sessions.get(session_id)
            if not s:
                return False
            old_acc = s.get("account", "Default")
            new_acc = new_account_email.strip()
            
            from core.account_manager import is_valid_account_email
            if not new_acc or (not is_valid_account_email(new_acc) and new_acc.lower() not in ("default", "local", "default / local account")):
                return False

            s["account"] = new_acc
            acc_usage = s.setdefault("account_usage", {})
            if old_acc in acc_usage and old_acc != new_acc:
                acc_usage[new_acc] = acc_usage.pop(old_acc)
            elif new_acc not in acc_usage:
                acc_usage[new_acc] = {
                    "prompt": s.get("prompt", 0),
                    "thinking": s.get("thinking", 0),
                    "candidates": s.get("candidates", 0),
                    "total": s.get("total", 0),
                    "records": list(s.get("records", [])),
                }

            self._append_to_log("account_reassigned_manually", session_id, new_acc, {
                "previous_account": old_acc,
                "new_account": new_acc,
                "session_total": s.get("total", 0),
            })

            self._is_dirty = True
            self.flush_to_disk(force=True)
            return True

    def remove_session(self, session_id: str):
        """Removes a session from in-memory ledger."""
        with self._lock:
            if session_id in self.sessions:
                del self.sessions[session_id]
                self._is_dirty = True

    def remove_sessions(self, session_ids: List[str]):
        """Removes multiple sessions from in-memory ledger."""
        with self._lock:
            changed = False
            for sid in session_ids:
                if sid in self.sessions:
                    del self.sessions[sid]
                    changed = True
            if changed:
                self._is_dirty = True

    def clear_all(self):
        """Wipes all sessions from in-memory ledger."""
        with self._lock:
            self.sessions.clear()
            self._is_dirty = True

    def get_all_time_series_records(
        self,
        account_email: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> List[Tuple[Optional[datetime], int, int, int]]:
        """
        Extracts sorted (datetime, prompt, thinking, candidates) time-series records
        filtered by session_id, account_email, or globally for all sessions.
        """
        with self._lock:
            records: List[Tuple[Optional[datetime], int, int, int]] = []
            target_act = (account_email or "").strip().lower()

            if session_id and session_id.upper() not in ("ACTIVE", "ALL"):
                for sid, s in self.sessions.items():
                    if session_id.lower() in sid.lower():
                        acc_usage = s.get("account_usage")
                        if acc_usage and isinstance(acc_usage, dict) and target_act and target_act not in ("all", "active"):
                            for act_k, udata in acc_usage.items():
                                k_clean = act_k.strip().lower()
                                is_default = not k_clean or k_clean in ("default", "local", "default / local account")
                                match = (
                                    k_clean == target_act
                                    or (target_act in ("default", "local", "default / local account") and is_default)
                                    or ('@' in k_clean and target_act == k_clean.split('@')[0])
                                    or ('@' in target_act and k_clean == target_act.split('@')[0])
                                )
                                if match:
                                    records.extend(udata.get("records", []))
                        else:
                            s_act = s.get("account", "").strip().lower()
                            if not target_act or target_act in ("all", "active") or s_act == target_act or (target_act == "default" and not s_act):
                                records.extend(s.get("records", []))
                        break
            else:
                for s in self.sessions.values():
                    acc_usage = s.get("account_usage")
                    if acc_usage and isinstance(acc_usage, dict) and target_act and target_act not in ("all", "active"):
                        for act_k, udata in acc_usage.items():
                            k_clean = act_k.strip().lower()
                            is_default = not k_clean or k_clean in ("default", "local", "default / local account")
                            match = (
                                k_clean == target_act
                                or (target_act in ("default", "local", "default / local account") and is_default)
                                or ('@' in k_clean and target_act == k_clean.split('@')[0])
                                or ('@' in target_act and k_clean == target_act.split('@')[0])
                            )
                            if match:
                                records.extend(udata.get("records", []))
                    else:
                        s_act = s.get("account", "").strip().lower()
                        if not target_act or target_act == "all" or s_act == target_act or (target_act == "default" and not s_act):
                            records.extend(s.get("records", []))

            # Filter valid timestamps and sort chronologically
            valid = [r for r in records if r[0] is not None]
            valid.sort(key=lambda r: r[0])
            return valid

    def get_filtered_report(
        self,
        account_email: Optional[str] = "all",
        active_only: bool = False,
        session_id: Optional[str] = None,
        timeframe: str = "5h",
        active_session_id: Optional[str] = None,
        ref_time: Optional[datetime] = None,
        use_local_time: bool = True,
        active_only_5h: Optional[bool] = None,
        active_only_7d: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Unified multi-dimensional query calculator:
          Target Data = f(Account, Active Sessions Only, Time Window)

        Synchronously computes:
          1. Time-bucketed records and period totals for metric cards & graphs.
          2. Rolling 5h & 7d window quota burn and real-time Google recovery info.
          3. Filtered session list and matched interaction counts.
        """
        with self._lock:
            from core.analytics import bucket_records_by_time, calculate_analytics_summary
            from core.account_manager import get_active_google_account

            if active_only_5h is None:
                active_only_5h = active_only
            if active_only_7d is None:
                active_only_7d = active_only

            now_utc = ref_time if ref_time is not None else datetime.now(timezone.utc)
            if now_utc.tzinfo is None:
                now_utc = now_utc.replace(tzinfo=timezone.utc)

            active_act = (get_active_google_account() or "Default").strip().lower()

            acc_clean = (account_email or "").strip().lower()
            is_all_accounts = acc_clean in ("all", "all accounts", "★ all accounts", "*", "", None)

            if is_all_accounts:
                target_act = "all"
            elif acc_clean in ("active", "active user", "👤 active user"):
                target_act = active_act
            else:
                target_act = acc_clean.replace("👤", "").strip().lower()

            # Helper to resolve active session
            all_sessions = list(self.sessions.values())
            sorted_sess = sorted(all_sessions, key=lambda s: s.get("mtime", 0.0), reverse=True)

            def _session_matches_target(s_entry: Dict[str, Any]) -> bool:
                if is_all_accounts or target_act in ("all", "*", ""):
                    return True
                acc_u = s_entry.get("account_usage")
                if acc_u and isinstance(acc_u, dict):
                    for act_k, udata in acc_u.items():
                        k_clean = act_k.strip().lower()
                        is_def = not k_clean or k_clean in ("default", "local", "default / local account")
                        if (
                            k_clean == target_act
                            or (target_act in ("default", "local", "default / local account") and is_def)
                            or (target_act == active_act and is_def)
                            or ('@' in k_clean and target_act == k_clean.split('@')[0])
                            or ('@' in target_act and k_clean == target_act.split('@')[0])
                        ):
                            if udata.get("total", 0) > 0 or len(acc_u) == 1:
                                return True
                    return False
                else:
                    s_a = s_entry.get("account", "").strip().lower()
                    is_def = not s_a or s_a in ("default", "local", "default / local account")
                    return bool(
                        s_a == target_act
                        or (target_act in ("default", "local", "default / local account") and is_def)
                        or (target_act == active_act and is_def)
                        or ('@' in s_a and target_act == s_a.split('@')[0])
                        or ('@' in target_act and s_a == target_act.split('@')[0])
                    )

            if is_all_accounts:
                if active_session_id and active_session_id in self.sessions:
                    active_sessions = [self.sessions[active_session_id]]
                elif sorted_sess:
                    active_sessions = [sorted_sess[0]]
                else:
                    active_sessions = []
            else:
                target_session = None
                if active_session_id and active_session_id in self.sessions:
                    candidate = self.sessions[active_session_id]
                    if _session_matches_target(candidate):
                        target_session = candidate

                if not target_session:
                    for s in sorted_sess:
                        if _session_matches_target(s):
                            target_session = s
                            break

                if target_session:
                    active_sessions = [target_session]
                elif sorted_sess:
                    active_sessions = [sorted_sess[0]]
                else:
                    active_sessions = []

            # 1. Determine matching sessions for main timeframe metrics
            if session_id and session_id.upper() not in ("ALL", "ALL_CHATS", "ACTIVE_CHAT", "NONE", ""):
                target_sessions = [s for sid, s in self.sessions.items() if session_id.lower() in sid.lower()]
            elif active_only or session_id == "ACTIVE_CHAT":
                target_sessions = active_sessions
            else:
                target_sessions = all_sessions

            def _extract_records_for_sessions(sess_list: List[Dict]):
                extracted: List[Tuple[Optional[datetime], int, int, int]] = []
                p_tot = 0
                th_tot = 0
                c_tot = 0
                match_cnt = 0
                match_ids = []

                for s in sess_list:
                    sid = s.get("session_id", "")
                    acc_usage = s.get("account_usage")
                    sess_has_match = False
                    sess_p = 0
                    sess_th = 0
                    sess_c = 0
                    sess_recs: List[Tuple[Optional[datetime], int, int, int]] = []

                    if is_all_accounts:
                        sess_has_match = True
                        sess_p = s.get("prompt", 0)
                        sess_th = s.get("thinking", 0)
                        sess_c = s.get("candidates", 0)
                        sess_recs = s.get("records", [])
                    else:
                        if acc_usage and isinstance(acc_usage, dict):
                            for act_k, udata in acc_usage.items():
                                k_clean = act_k.strip().lower()
                                is_default = not k_clean or k_clean in ("default", "local", "default / local account")
                                match = (
                                    k_clean == target_act
                                    or (target_act in ("default", "local", "default / local account") and is_default)
                                    or (target_act == active_act and is_default)
                                    or ('@' in k_clean and target_act == k_clean.split('@')[0])
                                    or ('@' in target_act and k_clean == target_act.split('@')[0])
                                )
                                if match and (udata.get("total", 0) > 0 or len(acc_usage) == 1):
                                    sess_has_match = True
                                    sess_p += udata.get("prompt", 0)
                                    sess_th += udata.get("thinking", 0)
                                    sess_c += udata.get("candidates", 0)
                                    recs = udata.get("records", [])
                                    if not recs and s.get("records"):
                                        recs = s.get("records", [])
                                    sess_recs.extend(recs)
                        else:
                            s_act = s.get("account", "").strip().lower()
                            is_default_s = not s_act or s_act in ("default", "local", "default / local account")
                            match = (
                                s_act == target_act
                                or (target_act in ("default", "local", "default / local account") and is_default_s)
                                or (target_act == active_act and is_default_s)
                                or ('@' in s_act and target_act == s_act.split('@')[0])
                                or ('@' in target_act and s_act == target_act.split('@')[0])
                            )
                            if match:
                                sess_has_match = True
                                sess_p = s.get("prompt", 0)
                                sess_th = s.get("thinking", 0)
                                sess_c = s.get("candidates", 0)
                                sess_recs = s.get("records", [])

                        # Secondary fallback: if session account strictly matches target account and sess_recs is still empty
                        if not sess_has_match:
                            s_act = s.get("account", "").strip().lower()
                            if s_act == target_act or ('@' in s_act and target_act == s_act.split('@')[0]):
                                sess_has_match = True
                                sess_p = s.get("prompt", 0)
                                sess_th = s.get("thinking", 0)
                                sess_c = s.get("candidates", 0)
                                sess_recs = s.get("records", [])
                        elif not sess_recs and s.get("records"):
                            sess_recs.extend(s.get("records", []))

                    if sess_has_match:
                        match_cnt += 1
                        match_ids.append(sid)
                        p_tot += sess_p
                        th_tot += sess_th
                        c_tot += sess_c
                        extracted.extend(sess_recs)

                valid = [r for r in extracted if r[0] is not None]
                valid.sort(key=lambda r: r[0])
                return valid, p_tot, th_tot, c_tot, match_cnt, match_ids

            # 2. Extract records and lifetime tokens for main target scope
            valid_records, lifetime_prompt, lifetime_thinking, lifetime_candidates, matched_sessions_count, matching_session_ids = _extract_records_for_sessions(target_sessions)

            # 3. Extract records for 5H and 7D independent windows
            if session_id and session_id.upper() not in ("ALL", "ALL_CHATS", "ACTIVE_CHAT", "NONE", ""):
                valid_records_5h = valid_records
                valid_records_7d = valid_records
            else:
                sess_5h = active_sessions if active_only_5h else all_sessions
                sess_7d = active_sessions if active_only_7d else all_sessions
                valid_records_5h, _, _, _, _, _ = _extract_records_for_sessions(sess_5h)
                valid_records_7d, _, _, _, _, _ = _extract_records_for_sessions(sess_7d)

            # 4. Compute timeframe buckets and summary
            buckets = bucket_records_by_time(valid_records, timeframe=timeframe, ref_time=now_utc, use_local_time=use_local_time)
            summary = calculate_analytics_summary(buckets)

            period_prompt = summary.get("prompt_tokens", 0)
            period_thinking = summary.get("thinking_tokens", 0)
            period_candidates = summary.get("candidates_tokens", 0)
            period_total = summary.get("total_tokens", 0)
            prompt_pct = summary.get("prompt_pct", 0.0)
            thinking_pct = summary.get("thinking_pct", 0.0)
            candidates_pct = summary.get("candidates_pct", 0.0)

            # Fallback for missing or unbucketed historical records when viewing all-time
            lifetime_sum = lifetime_prompt + lifetime_thinking + lifetime_candidates
            if timeframe.lower().strip() in ("all", "all_time", "lifetime") and period_total < lifetime_sum:
                period_prompt = lifetime_prompt
                period_thinking = lifetime_thinking
                period_candidates = lifetime_candidates
                period_total = lifetime_sum
                if period_total > 0:
                    prompt_pct = round((period_prompt / period_total) * 100, 2)
                    thinking_pct = round((period_thinking / period_total) * 100, 2)
                    candidates_pct = round((period_candidates / period_total) * 100, 2)

            # 5. Compute rolling 5h / 7d recovery info independently
            window_tracker_5h = calculate_window_tracker(valid_records_5h, ref_time=now_utc)
            rec_5h = format_recovery_info(window_tracker_5h, ref_time=now_utc)

            window_tracker_7d = calculate_window_tracker(valid_records_7d, ref_time=now_utc)
            rec_7d = format_recovery_info(window_tracker_7d, ref_time=now_utc)

            recovery = {
                "tokens_5h": rec_5h.get("tokens_5h", 0),
                "prompt_5h": rec_5h.get("prompt_5h", 0),
                "thinking_5h": rec_5h.get("thinking_5h", 0),
                "candidates_5h": rec_5h.get("candidates_5h", 0),
                "reset_5h_str": rec_5h.get("reset_5h_str", "No recent usage"),
                "pct_5h_remaining": rec_5h.get("pct_5h_remaining", 0.0),
                "secs_5h_remaining": rec_5h.get("secs_5h_remaining", 0),
                "recovery_5h_time": rec_5h.get("recovery_5h_time"),

                "tokens_7d": rec_7d.get("tokens_7d", 0),
                "prompt_7d": rec_7d.get("prompt_7d", 0),
                "thinking_7d": rec_7d.get("thinking_7d", 0),
                "candidates_7d": rec_7d.get("candidates_7d", 0),
                "reset_7d_str": rec_7d.get("reset_7d_str", "No weekly usage"),
                "pct_7d_remaining": rec_7d.get("pct_7d_remaining", 0.0),
                "secs_7d_remaining": rec_7d.get("secs_7d_remaining", 0),
                "recovery_7d_time": rec_7d.get("recovery_7d_time"),

                "tokens_15m": rec_5h.get("tokens_15m", 0),
                "tokens_1h": rec_5h.get("tokens_1h", 0),
                "burn_rate_str": rec_5h.get("burn_rate_str", "Idle"),
            }

            # 6. Enrich with real-time Google account quota (only when viewing account-wide all-sessions)
            is_rt = False
            sub_tier = "Google AI Pro"
            if not is_all_accounts:
                lookup_act = target_act if (target_act not in ("default", "local", "active")) else active_act
                rt = None
                for k, v in self.realtime_quotas.items():
                    if k.lower() == lookup_act.lower() or ('@' in k and k.split('@')[0].lower() == lookup_act.lower()):
                        rt = v
                        break
                if not rt:
                    try:
                        rt = get_account_realtime_quota(lookup_act, ref_time=now_utc)
                        if rt:
                            self.realtime_quotas[lookup_act] = rt
                    except Exception:
                        rt = None

                if rt:
                    is_rt = True
                    sub_tier = rt.get("subscription_tier", "Google AI Pro")
                    g5 = rt.get("gemini_5h", {})
                    gw = rt.get("gemini_weekly", {})
                    if not (session_id and session_id.upper() not in ("ALL", "ALL_CHATS", "NONE", "")):
                        recovery["pct_5h_remaining"] = g5.get("pct_remaining", recovery["pct_5h_remaining"])
                        recovery["reset_5h_str"] = g5.get("reset_str", recovery["reset_5h_str"])
                        recovery["secs_5h_remaining"] = g5.get("secs_remaining", recovery["secs_5h_remaining"])
                        recovery["recovery_5h_time"] = g5.get("reset_time") or recovery["recovery_5h_time"]

                        recovery["pct_7d_remaining"] = gw.get("pct_remaining", recovery["pct_7d_remaining"])
                        recovery["reset_7d_str"] = gw.get("reset_str", recovery["reset_7d_str"])
                        recovery["secs_7d_remaining"] = gw.get("secs_remaining", recovery["secs_7d_remaining"])
                        recovery["recovery_7d_time"] = gw.get("reset_time") or recovery["recovery_7d_time"]

            # 7. Format clean badge text
            if is_all_accounts:
                badge_base = "All"
            else:
                u_short = target_act.split('@')[0] if '@' in target_act else target_act
                badge_base = f"👤 {u_short}"

            if active_only:
                badge_text = f"{badge_base} • Active"
            else:
                badge_text = f"{badge_base}"

            tf_upper = timeframe.upper()

            return {
                "prompt": period_prompt,
                "thinking": period_thinking,
                "candidates": period_candidates,
                "total": period_total,
                "prompt_total": period_prompt,
                "thinking_total": period_thinking,
                "candidates_total": period_candidates,
                "tokens_total": period_total,
                "tokens": period_total,
                "prompt_pct": prompt_pct,
                "thinking_pct": thinking_pct,
                "candidates_pct": candidates_pct,
                "lifetime_prompt": lifetime_prompt,
                "lifetime_thinking": lifetime_thinking,
                "lifetime_candidates": lifetime_candidates,
                "lifetime_total": lifetime_prompt + lifetime_thinking + lifetime_candidates,
                "account": "All" if is_all_accounts else target_act,
                "is_all": is_all_accounts,
                "active_only": active_only,
                "active_only_5h": active_only_5h,
                "active_only_7d": active_only_7d,
                "timeframe": timeframe,
                "timeframe_label": tf_upper,
                "session_id": session_id,
                "scope_badge": badge_text,
                "matched_sessions_count": matched_sessions_count,
                "matching_session_ids": matching_session_ids,
                "records": valid_records,
                "buckets": buckets,
                "summary": summary,
                "is_realtime_quota": is_rt,
                "subscription_tier": sub_tier,
                **recovery,
            }

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            accounts = set(s.get("account", "Default") for s in self.sessions.values())
            return {
                "tracked_sessions": len(self.sessions),
                "accounts_tracked": list(accounts),
                "total_tokens": sum(s.get("total", 0) for s in self.sessions.values()),
            }


# Singleton ledger instance
ledger = AccountLedger()
