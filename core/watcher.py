import time
import threading
from typing import Callable, List, Optional, Dict, Any
from pathlib import Path
from core.session_finder import get_all_session_files
from core.engine import get_single_session_report, parse_transcript_file_cached
from core.config import config


class SessionWatcher:
    """
    Ultra-lightweight background watcher.
    Uses smart stat-based change detection (0.0% CPU when idle) and cached parsing.
    """

    def __init__(self, on_update_callback: Optional[Callable[[Dict[str, Any], Dict[str, Any], List[Dict]], None]] = None):
        self.on_update_callback = on_update_callback
        self._running = False
        self._paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._wake_event = threading.Event()
        self._force_requested = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._poll_lock = threading.Lock()
        self._selected_session_id: Optional[str] = None  # If None or 'ACTIVE', auto-tracks latest
        self._mode_all: bool = False

        # State cache for fast comparison
        self._last_brain_mtimes: Dict[str, float] = {}
        self._last_realtime_mtimes: Dict[str, float] = {}
        self._last_active_mtime: float = 0.0
        self._last_active_size: int = 0
        self._last_sessions_fingerprint: tuple = ()
        self._last_full_scan_time: float = 0.0
        self._last_report_time: float = 0.0

        self.latest_single_report: Optional[Dict[str, Any]] = None
        self.latest_all_report: Optional[Dict[str, Any]] = None
        self.latest_account_report: Optional[Dict[str, Any]] = None
        self.latest_sessions: List[Dict] = []

    def is_paused(self) -> bool:
        """Returns True if background synchronization is currently suspended."""
        return self._paused

    def pause(self):
        """Puts the watcher into complete idle standby with 0% CPU and zero disk/subprocess activity."""
        with self._lock:
            if not self._paused:
                self._paused = True
                self._pause_event.clear()

    def resume(self):
        """Wakes the watcher from idle state and immediately triggers a fresh live sync."""
        with self._lock:
            if self._paused:
                self._paused = False
                self._pause_event.set()
        self.force_refresh()

    def set_target(self, session_id: Optional[str] = None, mode_all: bool = False):
        with self._lock:
            self._selected_session_id = session_id
            self._mode_all = mode_all
        if not self._paused:
            self.force_refresh()

    def start(self):
        if self._running:
            return
        self._running = True
        self._paused = False
        self._pause_event.set()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="TokenCounterWatcher")
        self._thread.start()

    def force_refresh(self):
        """Triggers an immediate background polling cycle without creating unmanaged thread thrashing."""
        if self._paused:
            return
        now = time.time()
        with self._lock:
            if now - getattr(self, "_last_force_refresh_time", 0.0) < 0.20:
                return
            self._last_force_refresh_time = now
            self._force_requested = True

        if self._thread and self._thread.is_alive():
            self._wake_event.set()
        else:
            threading.Thread(target=lambda: self._poll(force=True), daemon=True).start()

    def _poll(self, force: bool = False):
        if self._paused:
            return
        if not self._poll_lock.acquire(blocking=False):
            return
        try:
            now = time.time()
            custom_dirs = config.get("custom_brain_dirs") or []
            from core.session_finder import find_all_brain_dirs
            from core.account_manager import get_active_google_account, has_auth_credentials_changed, find_best_matching_account
            from core.ledger import ledger

            # 1. Quick stat on brain directories to detect new session folders instantly (<0.1ms)
            brain_dirs = find_all_brain_dirs(custom_dirs=custom_dirs)
            brain_changed = False
            current_brain_strs = set()
            for b_dir in brain_dirs:
                try:
                    b_str = str(b_dir)
                    current_brain_strs.add(b_str)
                    b_mtime = b_dir.stat().st_mtime
                    if self._last_brain_mtimes.get(b_str) != b_mtime:
                        brain_changed = True
                        self._last_brain_mtimes[b_str] = b_mtime
                except (OSError, PermissionError):
                    pass

            # Prune stale brain paths from cache
            for stale_k in list(self._last_brain_mtimes.keys()):
                if stale_k not in current_brain_strs:
                    self._last_brain_mtimes.pop(stale_k, None)

            # 2. Check real-time Google quota directory updates
            from core.realtime_quota import get_realtime_accounts_dirs, load_all_realtime_quotas
            rt_dirs = get_realtime_accounts_dirs()
            rt_changed = False
            current_rt_strs = set()
            for r_dir in rt_dirs:
                try:
                    r_str = str(r_dir)
                    current_rt_strs.add(r_str)
                    r_mtime = r_dir.stat().st_mtime
                    if self._last_realtime_mtimes.get(r_str) != r_mtime:
                        rt_changed = True
                        self._last_realtime_mtimes[r_str] = r_mtime
                except (OSError, PermissionError):
                    pass

            # Prune stale realtime quota paths from cache
            for stale_rt in list(self._last_realtime_mtimes.keys()):
                if stale_rt not in current_rt_strs:
                    self._last_realtime_mtimes.pop(stale_rt, None)

            # 3. Rescan session files if forced, brain changed, real-time changed, startup, or every 30s fallback
            is_full_scan_due = force or brain_changed or rt_changed or not self.latest_sessions or (now - self._last_full_scan_time > 30.0)

            if is_full_scan_due:
                sessions = get_all_session_files(custom_dirs=custom_dirs)
                self._last_full_scan_time = now
                self.latest_sessions = sessions
            else:
                sessions = self.latest_sessions

            with self._lock:
                target_id = self._selected_session_id
                mode_all = self._mode_all

            if not sessions:
                empty_report = {
                    "is_all": mode_all,
                    "session_id": "No Sessions Found",
                    "folder": "",
                    "file": "",
                    "last_active": "N/A",
                    "mtime": 0,
                    "size": 0,
                    "prompt": 0,
                    "thinking": 0,
                    "candidates": 0,
                    "total": 0,
                    "prompt_pct": 0,
                    "thinking_pct": 0,
                    "candidates_pct": 0,
                    "tokens_5h": 0,
                    "reset_5h_str": "No active sessions",
                    "pct_5h_remaining": 0,
                    "secs_5h_remaining": 0,
                    "tokens_7d": 0,
                    "reset_7d_str": "No active sessions",
                    "pct_7d_remaining": 0,
                    "secs_7d_remaining": 0,
                }
                self.latest_single_report = empty_report
                self.latest_all_report = empty_report
                self.latest_account_report = empty_report
                if self.on_update_callback:
                    self.on_update_callback(empty_report, empty_report, [])
                return

            # Target session resolution
            target_session = sessions[0]
            if target_id and target_id.upper() not in ("ACTIVE", "ACTIVE_CHAT"):
                matched = next((s for s in sessions if target_id.lower() in s["session_id"].lower()), None)
                if matched:
                    target_session = matched

            # 4. Live stat check across active / recent session files
            current_live_fingerprint = []
            files_changed = False
            check_sessions = list(sessions[:15])
            if target_session and target_session not in check_sessions:
                check_sessions.append(target_session)

            for s in check_sessions:  # Check recent sessions + active target (<1ms)
                try:
                    f_stat = Path(s["file"]).stat()
                    f_mtime, f_size = f_stat.st_mtime, f_stat.st_size
                    if f_mtime != s.get("mtime", 0.0) or f_size != s.get("size", 0):
                        s["mtime"] = f_mtime
                        s["size"] = f_size
                        files_changed = True
                    current_live_fingerprint.append((s["session_id"], f_mtime, f_size))
                except OSError:
                    current_live_fingerprint.append((s["session_id"], s.get("mtime", 0.0), s.get("size", 0)))

            auth_changed = has_auth_credentials_changed()
            live_fp_tuple = tuple(current_live_fingerprint)

            time_since_report = now - self._last_report_time
            is_periodic_report_due = (time_since_report >= 30.0)

            has_changed = (
                force or
                brain_changed or
                files_changed or
                auth_changed or
                rt_changed or
                is_periodic_report_due or
                live_fp_tuple != self._last_sessions_fingerprint
            )

            if not has_changed and self.latest_account_report is not None:
                return

            self._last_sessions_fingerprint = live_fp_tuple
            self._last_report_time = now

            # Detect active Google account
            active_account = get_active_google_account() or "Default"

            # Periodically sync real-time Google quotas into the ledger
            if rt_changed or is_full_scan_due:
                try:
                    ledger.realtime_quotas = load_all_realtime_quotas()
                except Exception:
                    pass

            # Parse and sync all discovered session log files into the ledger
            for idx, s in enumerate(sessions):
                stats, records, fp = parse_transcript_file_cached(s["file"])
                sid = s.get("session_id", "unknown")
                existing_acc = ledger.get_session_account(sid)

                # The active session (idx == 0) dynamically tracks the currently active logged-in Google account
                # Historical sessions (idx > 0) retain their locked owner to preserve historical isolation.
                # If an unassigned historical session is found, correlate its timestamp with known account activity ranges.
                if idx == 0 and active_account and active_account not in ("Default", "Local"):
                    sess_account = active_account
                    force_acc = True
                elif not existing_acc or existing_acc in ("Default", "Local", "None", "Unassigned"):
                    sess_account = find_best_matching_account(s.get("mtime", 0.0), fallback_account=active_account)
                    force_acc = False
                else:
                    sess_account = existing_acc
                    force_acc = False

                ledger.update_session(
                    session_id=sid,
                    account_email=sess_account,
                    stats=stats,
                    line_records=records,
                    first_prompt=fp,
                    last_active=s.get("last_active_str", "Unknown"),
                    mtime=s.get("mtime", 0.0),
                    size=s.get("size", 0),
                    folder_path=str(s.get("folder", "")),
                    file_path=str(s.get("file", "")),
                    force_account=force_acc
                )
                s["tokens"] = stats.get("prompt", 0) + stats.get("thinking", 0) + stats.get("candidates", 0)
                s["account"] = sess_account
                if fp:
                    s["first_prompt"] = fp
                    s["title"] = fp

            # Re-sort sessions after parsing in case mtimes updated
            sessions.sort(key=lambda s: s.get("mtime", 0.0), reverse=True)

            # Generate reports using cached engine
            account_report = ledger.get_account_report(active_account)
            single_report = get_single_session_report(target_session, account_email=active_account)
            all_report = ledger.get_device_report()

            self.latest_single_report = single_report
            self.latest_all_report = all_report
            self.latest_account_report = account_report

            if mode_all:
                active_report = all_report
            elif target_id and target_id not in ("ALL_CHATS", "all", None):
                active_report = single_report
            else:
                active_report = account_report

            if self.on_update_callback:
                try:
                    self.on_update_callback(active_report, all_report, sessions)
                except Exception:
                    pass

        except Exception:
            pass
        finally:
            self._poll_lock.release()

    def _run_loop(self):
        # Initial poll on start
        self._poll(force=True)
        last_flush_check = time.time()

        while self._running:
            # If paused, wait indefinitely until resumed or stopped (0% CPU / zero disk activity)
            if self._paused:
                self._pause_event.wait(timeout=1.0)
                continue

            interval = max(1, int(config.get("refresh_interval_sec") or 3))
            woken = self._wake_event.wait(timeout=interval)
            if woken:
                self._wake_event.clear()

            if self._running and not self._paused:
                force_flag = woken or self._force_requested
                self._force_requested = False
                self._poll(force=force_flag)

                # Periodic debounced disk flush every 30 seconds (zero SSD wear)
                now = time.time()
                if now - last_flush_check >= 30.0:
                    last_flush_check = now
                    try:
                        from core.ledger import ledger
                        ledger.flush_to_disk()
                    except Exception:
                        pass

    def stop(self):
        self._running = False
        self._pause_event.set()
        self._wake_event.set()
        try:
            from core.ledger import ledger
            ledger.flush_to_disk(force=True)
        except Exception:
            pass
