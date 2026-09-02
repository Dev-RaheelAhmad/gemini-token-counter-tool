import threading
from typing import Callable, Optional
from PIL import Image, ImageDraw
import pystray


# In-memory cache for tray icon images per status color to eliminate GDI handle / memory allocations
_ICON_IMAGE_CACHE: dict = {}


def create_tray_icon_image(status_color: str = "#3B82F6") -> Image.Image:
    """Creates or returns a cached sleek 64x64 tray icon with an illuminated Gemini badge."""
    if status_color in _ICON_IMAGE_CACHE:
        return _ICON_IMAGE_CACHE[status_color]

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Background rounded circle
    draw.ellipse((4, 4, 60, 60), fill="#1e222d", outline=status_color, width=3)

    # Inner lightning / diamond motif
    # Lightning coordinates
    pts = [
        (34, 12),
        (22, 34),
        (32, 34),
        (28, 52),
        (44, 28),
        (34, 28)
    ]
    draw.polygon(pts, fill=status_color)
    _ICON_IMAGE_CACHE[status_color] = image
    return image


def truncate_utf16(text: str, max_wchars: int = 127) -> str:
    """Safely truncates string so its UTF-16 wchar_t count does not exceed max_wchars."""
    cur_wchars = 0
    chars = []
    for ch in text:
        ch_wchars = 2 if ord(ch) > 0xFFFF else 1
        if cur_wchars + ch_wchars > max_wchars:
            break
        chars.append(ch)
        cur_wchars += ch_wchars
    return "".join(chars)


def format_tray_tooltip(
    display_report: Optional[dict] = None,
    active_report: Optional[dict] = None,
    all_report: Optional[dict] = None,
    account_name: str = ""
) -> str:
    """Formats a high-density, 5-line status report for the Windows system tray tooltip (< 127 chars)."""
    # 1. Resolve Account / User display name
    if not account_name:
        try:
            from core.account_manager import get_active_google_account
            account_name = get_active_google_account() or "Default"
        except Exception:
            account_name = "Default"

    # Strip domain to get clean username
    username = account_name.split("@")[0].strip() if "@" in account_name else account_name.strip()
    if not username:
        username = "Default"
    if len(username) > 15:
        username = username[:15] + "..."

    all_rep = all_report or display_report or {}
    act_rep = active_report or display_report or {}

    def _fmt(val: int) -> str:
        if val >= 1_000_000:
            return f"{val / 1_000_000:.1f}M"
        elif val >= 100_000:
            return f"{val / 1_000:.0f}K"
        elif val >= 1_000:
            return f"{val / 1_000:.1f}K"
        return str(val)

    # 5H Data
    used_5h_all = all_rep.get("tokens_5h", 0)
    used_5h_act = act_rep.get("tokens_5h", 0)
    pct_5h_rem = float(all_rep.get("pct_5h_remaining", 0.0))
    raw_reset_5h = all_rep.get("reset_5h_str", "") or "Reset"
    clean_reset_5h = raw_reset_5h.split("(")[0].strip() if "(" in raw_reset_5h else raw_reset_5h.strip()
    clean_reset_5h = clean_reset_5h.lstrip("🔄 ")

    # 7D Data
    used_7d_all = all_rep.get("tokens_7d", 0)
    used_7d_act = act_rep.get("tokens_7d", 0)
    pct_7d_rem = float(all_rep.get("pct_7d_remaining", 0.0))
    raw_reset_7d = all_rep.get("reset_7d_str", "") or "Reset"
    clean_reset_7d = raw_reset_7d.split("(")[0].strip() if "(" in raw_reset_7d else raw_reset_7d.strip()
    clean_reset_7d = clean_reset_7d.lstrip("🔄 ")

    lines = [
        f"⚡ Gemini ({username})",
        f"⏳ 5H: 🔄 {clean_reset_5h} ({pct_5h_rem:.0f}% rem)",
        f" Act: {_fmt(used_5h_act)} • All: {_fmt(used_5h_all)}",
        f"📅 7D: 🔄 {clean_reset_7d} ({pct_7d_rem:.0f}% rem)",
        f" Act: {_fmt(used_7d_act)} • All: {_fmt(used_7d_all)}"
    ]
    full_text = "\n".join(lines)
    return truncate_utf16(full_text, 127)


class SystemTrayManager:
    """Manages the Windows System Tray icon, context menu, and tooltip notifications."""

    def __init__(
        self,
        on_open_dashboard: Callable[[], None],
        on_open_mini_hud: Callable[[], None],
        on_refresh: Callable[[], None],
        on_quit: Callable[[], None],
        on_open_bubble: Optional[Callable[[], None]] = None
    ):
        self.on_open_dashboard = on_open_dashboard
        self.on_open_mini_hud = on_open_mini_hud
        self.on_open_bubble = on_open_bubble
        self.on_refresh = on_refresh
        self.on_quit = on_quit

        self.icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None
        self._last_status_color: Optional[str] = None
        self._last_tooltip_text: Optional[str] = None

    def _safe_call(self, callback: Optional[Callable[[], None]]):
        if callback:
            try:
                callback()
            except Exception:
                pass

    def start(self):
        menu = pystray.Menu(
            pystray.MenuItem("⚡ Open Dashboard", lambda: self._safe_call(self.on_open_dashboard), default=True),
            pystray.MenuItem("🗕 Floating Mini HUD", lambda: self._safe_call(self.on_open_mini_hud)),
            pystray.MenuItem("🫧 Floating Bubble", lambda: self._safe_call(self.on_open_bubble)),
            pystray.MenuItem("🔄 Refresh Now", lambda: self._safe_call(self.on_refresh)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ Exit", lambda: self._handle_quit())
        )

        initial_color = "#3B82F6"
        initial_title = "Gemini Token Counter - Live"
        self._last_status_color = initial_color
        self._last_tooltip_text = initial_title
        img = create_tray_icon_image(initial_color)
        self.icon = pystray.Icon(
            "GeminiTokenCounter",
            img,
            initial_title,
            menu=menu
        )

        self._thread = threading.Thread(target=self.icon.run, daemon=True, name="TrayThread")
        self._thread.start()

    def update_tooltip(self, tooltip_text: str, status_color: str = "#3B82F6"):
        if not self.icon:
            return

        # 1. Update tooltip text ONLY if it changed to avoid redundant Windows shell notify calls
        truncated = truncate_utf16(tooltip_text, 127)
        if truncated != self._last_tooltip_text:
            self._last_tooltip_text = truncated
            try:
                self.icon.title = truncated
            except Exception:
                pass

        # 2. Update GDI Icon image ONLY if status color changed to prevent GDI handle leaks
        if status_color != self._last_status_color:
            self._last_status_color = status_color
            try:
                self.icon.icon = create_tray_icon_image(status_color)
            except Exception:
                pass

    def _handle_quit(self):
        if self.icon:
            self.icon.stop()
        self.on_quit()

    def stop(self):
        if self.icon:
            self.icon.stop()
