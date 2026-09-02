import os
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any


# In-memory caches for realtime directories and quota data to guarantee 0% CPU and zero UI thread stalls
_CACHED_REALTIME_DIRS: Optional[List[Path]] = None
_LAST_REALTIME_DIRS_TIME: float = 0.0

_CACHED_REALTIME_QUOTAS: Optional[Dict[str, Dict[str, Any]]] = None
_LAST_REALTIME_QUOTAS_TIME: float = 0.0


def clear_realtime_quota_cache():
    """Clears all cached realtime account directories and quota payloads."""
    global _CACHED_REALTIME_DIRS, _LAST_REALTIME_DIRS_TIME, _CACHED_REALTIME_QUOTAS, _LAST_REALTIME_QUOTAS_TIME
    _CACHED_REALTIME_DIRS = None
    _LAST_REALTIME_DIRS_TIME = 0.0
    _CACHED_REALTIME_QUOTAS = None
    _LAST_REALTIME_QUOTAS_TIME = 0.0


def get_realtime_accounts_dirs(force_refresh: bool = False) -> List[Path]:
    """
    Discovers potential candidate directories for .antigravity_tools/accounts
    with multi-platform, multi-drive, and WSL2 support.
    Caches result for 60 seconds.
    """
    global _CACHED_REALTIME_DIRS, _LAST_REALTIME_DIRS_TIME
    import time
    now = time.time()

    if not force_refresh and _CACHED_REALTIME_DIRS is not None and (now - _LAST_REALTIME_DIRS_TIME < 60.0):
        return list(_CACHED_REALTIME_DIRS)

    candidate_dirs: List[Path] = []

    # 1. Standard user home
    candidate_dirs.append(Path.home() / ".antigravity_tools" / "accounts")

    # 2. Windows environment variables
    for env_var in ["USERPROFILE", "APPDATA", "LOCALAPPDATA"]:
        val = os.environ.get(env_var)
        if val:
            base = Path(val)
            candidate_dirs.append(base / ".antigravity_tools" / "accounts")
            candidate_dirs.append(base.parent / ".antigravity_tools" / "accounts")

    # 3. Dedicated system paths
    if os.name == "nt":
        sys_drive = os.environ.get("SystemDrive", "C:")
        candidate_dirs.append(Path(f"{sys_drive}\\Users\\{os.environ.get('USERNAME', '')}\\.antigravity_tools\\accounts"))

    # Return only directories that exist and are accessible, without duplicates
    existing_dirs = []
    seen = set()
    for d in candidate_dirs:
        try:
            resolved = d.resolve()
            if resolved.exists() and resolved.is_dir() and str(resolved) not in seen:
                seen.add(str(resolved))
                existing_dirs.append(resolved)
        except Exception:
            continue

    _CACHED_REALTIME_DIRS = list(existing_dirs)
    _LAST_REALTIME_DIRS_TIME = now
    return existing_dirs


def format_time_until_reset(reset_iso_str: Optional[str], ref_time: Optional[datetime] = None) -> Tuple[int, str]:
    """
    Calculates remaining seconds and formats a human-friendly countdown string (e.g. 'in 3h 45m', 'in 5d 15h').
    """
    if not reset_iso_str:
        return 0, "Reset"

    try:
        now = ref_time if ref_time is not None else datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        clean_iso = reset_iso_str.replace("Z", "+00:00")
        reset_dt = datetime.fromisoformat(clean_iso)
        if reset_dt.tzinfo is None:
            reset_dt = reset_dt.replace(tzinfo=timezone.utc)

        secs = max(0, int((reset_dt - now).total_seconds()))
        if secs <= 0:
            return 0, "Fully refreshed"

        days = secs // 86400
        hours = (secs % 86400) // 3600
        mins = (secs % 3600) // 60

        if days > 0:
            return secs, f"in {days}d {hours:02d}h"
        elif hours > 0:
            return secs, f"in {hours}h {mins:02d}m"
        else:
            return secs, f"in {mins}m"
    except Exception:
        return 0, "Reset"


def parse_account_quota_file(file_path: Path, ref_time: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """
    Parses a single account JSON file from .antigravity_tools/accounts.
    Extracts the account email and quota_groups block (Gemini & Claude/GPT limits).
    """
    try:
        if not file_path.exists() or not file_path.is_file():
            return None

        content = file_path.read_text(encoding="utf-8", errors="ignore")
        data = json.loads(content)
        if not isinstance(data, dict):
            return None

        # 1. Extract email
        email = str(data.get("email", "")).strip().lower()
        if not email:
            email = str(data.get("token", {}).get("email", "")).strip().lower()
        if not email and "@" in file_path.stem:
            email = file_path.stem.lower().strip()
        if not email or "@" not in email:
            return None

        # 2. Extract quota_groups block
        quota = data.get("quota", {}) if isinstance(data.get("quota"), dict) else data
        quota_groups = quota.get("quota_groups", [])
        if not isinstance(quota_groups, list):
            quota_groups = []

        # Default quota values
        gemini_5h_pct = 100.0
        gemini_5h_reset_time = None
        gemini_5h_desc = ""

        gemini_weekly_pct = 100.0
        gemini_weekly_reset_time = None
        gemini_weekly_desc = ""

        p3_5h_pct = 100.0
        p3_5h_reset_time = None
        p3_weekly_pct = 100.0
        p3_weekly_reset_time = None

        for group in quota_groups:
            if not isinstance(group, dict):
                continue
            group_name = str(group.get("display_name", "")).lower()
            buckets = group.get("buckets", [])
            if not isinstance(buckets, list):
                continue

            for b in buckets:
                if not isinstance(b, dict):
                    continue
                b_id = str(b.get("bucket_id", "")).lower()
                b_window = str(b.get("window", "")).lower()
                rem_frac = b.get("remaining_fraction", 1.0)
                rem_pct = max(0.0, min(100.0, float(rem_frac) * 100.0))
                r_time = b.get("reset_time")
                desc = b.get("description", "")

                if "gemini" in group_name or "gemini" in b_id:
                    if b_window == "5h" or "5h" in b_id:
                        gemini_5h_pct = rem_pct
                        gemini_5h_reset_time = r_time
                        gemini_5h_desc = desc
                    elif b_window == "weekly" or "weekly" in b_id:
                        gemini_weekly_pct = rem_pct
                        gemini_weekly_reset_time = r_time
                        gemini_weekly_desc = desc
                elif "claude" in group_name or "gpt" in group_name or "3p" in b_id:
                    if b_window == "5h" or "5h" in b_id:
                        p3_5h_pct = rem_pct
                        p3_5h_reset_time = r_time
                    elif b_window == "weekly" or "weekly" in b_id:
                        p3_weekly_pct = rem_pct
                        p3_weekly_reset_time = r_time

        # Calculate human-readable countdowns
        secs_5h, reset_5h_countdown = format_time_until_reset(gemini_5h_reset_time, ref_time=ref_time)
        secs_7d, reset_7d_countdown = format_time_until_reset(gemini_weekly_reset_time, ref_time=ref_time)

        reset_5h_str = f"{reset_5h_countdown} ({gemini_5h_pct:.1f}% remaining)" if secs_5h > 0 else "Fully refreshed"
        reset_7d_str = f"{reset_7d_countdown} ({gemini_weekly_pct:.1f}% remaining)" if secs_7d > 0 else "Fully refreshed"

        return {
            "email": email,
            "gemini_5h": {
                "pct_remaining": gemini_5h_pct,
                "reset_time": gemini_5h_reset_time,
                "reset_countdown": reset_5h_countdown,
                "reset_str": reset_5h_str,
                "secs_remaining": secs_5h,
                "description": gemini_5h_desc,
            },
            "gemini_weekly": {
                "pct_remaining": gemini_weekly_pct,
                "reset_time": gemini_weekly_reset_time,
                "reset_countdown": reset_7d_countdown,
                "reset_str": reset_7d_str,
                "secs_remaining": secs_7d,
                "description": gemini_weekly_desc,
            },
            "third_party_5h": {
                "pct_remaining": p3_5h_pct,
                "reset_time": p3_5h_reset_time,
            },
            "third_party_weekly": {
                "pct_remaining": p3_weekly_pct,
                "reset_time": p3_weekly_reset_time,
            },
            "quota_groups": quota_groups,
        }
    except Exception:
        return None


def load_all_realtime_quotas(ref_time: Optional[datetime] = None, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Reads all account JSON files from available .antigravity_tools/accounts directories.
    Returns a dictionary mapping lower-case account email to parsed quota metrics.
    Caches results for 30 seconds for 0% CPU and zero UI stutter.
    """
    global _CACHED_REALTIME_QUOTAS, _LAST_REALTIME_QUOTAS_TIME
    import time
    now = time.time()

    if not force_refresh and _CACHED_REALTIME_QUOTAS is not None and (now - _LAST_REALTIME_QUOTAS_TIME < 30.0) and ref_time is None:
        return dict(_CACHED_REALTIME_QUOTAS)

    results: Dict[str, Dict[str, Any]] = {}
    dirs = get_realtime_accounts_dirs(force_refresh=force_refresh)

    for d in dirs:
        try:
            for p in d.glob("*.json"):
                parsed = parse_account_quota_file(p, ref_time=ref_time)
                if parsed and parsed.get("email"):
                    email_key = parsed["email"].lower().strip()
                    # Prefer newer or already parsed
                    if email_key not in results or parsed.get("last_updated", 0) >= results[email_key].get("last_updated", 0):
                        results[email_key] = parsed
        except Exception:
            continue

    if ref_time is None:
        _CACHED_REALTIME_QUOTAS = dict(results)
        _LAST_REALTIME_QUOTAS_TIME = now

    return results


def get_account_realtime_quota(email: str, ref_time: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """
    Retrieves real-time quota data for a specific account email or username prefix, or returns None if not found.
    """
    if not email:
        return None
    em_clean = email.lower().strip()
    all_quotas = load_all_realtime_quotas(ref_time=ref_time)
    if em_clean in all_quotas:
        return all_quotas[em_clean]
    for k, v in all_quotas.items():
        if k == em_clean or ('@' in k and k.split('@')[0] == em_clean) or ('@' in em_clean and em_clean.split('@')[0] == k):
            return v
    return None
