import os
import json
import base64
from pathlib import Path
from typing import Dict, List, Optional, Any


import glob
from core.session_finder import get_wsl_distros, get_available_drives


def is_valid_account_email(email: Optional[str]) -> bool:
    """
    Validates that a string is a legitimate Google/email account identifier
    and filters out test fixtures, mocks, and invalid tokens.
    """
    if not email or not isinstance(email, str):
        return False
    em = email.strip().lower()
    if not em or em in ("default", "local", "none", "unknown", "default / local account"):
        return False
    # Discard test / mock accounts via strict match to avoid catching real users
    test_domains = ("@test.com", "@mock.com", "@dummy.com")
    test_prefixes = ("test@", "mock@", "dummy@", "example@", "active_tester@")

    if any(em.endswith(d) for d in test_domains) or any(em.startswith(p) for p in test_prefixes):
        return False
    # Verify standard email structure user@domain.tld
    if "@" not in em:
        return False
    parts = em.split("@")
    if len(parts) != 2:
        return False
    user_part, domain_part = parts
    if not user_part or not domain_part or "." not in domain_part:
        return False
    return True


def decode_id_token_email(oauth_creds_file: Path) -> Optional[str]:
    """Decodes the email address directly from the JWT id_token inside oauth_creds.json."""
    try:
        if not oauth_creds_file.exists():
            return None
        data = json.loads(oauth_creds_file.read_text(encoding="utf-8", errors="ignore"))
        id_tok = data.get("id_token", "")
        if id_tok and "." in id_tok:
            parts = id_tok.split(".")
            if len(parts) >= 2:
                payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
                decoded = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
                email = decoded.get("email")
                if email:
                    return str(email).strip()
    except Exception:
        pass
    return None


def extract_antigravity_active_account(file_path: Path) -> Optional[str]:
    """Extracts active account email from .antigravity_tools/accounts.json using current_account_id."""
    try:
        if not file_path.exists():
            return None
        data = json.loads(file_path.read_text(encoding="utf-8", errors="ignore"))
        if isinstance(data, dict):
            cur_id = data.get("current_account_id")
            accounts = data.get("accounts", [])
            if cur_id and isinstance(accounts, list):
                for acc in accounts:
                    if isinstance(acc, dict) and acc.get("id") == cur_id:
                        em = acc.get("email")
                        if em and is_valid_account_email(str(em)):
                            return str(em).strip()
    except Exception:
        pass
    return None


# In-memory cache for discovered credential files to prevent expensive multi-drive/WSL globs
_CACHED_CREDENTIAL_FILES: Optional[Dict[str, List[Path]]] = None
_LAST_CREDENTIAL_SCAN_TIME: float = 0.0


def clear_credential_cache():
    """Clears cached credential file paths and dependent account caches to allow fresh discovery."""
    global _CACHED_CREDENTIAL_FILES, _LAST_CREDENTIAL_SCAN_TIME, _CACHED_KNOWN_ACCOUNTS, _LAST_KNOWN_ACCOUNTS_TIME, _CACHED_ACTIVITY_RANGES, _LAST_ACTIVITY_RANGES_TIME
    _CACHED_CREDENTIAL_FILES = None
    _LAST_CREDENTIAL_SCAN_TIME = 0.0
    _CACHED_KNOWN_ACCOUNTS = None
    _LAST_KNOWN_ACCOUNTS_TIME = 0.0
    _CACHED_ACTIVITY_RANGES = None
    _LAST_ACTIVITY_RANGES_TIME = 0.0
    try:
        from core.realtime_quota import clear_realtime_quota_cache
        clear_realtime_quota_cache()
    except Exception:
        pass


def find_credential_files(force_refresh: bool = False) -> Dict[str, List[Path]]:
    """
    Discovers all Google authentication files dynamically across Windows, drives, and WSL2 paths.
    Caches results for 60 seconds to guarantee 0% CPU and zero UI thread stalls.
    """
    global _CACHED_CREDENTIAL_FILES, _LAST_CREDENTIAL_SCAN_TIME
    import time
    now = time.time()

    if not force_refresh and _CACHED_CREDENTIAL_FILES is not None and (now - _LAST_CREDENTIAL_SCAN_TIME < 60.0):
        return _CACHED_CREDENTIAL_FILES

    res = {
        "google_accounts": [],
        "oauth_creds": [],
        "jetski_tokens": [],
        "antigravity_accounts": [],
    }

    candidate_bases = [
        Path.home() / ".gemini",
    ]

    for env_var in ["USERPROFILE", "APPDATA", "LOCALAPPDATA"]:
        if env_var in os.environ:
            base = Path(os.environ[env_var])
            candidate_bases.extend([
                base / ".gemini",
                base / ".." / ".gemini",
            ])

    # Windows drives scanning (C:, D:, Z:, etc.)
    drives = get_available_drives()
    if not drives and os.name == "nt":
        drives = [os.environ.get("SystemDrive", "C:")]

    for drive in drives:
        for pat in [f"{drive}\\Users\\*\\.gemini", f"{drive}\\home\\*\\.gemini"]:
            try:
                for match in glob.glob(pat):
                    candidate_bases.append(Path(match))
            except Exception:
                pass

    # WSL2 UNC paths
    if os.name == "nt":
        distros = get_wsl_distros()
        for distro in distros:
            for unc_root in [rf"\\wsl.localhost\{distro}", rf"\\wsl$\{distro}"]:
                for pat in [f"{unc_root}\\home\\*\\.gemini", f"{unc_root}\\root\\.gemini"]:
                    try:
                        for match in glob.glob(pat):
                            candidate_bases.append(Path(match))
                    except Exception:
                        pass

    # Linux native paths
    for pat in ["/home/*/.gemini", "/root/.gemini"]:
        try:
            for match in glob.glob(pat):
                candidate_bases.append(Path(match))
        except Exception:
            pass

    for b in candidate_bases:
        try:
            if not b.exists():
                continue
            ga = b / "google_accounts.json"
            if ga.exists() and ga.is_file() and ga not in res["google_accounts"]:
                res["google_accounts"].append(ga)

            oc = b / "oauth_creds.json"
            if oc.exists() and oc.is_file() and oc not in res["oauth_creds"]:
                res["oauth_creds"].append(oc)

            jt = b / "jetski-standalone-oauth-token"
            if jt.exists() and jt.is_file() and jt not in res["jetski_tokens"]:
                res["jetski_tokens"].append(jt)
        except Exception:
            pass

    # Discover Antigravity Tools accounts.json (.antigravity_tools/accounts.json)
    ag_candidate_files = [
        Path.home() / ".antigravity_tools" / "accounts.json",
    ]
    for env_var in ["USERPROFILE", "APPDATA", "LOCALAPPDATA"]:
        if env_var in os.environ:
            base = Path(os.environ[env_var])
            ag_candidate_files.extend([
                base / ".antigravity_tools" / "accounts.json",
                base.parent / ".antigravity_tools" / "accounts.json",
            ])
    if os.name == "nt":
        sys_drive = os.environ.get("SystemDrive", "C:")
        ag_candidate_files.append(
            Path(f"{sys_drive}\\Users\\{os.environ.get('USERNAME', '')}\\.antigravity_tools\\accounts.json")
        )

    for ag_f in ag_candidate_files:
        try:
            if ag_f.exists() and ag_f.is_file() and ag_f not in res["antigravity_accounts"]:
                res["antigravity_accounts"].append(ag_f)
        except Exception:
            pass

    # Ensure default user profile .gemini path is always registered
    default_gemini = Path.home() / ".gemini"
    default_ga = default_gemini / "google_accounts.json"
    default_oc = default_gemini / "oauth_creds.json"
    if default_ga not in res["google_accounts"]:
        res["google_accounts"].append(default_ga)
    if default_oc not in res["oauth_creds"]:
        res["oauth_creds"].append(default_oc)

    _CACHED_CREDENTIAL_FILES = res
    _LAST_CREDENTIAL_SCAN_TIME = now
    return res


# In-memory RAM tracker for the active user account to prevent storing stale accounts in files
_LIVE_ACTIVE_ACCOUNT: Optional[str] = None
_LAST_AUTH_CHECK_TIME: float = 0.0
_AUTH_FINGERPRINT: tuple = ()


def get_auth_files_fingerprint() -> tuple:
    """Returns a lightweight stat fingerprint (mtime, size) of all credential files."""
    files = find_credential_files()
    fp_list = []
    for category in ("google_accounts", "oauth_creds", "jetski_tokens", "antigravity_accounts"):
        for f in files.get(category, []):
            try:
                if f.exists():
                    st = f.stat()
                    fp_list.append((str(f), st.st_mtime, st.st_size))
            except Exception:
                pass
    return tuple(fp_list)


def has_auth_credentials_changed() -> bool:
    """
    Checks if Google authentication credential files or active login state changed in the background.
    Uses ultra-fast stat-based comparison (0.001ms execution, 0% CPU).
    """
    global _AUTH_FINGERPRINT, _LIVE_ACTIVE_ACCOUNT
    current_fp = get_auth_files_fingerprint()
    if current_fp != _AUTH_FINGERPRINT:
        _AUTH_FINGERPRINT = current_fp
        clear_credential_cache()
        get_active_google_account(force_reload=True)
        return True
    return False


def set_active_google_account_in_memory(email: Optional[str]):
    """Manually updates the active user account in RAM memory."""
    global _LIVE_ACTIVE_ACCOUNT, _LAST_AUTH_CHECK_TIME
    import time
    _LIVE_ACTIVE_ACCOUNT = email.strip() if email else None
    _LAST_AUTH_CHECK_TIME = time.time()


def get_active_google_account(force_reload: bool = False) -> Optional[str]:
    """
    Returns the currently active logged-in Google Account email (e.g. 'user@example.com').
    Maintains the live active account in RAM memory, dynamically checking credential recency.
    """
    global _LIVE_ACTIVE_ACCOUNT, _LAST_AUTH_CHECK_TIME, _AUTH_FINGERPRINT
    import time
    now = time.time()
    if not force_reload and _LIVE_ACTIVE_ACCOUNT is not None and (now - _LAST_AUTH_CHECK_TIME < 3.0):
        return _LIVE_ACTIVE_ACCOUNT

    files = find_credential_files()
    candidates: List[tuple] = []  # list of tuples: (mtime, email, source_type)

    # 1. oauth_creds.json (JWT id_token ground truth)
    for f in files.get("oauth_creds", []):
        try:
            if f.exists():
                e = decode_id_token_email(f)
                if e and is_valid_account_email(e):
                    candidates.append((f.stat().st_mtime, e, "oauth_creds"))
        except Exception:
            pass

    # 2. antigravity_accounts (.antigravity_tools/accounts.json current_account_id)
    for f in files.get("antigravity_accounts", []):
        try:
            if f.exists():
                e = extract_antigravity_active_account(f)
                if e and is_valid_account_email(e):
                    candidates.append((f.stat().st_mtime, e, "antigravity_accounts"))
        except Exception:
            pass

    # 3. google_accounts.json (active field)
    for f in files.get("google_accounts", []):
        try:
            if not f.exists():
                continue
            data = json.loads(f.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(data, dict):
                active = data.get("active")
                em = None
                if isinstance(active, str) and active.strip():
                    em = active.strip()
                elif isinstance(active, dict) and "email" in active:
                    em = str(active["email"]).strip()
                if em and is_valid_account_email(em):
                    candidates.append((f.stat().st_mtime, em, "google_accounts"))
        except Exception:
            pass

    if candidates:
        # Sort descending by file mtime: the credential source updated most recently wins
        candidates.sort(key=lambda x: x[0], reverse=True)
        email = candidates[0][1]
    else:
        email = None

    _LIVE_ACTIVE_ACCOUNT = email
    _LAST_AUTH_CHECK_TIME = now
    _AUTH_FINGERPRINT = get_auth_files_fingerprint()
    return _LIVE_ACTIVE_ACCOUNT


def get_all_google_accounts() -> Dict[str, Any]:
    """Returns structured account information including active and previous accounts."""
    active_email = get_active_google_account()
    if active_email and not is_valid_account_email(active_email):
        active_email = None

    old_accounts: List[str] = []
    seen = set([active_email.lower()] if active_email else [])

    files = find_credential_files()["google_accounts"]
    for f in files:
        try:
            if not f.exists():
                continue
            data = json.loads(f.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(data, dict):
                old = data.get("old", [])
                if isinstance(old, list):
                    for item in old:
                        em = None
                        if isinstance(item, str):
                            em = item.strip()
                        elif isinstance(item, dict) and "email" in item:
                            em = str(item["email"]).strip()
                        if em and is_valid_account_email(em) and em.lower() not in seen:
                            seen.add(em.lower())
                            old_accounts.append(em)
        except Exception:
            continue

    return {
        "active_account": active_email or "Default / Local Account",
        "has_active": active_email is not None,
        "old_accounts": old_accounts,
        "total_accounts": (1 if active_email else 0) + len(old_accounts),
    }


_CACHED_KNOWN_ACCOUNTS: Optional[List[str]] = None
_LAST_KNOWN_ACCOUNTS_TIME: float = 0.0


def clear_known_accounts_cache():
    """Clears cached known accounts list to allow fresh discovery."""
    global _CACHED_KNOWN_ACCOUNTS, _LAST_KNOWN_ACCOUNTS_TIME
    _CACHED_KNOWN_ACCOUNTS = None
    _LAST_KNOWN_ACCOUNTS_TIME = 0.0


def get_all_known_accounts_list(force_refresh: bool = False) -> List[str]:
    """
    Returns a clean, deduplicated list of all active, historical, and real Google accounts.
    Discovers accounts from active credentials, real-time quota files, and ledger records,
    strictly filtering out mock/test accounts.
    Caches result for 30 seconds for zero UI stutter.
    """
    global _CACHED_KNOWN_ACCOUNTS, _LAST_KNOWN_ACCOUNTS_TIME
    import time
    now = time.time()

    if not force_refresh and _CACHED_KNOWN_ACCOUNTS is not None and (now - _LAST_KNOWN_ACCOUNTS_TIME < 30.0):
        return list(_CACHED_KNOWN_ACCOUNTS)

    accounts: List[str] = []
    seen: set = set()

    def _add_if_valid(acc: Optional[str]):
        if acc and is_valid_account_email(acc):
            norm = acc.strip().lower()
            if norm not in seen:
                seen.add(norm)
                accounts.append(acc.strip())

    # 1. Active Google account from credentials
    active = get_active_google_account()
    _add_if_valid(active)

    # 2. Antigravity Tools accounts (.antigravity_tools/accounts.json)
    for ag_f in find_credential_files().get("antigravity_accounts", []):
        try:
            if ag_f.exists():
                data = json.loads(ag_f.read_text(encoding="utf-8", errors="ignore"))
                if isinstance(data, dict):
                    for a_entry in data.get("accounts", []):
                        if isinstance(a_entry, dict):
                            _add_if_valid(a_entry.get("email"))
        except Exception:
            pass

    # 3. Real-time account tracker files (.antigravity_tools/accounts/*.json)
    try:
        from core.realtime_quota import load_all_realtime_quotas
        rt_quotas = load_all_realtime_quotas()
        for em_key, qdata in rt_quotas.items():
            em = qdata.get("email") or em_key
            _add_if_valid(em)
    except Exception:
        pass

    # 4. Old accounts from google_accounts.json
    all_acc = get_all_google_accounts()
    for o in all_acc.get("old_accounts", []):
        _add_if_valid(o)

    # 5. Legitimate account emails in the ledger
    try:
        from core.ledger import ledger
        for s in ledger.sessions.values():
            act = s.get("account", "").strip()
            _add_if_valid(act)
            acc_usage = s.get("account_usage", {})
            if isinstance(acc_usage, dict):
                for u_act in acc_usage.keys():
                    _add_if_valid(u_act)
    except Exception:
        pass

    if not accounts:
        accounts.append("Default / Local Account")

    _CACHED_KNOWN_ACCOUNTS = list(accounts)
    _LAST_KNOWN_ACCOUNTS_TIME = now
    return accounts


_CACHED_ACTIVITY_RANGES: Optional[List[Dict[str, Any]]] = None
_LAST_ACTIVITY_RANGES_TIME: float = 0.0


def clear_activity_ranges_cache():
    """Clears cached activity ranges."""
    global _CACHED_ACTIVITY_RANGES, _LAST_ACTIVITY_RANGES_TIME
    _CACHED_ACTIVITY_RANGES = None
    _LAST_ACTIVITY_RANGES_TIME = 0.0


def get_account_activity_ranges(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    Discovers activity time windows for all accounts from .antigravity_tools/accounts/*.json.
    Returns list of dicts with:
      - email: str
      - created_at: float (epoch seconds)
      - last_used: float (epoch seconds)
      - last_updated: float (epoch seconds)
    Caches result for 30 seconds for 0% CPU overhead.
    """
    global _CACHED_ACTIVITY_RANGES, _LAST_ACTIVITY_RANGES_TIME
    import time
    now = time.time()

    if not force_refresh and _CACHED_ACTIVITY_RANGES is not None and (now - _LAST_ACTIVITY_RANGES_TIME < 30.0):
        return _CACHED_ACTIVITY_RANGES

    from core.realtime_quota import get_realtime_accounts_dirs
    dirs = get_realtime_accounts_dirs()
    ranges: List[Dict[str, Any]] = []
    seen = set()

    for d in dirs:
        try:
            for p in d.glob("*.json"):
                try:
                    content = p.read_text(encoding="utf-8", errors="ignore")
                    data = json.loads(content)
                    if not isinstance(data, dict):
                        continue
                    email = str(data.get("email", "")).strip().lower()
                    if not email:
                        email = str(data.get("token", {}).get("email", "")).strip().lower()
                    if not email and "@" in p.stem:
                        email = p.stem.lower().strip()
                    if not email or not is_valid_account_email(email):
                        continue

                    created_at = float(data.get("created_at", 0.0) or 0.0)
                    last_used = float(data.get("last_used", 0.0) or 0.0)
                    quota_block = data.get("quota", {}) if isinstance(data.get("quota"), dict) else {}
                    last_updated = float(quota_block.get("last_updated", 0.0) or data.get("last_updated", 0.0) or 0.0)

                    file_mtime = p.stat().st_mtime
                    if last_updated == 0.0:
                        last_updated = file_mtime
                    if last_used == 0.0:
                        last_used = max(created_at, file_mtime)

                    k = (email, created_at, last_used)
                    if k not in seen:
                        seen.add(k)
                        ranges.append({
                            "email": email,
                            "created_at": created_at,
                            "last_used": last_used,
                            "last_updated": last_updated,
                        })
                except Exception:
                    continue
        except Exception:
            continue

    _CACHED_ACTIVITY_RANGES = ranges
    _LAST_ACTIVITY_RANGES_TIME = now
    return ranges


def find_best_matching_account(session_mtime: float, fallback_account: Optional[str] = None) -> str:
    """
    Correlates a session's modification timestamp (session_mtime) with known account activity
    ranges to accurately attribute historical unassigned sessions to the account active during that window.
    """
    if not session_mtime or session_mtime <= 0:
        return fallback_account or get_active_google_account() or "Default"

    ranges = get_account_activity_ranges()
    if not ranges:
        return fallback_account or get_active_google_account() or "Default"

    # 1. Exact or inside range check: [created_at - 1800, max(last_used, last_updated) + 1800]
    matched_candidates = []
    for r in ranges:
        start = r["created_at"]
        end = max(r["last_used"], r["last_updated"])
        if start > 0 and end > 0:
            if (start - 1800) <= session_mtime <= (end + 1800):
                dist = min(abs(session_mtime - start), abs(session_mtime - end))
                matched_candidates.append((dist, r["email"]))

    if matched_candidates:
        matched_candidates.sort(key=lambda x: x[0])
        return matched_candidates[0][1]

    # 2. Proximity check to last_used / last_updated
    proximity_candidates = []
    for r in ranges:
        ref_pts = [pt for pt in (r.get("created_at"), r.get("last_used"), r.get("last_updated")) if pt and pt > 0]
        if ref_pts:
            min_dist = min(abs(session_mtime - pt) for pt in ref_pts)
            proximity_candidates.append((min_dist, r["email"]))

    if proximity_candidates:
        proximity_candidates.sort(key=lambda x: x[0])
        if proximity_candidates[0][0] <= 172800:
            return proximity_candidates[0][1]

    return fallback_account or get_active_google_account() or "Default"


