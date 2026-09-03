import os
import sys
import shutil
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any

from core.session_finder import get_all_session_files, find_all_brain_dirs
from core.ledger import ledger
from core.engine import _FILE_CACHE


def format_bytes(size_bytes: int) -> str:
    """Formats raw byte count into human-readable string (B, KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def paginate_items(items: list, page: int = 1, page_size: int = 10) -> Dict[str, Any]:
    """
    Slices an in-memory list into a paginated subset and returns pagination metadata.

    Args:
        items: List of items to paginate.
        page: 1-indexed requested page number (clamped to [1, total_pages]).
        page_size: Maximum number of items per page (default 10, minimum 1).

    Returns:
        Dict with keys:
            - items: List of items on the current page slice.
            - page: Clamped 1-indexed current page number.
            - page_size: Effective page size.
            - total_pages: Total number of pages (>= 1).
            - total_count: Total number of items across all pages.
            - has_next: Boolean flag indicating if a next page exists.
            - has_prev: Boolean flag indicating if a previous page exists.
            - start_idx: 1-indexed start item number for display (0 if total_count == 0).
            - end_idx: 1-indexed end item number for display (0 if total_count == 0).
    """
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


def get_disk_usage_summary(custom_dirs: Optional[List[str]] = None) -> Dict[str, Any]:
    """Scans all sessions on disk and returns total session count, total disk bytes, and details."""
    sessions = get_all_session_files(custom_dirs=custom_dirs)
    total_bytes = 0
    detailed_list: List[Dict[str, Any]] = []

    for s in sessions:
        sid = s.get("session_id", "unknown")
        # Try calculating full folder size if available
        folder = s.get("folder")
        folder_size = 0
        if folder and os.path.exists(str(folder)):
            try:
                for root, _, files in os.walk(str(folder)):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            folder_size += os.path.getsize(fp)
                        except (OSError, PermissionError):
                            pass
            except Exception:
                folder_size = s.get("size", 0)
        else:
            folder_size = s.get("size", 0)

        total_bytes += folder_size

        ledger_entry = ledger.sessions.get(sid, {})
        tokens = ledger_entry.get("total", 0)

        detailed_list.append({
            "session_id": sid,
            "title": s.get("first_prompt") or s.get("title") or sid,
            "first_prompt": s.get("first_prompt", ""),
            "last_active": s.get("last_active_str", "Unknown"),
            "mtime": s.get("mtime", 0.0),
            "size_bytes": folder_size,
            "size_str": format_bytes(folder_size),
            "tokens": tokens,
            "account": ledger_entry.get("account", "Default"),
            "file": str(s.get("file", "")),
            "folder": str(s.get("folder", "")),
            "session_root_dir": str(s.get("session_root_dir", s.get("folder", ""))),
        })

    return {
        "total_sessions": len(sessions),
        "total_bytes": total_bytes,
        "total_size_str": format_bytes(total_bytes),
        "sessions": detailed_list,
    }


def delete_session_files(
    session_id: str,
    folder_path: Optional[str] = None,
    file_path: Optional[str] = None,
    delete_disk_files: bool = True,
    custom_dirs: Optional[List[str]] = None,
    flush: bool = True
) -> Tuple[bool, int, str]:
    """
    Safely deletes a session's directory and transcript files from disk (if delete_disk_files is True),
    purges it from cache, updates the in-memory ledger, and flushes to disk.
    Returns (success, freed_bytes, message).
    """
    freed_bytes = 0
    resolved_paths_to_delete: List[Path] = []

    # Sanitize session_id to prevent path traversal
    clean_sid = os.path.basename(str(session_id).strip().replace("\\", "/").rstrip("/"))
    if not clean_sid or clean_sid in (".", ".."):
        return False, 0, f"Invalid session ID: {session_id}"

    # 1. Identify paths from ledger or parameters
    if not folder_path or not file_path:
        ledger_info = ledger.sessions.get(session_id, {}) or ledger.sessions.get(clean_sid, {})
        folder_path = folder_path or ledger_info.get("folder") or ledger_info.get("folder_path")
        file_path = file_path or ledger_info.get("file") or ledger_info.get("file_path")

    # 2. Search across brain directories to find the exact session folder on disk
    brain_dirs = find_all_brain_dirs(custom_dirs=custom_dirs)
    for b_dir in brain_dirs:
        try:
            cand_dir = b_dir / clean_sid
            if cand_dir.exists() and cand_dir.is_dir():
                if cand_dir not in resolved_paths_to_delete:
                    resolved_paths_to_delete.append(cand_dir)
        except Exception:
            pass

    if folder_path and Path(folder_path).exists():
        p_folder = Path(folder_path).resolve()
        is_safe = False
        if p_folder.name == clean_sid:
            for b_dir in brain_dirs:
                try:
                    if p_folder.is_relative_to(b_dir.resolve()):
                        is_safe = True
                        break
                except Exception:
                    pass
        if is_safe and p_folder not in resolved_paths_to_delete:
            resolved_paths_to_delete.append(p_folder)

    if file_path and Path(file_path).exists():
        p_file = Path(file_path).resolve()
        is_safe = False
        if p_file.parent.name == clean_sid:
            for b_dir in brain_dirs:
                try:
                    if p_file.is_relative_to(b_dir.resolve()):
                        is_safe = True
                        break
                except Exception:
                    pass
        if is_safe and p_file not in resolved_paths_to_delete:
            resolved_paths_to_delete.append(p_file)

    # 3. Calculate freed bytes and delete from disk (if requested)
    if delete_disk_files:
        for p in resolved_paths_to_delete:
            try:
                if p.is_dir():
                    for root, _, files in os.walk(p):
                        for f in files:
                            try:
                                freed_bytes += (Path(root) / f).stat().st_size
                            except (OSError, PermissionError):
                                pass
                    shutil.rmtree(p, ignore_errors=True)
                elif p.is_file():
                    try:
                        freed_bytes += p.stat().st_size
                    except (OSError, PermissionError):
                        pass
                    p.unlink(missing_ok=True)
            except Exception:
                pass

    # 4. Clean in-memory file cache
    keys_to_remove = [k for k in _FILE_CACHE.keys() if session_id in k]
    for k in keys_to_remove:
        _FILE_CACHE.pop(k, None)

    # 5. Remove from in-memory ledger and flush
    ledger.remove_session(session_id)
    if flush:
        ledger.flush_to_disk(force=True)

    action_str = "deleted & freed storage" if delete_disk_files else "removed from ledger"
    return True, freed_bytes, f"Session '{session_id[:16]}...' {action_str} ({format_bytes(freed_bytes)})"


def prune_sessions_by_age(older_than_days: int, keep_active: bool = True, delete_disk_files: bool = True) -> Dict[str, Any]:
    """Deletes sessions older than X days."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=older_than_days)
    sessions = get_all_session_files()

    if not sessions:
        return {"deleted_count": 0, "freed_bytes": 0, "deleted_ids": []}

    active_id = sessions[0]["session_id"] if sessions else None
    deleted_ids = []
    total_freed = 0

    for s in sessions:
        sid = s["session_id"]
        if keep_active and sid == active_id:
            continue
        dt = s.get("last_active")
        if dt is None and "mtime" in s:
            dt = datetime.fromtimestamp(s["mtime"], tz=timezone.utc)
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < cutoff:
                ok, freed, _ = delete_session_files(
                    sid,
                    folder_path=str(s.get("folder", "")),
                    file_path=str(s.get("file", "")),
                    delete_disk_files=delete_disk_files,
                    flush=False
                )
                if ok:
                    deleted_ids.append(sid)
                    total_freed += freed

    if deleted_ids:
        ledger.flush_to_disk(force=True)

    return {
        "deleted_count": len(deleted_ids),
        "freed_bytes": total_freed,
        "freed_str": format_bytes(total_freed),
        "deleted_ids": deleted_ids,
    }


def prune_sessions_keep_latest(n_latest: int = 10, keep_active: bool = True, delete_disk_files: bool = True) -> Dict[str, Any]:
    """Keeps the most recent N sessions, deleting all older ones."""
    sessions = get_all_session_files()
    if len(sessions) <= n_latest:
        return {"deleted_count": 0, "freed_bytes": 0, "deleted_ids": []}

    to_delete = sessions[n_latest:]
    active_id = sessions[0]["session_id"] if sessions else None
    deleted_ids = []
    total_freed = 0

    for s in to_delete:
        sid = s["session_id"]
        if keep_active and sid == active_id:
            continue

        ok, freed, _ = delete_session_files(
            sid,
            folder_path=str(s.get("folder", "")),
            file_path=str(s.get("file", "")),
            delete_disk_files=delete_disk_files,
            flush=False
        )
        if ok:
            deleted_ids.append(sid)
            total_freed += freed

    if deleted_ids:
        ledger.flush_to_disk(force=True)

    return {
        "deleted_count": len(deleted_ids),
        "freed_bytes": total_freed,
        "freed_str": format_bytes(total_freed),
        "deleted_ids": deleted_ids,
    }


def prune_empty_sessions(delete_disk_files: bool = True) -> Dict[str, Any]:
    """Removes sessions that have 0 tokens or are corrupted/empty."""
    sessions = get_all_session_files()
    active_id = sessions[0]["session_id"] if sessions else None
    deleted_ids = []
    total_freed = 0

    for s in sessions:
        sid = s["session_id"]
        if sid == active_id:
            continue

        entry = ledger.sessions.get(sid, {})
        tot_tokens = entry.get("total", 0)
        size = s.get("size", 0)

        if tot_tokens == 0 or size == 0:
            ok, freed, _ = delete_session_files(
                sid,
                folder_path=str(s.get("folder", "")),
                file_path=str(s.get("file", "")),
                delete_disk_files=delete_disk_files,
                flush=False
            )
            if ok:
                deleted_ids.append(sid)
                total_freed += freed

    if deleted_ids:
        ledger.flush_to_disk(force=True)

    return {
        "deleted_count": len(deleted_ids),
        "freed_bytes": total_freed,
        "freed_str": format_bytes(total_freed),
        "deleted_ids": deleted_ids,
    }


def prune_all_previous(keep_active: bool = True, delete_disk_files: bool = True) -> Dict[str, Any]:
    """Deletes all previous sessions, keeping only the active session (or all if keep_active=False)."""
    sessions = get_all_session_files()
    if not sessions:
        return {"deleted_count": 0, "freed_bytes": 0, "deleted_ids": []}

    active_id = sessions[0]["session_id"] if sessions else None
    deleted_ids = []
    total_freed = 0

    for s in sessions:
        sid = s["session_id"]
        if keep_active and sid == active_id:
            continue

        ok, freed, _ = delete_session_files(
            sid,
            folder_path=str(s.get("folder", "")),
            file_path=str(s.get("file", "")),
            delete_disk_files=delete_disk_files,
            flush=False
        )
        if ok:
            deleted_ids.append(sid)
            total_freed += freed

    if deleted_ids:
        ledger.flush_to_disk(force=True)

    return {
        "deleted_count": len(deleted_ids),
        "freed_bytes": total_freed,
        "freed_str": format_bytes(total_freed),
        "deleted_ids": deleted_ids,
    }


def open_storage_folder(custom_dirs: Optional[List[str]] = None) -> Tuple[bool, str]:
    """
    Opens the primary .gemini/brain directory in the OS file explorer.
    Returns (success, path_or_message).
    """
    brain_dirs = find_all_brain_dirs(custom_dirs=custom_dirs)
    if not brain_dirs:
        return False, "No Antigravity storage folder (.gemini/brain) found on this machine."

    target_dir = brain_dirs[0]
    for b in brain_dirs:
        if b.exists() and b.is_dir():
            target_dir = b
            break

    try:
        target_str = str(target_dir)
        if os.name == "nt":
            os.startfile(target_str)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target_str])
        else:
            subprocess.Popen(["xdg-open", target_str])
        return True, target_str
    except Exception as e:
        return False, f"Could not open folder in Explorer: {e}"


def open_session_folder(session_id: str, folder_path: Optional[str] = None) -> Tuple[bool, str]:
    """
    Opens the specific session directory in the OS file explorer.
    Returns (success, path_or_message).
    """
    clean_sid = os.path.basename(str(session_id).strip().replace("\\", "/").rstrip("/"))
    if not clean_sid or clean_sid in (".", ".."):
        return False, f"Invalid session ID: {session_id}"

    target_path: Optional[Path] = None

    if folder_path and Path(folder_path).exists():
        target_path = Path(folder_path)
    else:
        # Check ledger info
        s_info = ledger.sessions.get(session_id, {}) or ledger.sessions.get(clean_sid, {})
        cand_folder = s_info.get("folder") or s_info.get("folder_path")
        if cand_folder and Path(cand_folder).exists():
            target_path = Path(cand_folder)
        else:
            # Search brain dirs
            for b_dir in find_all_brain_dirs():
                cand_dir = b_dir / clean_sid
                if cand_dir.exists():
                    target_path = cand_dir
                    break

    if not target_path or not target_path.exists():
        return False, f"Session folder for '{session_id[:16]}' not found on disk."

    try:
        target_str = str(target_path)
        if os.name == "nt":
            os.startfile(target_str)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target_str])
        else:
            subprocess.Popen(["xdg-open", target_str])
        return True, target_str
    except Exception as e:
        return False, f"Could not open session folder: {e}"


def sync_and_prune_orphaned_sessions(custom_dirs: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Synchronizes the ledger history database (account_usage.json) with physical on-disk session directories.
    Identifies and purges any session records in the ledger that no longer have physical files/folders on disk.
    Returns {
        "orphaned_count": int,
        "orphaned_ids": List[str],
        "synced_total": int,
        "msg": str
    }.
    """
    on_disk_sessions = get_all_session_files(custom_dirs=custom_dirs)
    disk_session_ids = {s.get("session_id") for s in on_disk_sessions if s.get("session_id")}

    # Also collect brain directory child folder names directly
    brain_dirs = find_all_brain_dirs(custom_dirs=custom_dirs)
    for b_dir in brain_dirs:
        try:
            if b_dir.exists() and b_dir.is_dir():
                for child in b_dir.iterdir():
                    if child.is_dir():
                        disk_session_ids.add(child.name)
        except Exception:
            pass

    orphaned_ids = []
    with ledger._lock:
        all_ledger_sids = list(ledger.sessions.keys())
        for sid in all_ledger_sids:
            clean_sid = os.path.basename(str(sid).strip().replace("\\", "/").rstrip("/"))
            s_info = ledger.sessions.get(sid, {})
            folder = s_info.get("folder") or s_info.get("folder_path")
            file_p = s_info.get("file") or s_info.get("file_path")

            exists_on_disk = False
            if sid in disk_session_ids or clean_sid in disk_session_ids:
                exists_on_disk = True
            elif folder and os.path.exists(str(folder)):
                exists_on_disk = True
            elif file_p and os.path.exists(str(file_p)):
                exists_on_disk = True

            if not exists_on_disk:
                orphaned_ids.append(sid)

    # Delete orphaned sessions from ledger & cache
    for sid in orphaned_ids:
        keys_to_remove = [k for k in _FILE_CACHE.keys() if sid in k]
        for k in keys_to_remove:
            _FILE_CACHE.pop(k, None)
        ledger.remove_session(sid)

    if orphaned_ids:
        ledger.flush_to_disk(force=True)

    synced_total = len(ledger.sessions)
    count = len(orphaned_ids)
    msg = f"Synced with storage: removed {count} orphaned session(s) from ledger." if count > 0 else "All ledger sessions match on-disk storage."

    return {
        "orphaned_count": count,
        "orphaned_ids": orphaned_ids,
        "synced_total": synced_total,
        "msg": msg
    }
