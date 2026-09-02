import os
import glob
import string
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any

# In-memory cache for WSL distros to completely avoid repetitive process spawning
_CACHED_WSL_DISTROS: Optional[List[str]] = None


def clear_wsl_cache():
    """Clears the cached WSL distros list to allow re-discovery."""
    global _CACHED_WSL_DISTROS
    _CACHED_WSL_DISTROS = None


def get_wsl_distros(force_refresh: bool = False) -> List[str]:
    """
    Discovers installed WSL2 distributions without popping up any cmd window.
    Uses direct UNC path probing first and caches the result for 0% overhead.
    """
    global _CACHED_WSL_DISTROS
    if force_refresh:
        _CACHED_WSL_DISTROS = None

    if _CACHED_WSL_DISTROS is not None:
        return _CACHED_WSL_DISTROS

    distros: List[str] = []
    if os.name != "nt":
        _CACHED_WSL_DISTROS = distros
        return distros

    # 1. Query Windows Registry for registered WSL distributions (Zero subprocesses, instant, 0 CMD windows)
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Lxss") as lxss_key:
            num_subkeys = winreg.QueryInfoKey(lxss_key)[0]
            for i in range(num_subkeys):
                guid = winreg.EnumKey(lxss_key, i)
                try:
                    with winreg.OpenKey(lxss_key, guid) as subkey:
                        distro_name, _ = winreg.QueryValueEx(subkey, "DistributionName")
                        if distro_name and "docker" not in distro_name.lower():
                            if distro_name not in distros:
                                distros.append(distro_name)
                except Exception:
                    pass
    except Exception:
        pass

    # 2. Check virtual filesystem network shares (\\wsl.localhost and \\wsl$)
    for base in [Path(r"\\wsl.localhost"), Path(r"\\wsl$")]:
        try:
            if base.exists():
                for d in base.iterdir():
                    if d.is_dir() and "docker" not in d.name.lower():
                        if d.name not in distros:
                            distros.append(d.name)
        except Exception:
            pass

    # 3. Known candidates fallback
    known_candidates = [
        "Ubuntu", "Ubuntu-24.04", "Ubuntu-22.04", "Ubuntu-20.04", "Ubuntu-18.04",
        "Debian", "kali-linux", "Arch", "openSUSE-Leap-15.5", "Fedora", "Alpine"
    ]
    for d in known_candidates:
        try:
            if Path(rf"\\wsl.localhost\{d}").exists() or Path(rf"\\wsl$\{d}").exists():
                if d not in distros:
                    distros.append(d)
        except Exception:
            pass

    _CACHED_WSL_DISTROS = distros
    return _CACHED_WSL_DISTROS


def get_available_drives() -> List[str]:
    """Returns all available drive letters on Windows."""
    if os.name != "nt":
        return []
    drives = []
    for letter in string.ascii_uppercase:
        drive_path = f"{letter}:\\"
        try:
            if os.path.exists(drive_path):
                drives.append(f"{letter}:")
        except Exception:
            pass
    return drives


# In-memory cache for discovered brain directories to prevent multi-drive & WSL glob overhead
_CACHED_BRAIN_DIRS: Optional[Dict[tuple, List[Path]]] = None
_LAST_BRAIN_DIRS_SCAN_TIME: float = 0.0


def clear_brain_dirs_cache():
    """Clears cached brain directory paths to allow fresh discovery."""
    global _CACHED_BRAIN_DIRS, _LAST_BRAIN_DIRS_SCAN_TIME
    _CACHED_BRAIN_DIRS = None
    _LAST_BRAIN_DIRS_SCAN_TIME = 0.0


def find_all_brain_dirs(custom_dirs: Optional[List[str]] = None, force_refresh: bool = False) -> List[Path]:
    r"""
    Comprehensive scanner for Antigravity 'brain' directories across:
    1. Custom user configured directories
    2. Windows user profiles & drives
    3. WSL2 UNC network paths (\\wsl.localhost and \\wsl$)
    4. Mapped network drives (e.g. Z:\home\...)
    5. Native Linux / WSL paths (/home/..., /mnt/c/...)
    Caches results for 60 seconds to guarantee 0% CPU and zero UI thread stalls.
    """
    global _CACHED_BRAIN_DIRS, _LAST_BRAIN_DIRS_SCAN_TIME
    import time
    now = time.time()
    cache_key = tuple(sorted(str(cd) for cd in (custom_dirs or []) if cd))

    if not force_refresh and _CACHED_BRAIN_DIRS is not None and cache_key in _CACHED_BRAIN_DIRS and (now - _LAST_BRAIN_DIRS_SCAN_TIME < 60.0):
        return list(_CACHED_BRAIN_DIRS[cache_key])

    dirs: List[Path] = []

    def _add_if_valid(p_obj):
        try:
            p = Path(p_obj)
            if p.exists() and p.is_dir():
                resolved = p.resolve() if not str(p).startswith("\\\\") else p
                if resolved not in dirs and p not in dirs:
                    dirs.append(p)
        except (PermissionError, OSError, Exception):
            pass

    # 1. Custom user directories
    if custom_dirs:
        for cd in custom_dirs:
            if cd:
                _add_if_valid(cd)

    # 2. Environment variables
    for env_var in ["ANTIGRAVITY_DIR", "GEMINI_BRAIN_DIR", "GEMINI_DIR"]:
        if env_var in os.environ:
            p = Path(os.environ[env_var])
            _add_if_valid(p / "brain")
            _add_if_valid(p)

    # 3. Windows Native Profiles & User directories
    home = Path.home()
    for sub in [".gemini/antigravity/brain", ".gemini/antigravity-ide/brain", ".gemini/brain"]:
        _add_if_valid(home / sub)

    for env_var in ["USERPROFILE", "APPDATA", "LOCALAPPDATA"]:
        if env_var in os.environ:
            base = Path(os.environ[env_var])
            for sub in [".gemini/antigravity/brain", ".gemini/antigravity-ide/brain", ".gemini/brain"]:
                _add_if_valid(base / sub)
                _add_if_valid(base / ".." / sub)

    # 4. Scan all available Windows drives (C:, D:, Z:, etc.)
    drives = get_available_drives()
    if not drives and os.name == "nt":
        drives = [os.environ.get("SystemDrive", "C:")]

    for drive in drives:
        patterns = [
            f"{drive}\\Users\\*\\.gemini\\antigravity\\brain",
            f"{drive}\\Users\\*\\.gemini\\antigravity-ide\\brain",
            f"{drive}\\Users\\*\\.gemini\\brain",
            f"{drive}\\home\\*\\.gemini\\antigravity\\brain",
            f"{drive}\\home\\*\\.gemini\\antigravity-ide\\brain",
            f"{drive}\\home\\*\\.gemini\\brain",
        ]
        for pat in patterns:
            try:
                for match in glob.glob(pat):
                    _add_if_valid(match)
            except Exception:
                pass

    # 5. WSL2 UNC Paths from Windows (\\wsl.localhost and \\wsl$)
    if os.name == "nt":
        distros = get_wsl_distros()
        for distro in distros:
            for unc_root in [rf"\\wsl.localhost\{distro}", rf"\\wsl$\{distro}"]:
                unc_patterns = [
                    f"{unc_root}\\home\\*\\.gemini\\antigravity\\brain",
                    f"{unc_root}\\home\\*\\.gemini\\antigravity-ide\\brain",
                    f"{unc_root}\\home\\*\\.gemini\\brain",
                    f"{unc_root}\\root\\.gemini\\antigravity\\brain",
                    f"{unc_root}\\root\\.gemini\\antigravity-ide\\brain",
                ]
                for pat in unc_patterns:
                    try:
                        for match in glob.glob(pat):
                            _add_if_valid(match)
                    except Exception:
                        pass

    # 6. Native Linux / WSL paths
    linux_patterns = [
        "/home/*/.gemini/antigravity/brain",
        "/home/*/.gemini/antigravity-ide/brain",
        "/home/*/.gemini/brain",
        "/root/.gemini/antigravity/brain",
        "/root/.gemini/antigravity-ide/brain",
        "/mnt/c/Users/*/.gemini/antigravity/brain",
        "/mnt/c/Users/*/.gemini/antigravity-ide/brain",
        "/mnt/d/Users/*/.gemini/antigravity/brain",
    ]
    for pat in linux_patterns:
        try:
            for match in glob.glob(pat):
                _add_if_valid(match)
        except Exception:
            pass

    if _CACHED_BRAIN_DIRS is None:
        _CACHED_BRAIN_DIRS = {}
    _CACHED_BRAIN_DIRS[cache_key] = list(dirs)
    _LAST_BRAIN_DIRS_SCAN_TIME = now
    return dirs


def get_brain_dirs_summary(custom_dirs: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Returns detailed summary of all discovered brain paths with type classification."""
    all_dirs = find_all_brain_dirs(custom_dirs=custom_dirs)
    custom_set = set(str(Path(cd).resolve()) if cd else "" for cd in (custom_dirs or []))
    
    summary = []
    for d in all_dirs:
        d_str = str(d)
        d_norm = str(d.resolve()) if not d_str.startswith("\\\\") else d_str
        is_custom = d_norm in custom_set or d_str in (custom_dirs or [])

        # Classify location type
        if "wsl.localhost" in d_str or "wsl$" in d_str:
            loc_type = "WSL2 Network"
        elif d_str.startswith("/mnt/"):
            loc_type = "WSL Mount"
        elif d_str.startswith("/home/") or d_str.startswith("/root/"):
            loc_type = "Linux Native"
        elif len(d_str) >= 2 and d_str[1] == ":" and d_str[0].upper() != "C":
            loc_type = f"Drive {d_str[0].upper()}:"
        else:
            loc_type = "Windows Native"

        # Count session files
        session_count = 0
        try:
            for _, dirs, files in os.walk(d):
                if "chunks" in dirs:
                    dirs.remove("chunks")
                if "transcript_full.jsonl" in files or "transcript.jsonl" in files:
                    session_count += 1
        except Exception:
            pass

        summary.append({
            "path": d_str,
            "type": loc_type,
            "is_custom": is_custom,
            "session_count": session_count,
            "exists": d.exists()
        })

    return summary


def get_all_session_files(custom_dirs: Optional[List[str]] = None) -> List[Dict]:
    """
    Scans brain directories across Windows and WSL2 and returns sorted session metadata (newest first).
    """
    brain_dirs = find_all_brain_dirs(custom_dirs=custom_dirs)
    if not brain_dirs:
        return []

    sessions_map: Dict[str, Dict] = {}

    for b_dir in brain_dirs:
        try:
            for root, dirs, files in os.walk(b_dir):
                if "chunks" in dirs:
                    dirs.remove("chunks")

                target_file = None
                if "transcript_full.jsonl" in files:
                    target_file = Path(root) / "transcript_full.jsonl"
                elif "transcript.jsonl" in files:
                    target_file = Path(root) / "transcript.jsonl"

                if target_file:
                    try:
                        stat = target_file.stat()
                        try:
                            rel_parts = Path(root).relative_to(b_dir).parts
                            session_id = rel_parts[0] if rel_parts else Path(root).name
                            session_root_dir = b_dir / rel_parts[0] if rel_parts else Path(root)
                        except ValueError:
                            session_id = Path(root).name
                            session_root_dir = Path(root)

                        last_dt = datetime.fromtimestamp(stat.st_mtime)

                        entry = {
                            "session_id": session_id,
                            "folder": Path(root),
                            "session_root_dir": session_root_dir,
                            "file": target_file,
                            "mtime": stat.st_mtime,
                            "size": stat.st_size,
                            "last_active": last_dt,
                            "last_active_str": last_dt.strftime("%Y-%m-%d %H:%M:%S"),
                            "brain_dir": b_dir,
                        }

                        if session_id in sessions_map:
                            if stat.st_mtime > sessions_map[session_id]["mtime"]:
                                sessions_map[session_id] = entry
                        else:
                            sessions_map[session_id] = entry

                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            continue

    sessions = list(sessions_map.values())
    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return sessions
