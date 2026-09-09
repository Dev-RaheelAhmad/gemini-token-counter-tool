import os
import sys
import shutil
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from core.config import config


def get_default_antigravity_tools_path() -> Path:
    """
    Dynamically resolves the default canonical path to antigravity-tools.exe
    without hardcoding any user profile directory.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Antigravity Tools" / "antigravity-tools.exe"

    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        return Path(user_profile) / "AppData" / "Local" / "Antigravity Tools" / "antigravity-tools.exe"

    return Path.home() / "AppData" / "Local" / "Antigravity Tools" / "antigravity-tools.exe"


def resolve_antigravity_tools_path(custom_path: Optional[str] = None) -> Optional[Path]:
    """
    Resolves the executable path to antigravity-tools.exe.
    Checks explicit custom_path first, then configured path, then default
    and fallback candidate locations. Returns Path if found and exists, else None.
    """
    # 1. Explicit argument path
    if custom_path and custom_path.strip():
        p = Path(custom_path.strip())
        if p.exists() and p.is_file():
            return p

    # 2. Configured custom path from config
    cfg_path = config.get("antigravity_tools_path")
    if cfg_path and str(cfg_path).strip():
        p = Path(str(cfg_path).strip())
        if p.exists() and p.is_file():
            return p

    # 3. Canonical default path
    default_p = get_default_antigravity_tools_path()
    if default_p.exists() and default_p.is_file():
        return default_p

    # 4. Fallback search locations
    candidates = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Antigravity Tools" / "antigravity-tools.exe")
        candidates.append(Path(local_app_data) / "Programs" / "antigravity-tools" / "antigravity-tools.exe")

    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(Path(program_files) / "Antigravity Tools" / "antigravity-tools.exe")

    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    if program_files_x86:
        candidates.append(Path(program_files_x86) / "Antigravity Tools" / "antigravity-tools.exe")

    for cand in candidates:
        if cand.exists() and cand.is_file():
            return cand

    # 5. Check PATH environment variable
    which_path = shutil.which("antigravity-tools.exe") or shutil.which("antigravity-tools")
    if which_path:
        p = Path(which_path)
        if p.exists() and p.is_file():
            return p

    return None


def is_antigravity_tools_installed(custom_path: Optional[str] = None) -> bool:
    """Returns True if antigravity-tools.exe is located on the host system."""
    return resolve_antigravity_tools_path(custom_path) is not None


def is_antigravity_tools_running(exe_name: str = "antigravity-tools.exe") -> Tuple[bool, Optional[int]]:
    """
    Checks if antigravity-tools.exe is currently running.
    Uses native Windows Toolhelp32Snapshot via ctypes for 0% CPU overhead,
    0ms execution, and zero console windows.
    Returns (is_running, process_id).
    """
    if sys.platform != "win32":
        return False, None

    try:
        import ctypes
        import ctypes.wintypes

        TH32CS_SNAPPROCESS = 0x00000002

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.wintypes.DWORD),
                ("cntUsage", ctypes.wintypes.DWORD),
                ("th32ProcessID", ctypes.wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", ctypes.wintypes.DWORD),
                ("cntThreads", ctypes.wintypes.DWORD),
                ("th32ParentProcessID", ctypes.wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        h_snap = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if h_snap == -1 or not h_snap:
            return False, None

        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)

        target_lower = exe_name.lower().rstrip(".exe")

        try:
            if ctypes.windll.kernel32.Process32First(h_snap, ctypes.byref(pe)):
                while True:
                    proc_name = pe.szExeFile.decode("ansi", errors="ignore").lower()
                    if target_lower in proc_name:
                        pid = int(pe.th32ProcessID)
                        return True, pid
                    if not ctypes.windll.kernel32.Process32Next(h_snap, ctypes.byref(pe)):
                        break
        finally:
            ctypes.windll.kernel32.CloseHandle(h_snap)

    except Exception:
        pass

    return False, None


def launch_antigravity_tools(custom_path: Optional[str] = None, force: bool = False) -> Tuple[bool, str]:
    """
    Launches antigravity-tools.exe as a detached, non-blocking background process.
    - If auto-launch is disabled in config and not forced, returns (False, 'disabled').
    - If already running, avoids spawning duplicate processes and returns (True, 'already_running').
    - If not installed, returns (False, 'not_installed').
    - If successful, returns (True, 'launched').
    """
    if not force and not bool(config.get("auto_launch_antigravity_tools", True)):
        return False, "disabled"

    running, pid = is_antigravity_tools_running()
    if running and not force:
        return True, "already_running"

    target_path = resolve_antigravity_tools_path(custom_path)
    if not target_path or not target_path.exists():
        return False, "not_installed"

    try:
        import subprocess

        creationflags = 0
        if sys.platform == "win32":
            # DETACHED_PROCESS (0x00000008) | CREATE_NEW_PROCESS_GROUP (0x00000200)
            creationflags = 0x00000008 | 0x00000200

        subprocess.Popen(
            [str(target_path)],
            cwd=str(target_path.parent),
            creationflags=creationflags,
            close_fds=True,
        )
        return True, "launched"
    except Exception as e:
        return False, f"error: {str(e)}"


def get_antigravity_tools_status(custom_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns a status dictionary of Antigravity Tools companion app:
    {
        'installed': bool,
        'running': bool,
        'pid': Optional[int],
        'path': Optional[str],
        'auto_launch_enabled': bool,
    }
    """
    resolved = resolve_antigravity_tools_path(custom_path)
    running, pid = is_antigravity_tools_running()
    return {
        "installed": resolved is not None,
        "running": running,
        "pid": pid,
        "path": str(resolved) if resolved else str(get_default_antigravity_tools_path()),
        "auto_launch_enabled": bool(config.get("auto_launch_antigravity_tools", True)),
    }
