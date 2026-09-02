import sys
import ctypes
from typing import Optional, Set, Tuple
from core.config import config


def get_screen_work_area(window=None) -> Tuple[int, int, int, int]:
    """
    Returns (left, top, right, bottom) in screen coordinates
    of the primary display usable work area (excluding taskbar),
    correctly handling all Windows display configurations.
    """
    if sys.platform.startswith("win"):
        try:
            import ctypes.wintypes
            rect = ctypes.wintypes.RECT()
            # SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
        except Exception:
            pass
    try:
        import tkinter as tk
        root = window or tk._default_root
        if root:
            w = root.winfo_screenwidth()
            h = root.winfo_screenheight()
            scale = get_window_scale(root)
            phys_w = int(round(w * scale))
            phys_h = int(round(h * scale))
            return 0, 0, phys_w, max(100, phys_h - int(round(40 * scale)))
    except Exception:
        pass
    return 0, 0, 1920, 1040


def get_window_scale(window) -> float:
    """Safely retrieves the DPI scaling factor for a Tkinter / CustomTkinter window."""
    try:
        if hasattr(window, "_get_window_scaling"):
            return float(window._get_window_scaling())
    except Exception:
        pass
    return 1.0


def center_window_on_screen(window, width: int, height: int):
    """
    Centers a Tkinter / CustomTkinter window on the primary screen work area,
    accounting for DPI scaling.
    """
    try:
        window.update_idletasks()
        scale = get_window_scale(window)
        wl, wt, wr, wb = get_screen_work_area(window)
        work_w = wr - wl
        work_h = wb - wt

        phys_w = int(round(width * scale))
        phys_h = int(round(height * scale))

        target_w = width if phys_w <= work_w else max(400, int(work_w / scale))
        target_h = height if phys_h <= work_h else max(300, int(work_h / scale))
        t_phys_w = int(round(target_w * scale))
        t_phys_h = int(round(target_h * scale))

        cx = max(wl, wl + (work_w - t_phys_w) // 2)
        cy = max(wt, wt + (work_h - t_phys_h) // 2)
        window.geometry(f"{target_w}x{target_h}+{cx}+{cy}")
    except Exception:
        window.geometry(f"{width}x{height}")


def position_bottom_right(window, width: int, height: int, pad_x: int = 16, pad_y: int = 16) -> str:
    """
    Calculates the exact geometry string to place a window snug in the bottom-right corner
    of the usable desktop work area (above the Windows taskbar), accounting for DPI scaling.
    """
    try:
        window.update_idletasks()
        scale = get_window_scale(window)
        wl, wt, wr, wb = get_screen_work_area(window)

        phys_w = int(round(width * scale))
        phys_h = int(round(height * scale))

        x = max(wl + 10, wr - phys_w - pad_x)
        y = max(wt + 10, wb - phys_h - pad_y)
        return f"{width}x{height}+{x}+{y}"
    except Exception:
        return f"{width}x{height}"


def apply_windows_dark_titlebar(window, mode: Optional[str] = None):
    """
    Enforces native Windows immersive dark titlebar and custom caption colors
    for top-level and dialog windows on Windows 10 (1903+) and Windows 11.
    Sets attributes smoothly without flicker loops.
    """
    if not sys.platform.startswith("win"):
        return

    try:
        if mode is None:
            mode = config.get("theme") or "dark"

        is_dark = mode.lower() == "dark" or (mode.lower() == "system" and config.get("theme") == "dark")

        hwnd = window.winfo_id()
        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi

        # Resolve top-level OS handles
        ga_root = user32.GetAncestor(hwnd, 2)
        ga_root_owner = user32.GetAncestor(hwnd, 3)
        parent_hwnd = user32.GetParent(hwnd)

        target_hwnds: Set[int] = {h for h in (hwnd, parent_hwnd, ga_root, ga_root_owner) if h}

        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
        DWMWA_CAPTION_COLOR = 35
        DWMWA_TEXT_COLOR = 36

        val = ctypes.c_int(1 if is_dark else 0)
        # Background color in 0x00BBGGRR format (0x001A130F for dark theme #0F131A, 0x00F9F5F1 for light #F1F5F9)
        caption_color = ctypes.c_int(0x001A130F if is_dark else 0x00F9F5F1)
        text_color = ctypes.c_int(0x00FFFFFF if is_dark else 0x00170F0F)

        for h in target_hwnds:
            dwmapi.DwmSetWindowAttribute(h, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(val), ctypes.sizeof(val))
            dwmapi.DwmSetWindowAttribute(h, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, ctypes.byref(val), ctypes.sizeof(val))
            dwmapi.DwmSetWindowAttribute(h, DWMWA_CAPTION_COLOR, ctypes.byref(caption_color), ctypes.sizeof(caption_color))
            dwmapi.DwmSetWindowAttribute(h, DWMWA_TEXT_COLOR, ctypes.byref(text_color), ctypes.sizeof(text_color))

        # Single frame change notification
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020
        for h in target_hwnds:
            user32.SetWindowPos(h, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    except Exception:
        pass


def cancel_all_pending_after_events(window):
    """
    Safely discovers and cancels all pending Tcl/Tk .after timer callbacks
    for a window before destruction, preventing dangling callbacks,
    'invalid command name' errors, or destroyed application exceptions.
    Uses direct Tcl after cancel so Tkinter's internal destroy can cleanly unregister commands.
    """
    try:
        if window and hasattr(window, "tk") and hasattr(window.tk, "eval") and hasattr(window.tk, "call"):
            raw_ids = window.tk.eval("after info")
            if raw_ids:
                for tid in raw_ids.split():
                    try:
                        window.tk.call("after", "cancel", tid)
                    except Exception:
                        pass
    except Exception:
        pass

