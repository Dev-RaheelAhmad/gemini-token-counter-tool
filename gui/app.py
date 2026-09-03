import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
import customtkinter as ctk

from core.config import config
from core.session_finder import find_all_brain_dirs, get_brain_dirs_summary, clear_wsl_cache
from core.watcher import SessionWatcher
from core.ledger import ledger
from gui.components.quota_gauge import QuotaGauge
from gui.components.usage_chart import UsageChart
from gui.components.session_table import SessionTable
from gui.mini_hud import MiniHUD
from gui.tray import SystemTrayManager, format_tray_tooltip
from gui.analytics_dialog import AnalyticsDialog
from gui.cleaner_dialog import CleanerDialog
from gui.window_utils import apply_windows_dark_titlebar, center_window_on_screen, cancel_all_pending_after_events, get_screen_work_area, get_window_scale


def get_startup_shortcut_path() -> Optional[Path]:
    if "APPDATA" in os.environ:
        return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Gemini Token Monitor.lnk"
    return None


def is_startup_enabled() -> bool:
    p = get_startup_shortcut_path()
    return p.exists() if p else False


def set_startup_enabled(enable: bool):
    p = get_startup_shortcut_path()
    if not p:
        return
    current_state = is_startup_enabled()
    if current_state == enable:
        return  # No change required, zero overhead

    def _do_update():
        if enable:
            try:
                import subprocess
                root_dir = Path(__file__).parent.parent
                target_pyw = (root_dir / "token_counter_gui.pyw").resolve()
                ps_code = (
                    f"$WshShell = New-Object -comObject WScript.Shell; "
                    f"$s = $WshShell.CreateShortcut('{str(p)}'); "
                    f"$s.TargetPath = 'pythonw.exe'; "
                    f"$s.Arguments = '\"" + str(target_pyw).replace("'", "''") + "\"'; "
                    f"$s.WorkingDirectory = '\"" + str(root_dir).replace("'", "''") + "\"'; "
                    f"$s.Description = 'Gemini Token Monitor Startup Service'; "
                    f"$s.Save()"
                )
                creationflags = 0x08000000 if os.name == "nt" else 0
                subprocess.run(["powershell.exe", "-ExecutionPolicy", "Bypass", "-Command", ps_code],
                               capture_output=True, creationflags=creationflags)
            except Exception:
                pass
        else:
            try:
                if p.exists():
                    p.unlink(missing_ok=True)
            except Exception:
                pass

    import threading
    threading.Thread(target=_do_update, daemon=True, name="StartupShortcutWorker").start()


class GeminiTokenCounterApp(ctk.CTk):
    """Main Desktop Dashboard Window for the Gemini Token Counter with full Light/Dark support."""

    def __init__(self):
        super().__init__()

        # Appearance configuration
        theme = config.get("theme") or "dark"
        ctk.set_appearance_mode(theme)
        ctk.set_default_color_theme("blue")

        # Window properties & centered startup geometry
        self.title("Gemini Token Counter - Desktop Monitor")
        self._init_window_geometry()

        # Always on top state
        self.is_pinned = bool(config.get("always_on_top"))
        self.attributes("-topmost", self.is_pinned)

        # State tracking (Default: Currently Active User + "Active Session" scope)
        from core.account_manager import get_active_google_account
        active_email = get_active_google_account()
        saved_acc = config.get("selected_account")

        # Default to active Google account on launch
        if active_email and active_email not in ("Default", "Local", "Default / Local Account"):
            if saved_acc and saved_acc not in ("active", "active user", "👤 active user", "all", "all accounts", "", None):
                self.selected_account_filter: str = saved_acc
                self.is_all_mode: bool = False
            else:
                self.selected_account_filter = active_email
                self.is_all_mode = False
        else:
            self.selected_account_filter = "all"
            self.is_all_mode = True

        self.active_sessions_only: bool = bool(config.get("active_sessions_only", True))
        self.selected_timeframe: str = str(config.get("dashboard_timeframe") or "5h")
        self.selected_session_id: Optional[str] = None
        self.current_report: Optional[Dict[str, Any]] = None
        self.all_report: Optional[Dict[str, Any]] = None
        self.mini_hud_window: Optional[MiniHUD] = None
        self.settings_dialog_window = None
        self.analytics_dialog_window: Optional[AnalyticsDialog] = None
        self.cleaner_dialog_window: Optional[CleanerDialog] = None
        self._quota_layout_mode: Optional[str] = None
        self.account_map: Dict[str, str] = {}

        # Initialize background live watcher before building UI
        self.watcher = SessionWatcher(on_update_callback=self._on_watcher_update)

        # Build UI Structure
        self._build_ui()

        # System tray manager (marshaled onto main Tkinter UI thread for Windows 11 compatibility)
        self.tray = SystemTrayManager(
            on_open_dashboard=lambda: self._safe_after(0, self.show_dashboard),
            on_open_mini_hud=lambda: self._safe_after(0, self.show_mini_hud),
            on_open_bubble=lambda: self._safe_after(0, self.show_floating_bubble),
            on_refresh=lambda: self._safe_after(0, self.refresh_data),
            on_quit=lambda: self._safe_after(0, self.quit_application)
        )
        self.tray.start()

        # Protocol & Hotkey handling
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.bind("<Configure>", self._on_window_resize)
        self.bind("<Map>", self._on_window_map)
        self.bind("<Unmap>", self._on_window_unmap)
        self.bind("<Visibility>", self._on_window_visibility)
        self.bind("<Control-r>", lambda e: self.refresh_data())
        self.bind("<Control-R>", lambda e: self.refresh_data())
        self.bind("<F5>", lambda e: self.refresh_data())
        self.bind("<Control-m>", lambda e: self.show_mini_hud())
        self.bind("<Control-M>", lambda e: self.show_mini_hud())
        self.bind("<Escape>", lambda e: self._on_window_close())

        # Perform immediate synchronous initial poll to guarantee fully loaded data with zero 0-values
        self.watcher._poll(force=True)

        # Detect active Google account resolved from initial poll
        active_email = get_active_google_account()
        if self.selected_account_filter in ("active", "active user", "👤 active user", "Default", ""):
            if active_email and not self.is_all_mode:
                self.selected_account_filter = active_email
                self.is_all_mode = False

        # Start live monitoring
        self.watcher.start()

        # Immediate synchronous render of initial view with fully resolved account
        self._update_account_badge()
        self._apply_current_view()

        # Apply initial responsive layout based on startup dimensions
        self.update_idletasks()
        self._reflow_responsive_layout(self.winfo_width(), self.winfo_height())

        # Apply native Windows dark titlebar & caption color
        apply_windows_dark_titlebar(self)

        # Start periodic 10-second heartbeat to ensure watcher activity matches UI visibility
        self._safe_after(10000, self._heartbeat_watcher_activity)

    def _safe_after(self, delay_ms: int, func, *args):
        """Safely schedules a Tkinter .after callback only if the window exists and is not destroyed."""
        try:
            if not self.winfo_exists():
                return None
            def _wrapper(*cb_args):
                try:
                    if self.winfo_exists():
                        func(*cb_args)
                except Exception:
                    pass
            return self.after(delay_ms, _wrapper, *args)
        except Exception:
            pass
        return None

    def _schedule_apply_current_view(self, delay_ms: int = 50):
        """Debounced scheduler — coalesces multiple rapid _apply_current_view calls into one."""
        if getattr(self, '_apply_view_timer', None):
            try:
                self.after_cancel(self._apply_view_timer)
            except Exception:
                pass
        self._apply_view_timer = self._safe_after(delay_ms, self._do_apply_current_view)

    def _do_apply_current_view(self):
        """Actual execution of _apply_current_view after debounce."""
        self._apply_view_timer = None
        self._apply_current_view()

    def _build_ui(self):
        # Master container with Light/Dark backgrounds
        self.main_container = ctk.CTkFrame(self, fg_color=("#f1f5f9", "#0f131a"))
        self.main_container.pack(fill="both", expand=True, padx=12, pady=12)

        # 1. Pinned Top Header Toolbar
        self._build_header(self.main_container)

        # 2. Middle Container (Houses Scrollable Dashboard + Collapsible Side Drawer)
        self.middle_container = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.middle_container.pack(fill="both", expand=True, pady=(0, 6))

        # Build Side Panel (initially hidden/collapsed)
        self._build_side_panel(self.middle_container)

        # 3. Scrollable Body Container (Guarantees zero UI clipping across all screen heights)
        self.body_scroll = ctk.CTkScrollableFrame(
            self.middle_container,
            fg_color="transparent",
            corner_radius=0
        )
        self.body_scroll.pack(side="left", fill="both", expand=True)

        # 4. Quota & Rate Limits Section (5h and 7d Gauges)
        self._build_quota_section(self.body_scroll)

        # 6. Interactive Usage Graph (Hourly, Daily, Monthly, Yearly, Session)
        self.usage_chart = UsageChart(
            self.body_scroll,
            on_expand_callback=self._open_analytics_dialog,
            on_timeframe_changed=self._on_timeframe_changed
        )
        self.usage_chart.pack(fill="x", pady=(0, 10))

        # 7. Session Explorer
        self.session_table = SessionTable(
            self.body_scroll,
            on_select_session=self._on_session_selected,
            on_open_cleaner=self._open_cleaner_dialog,
            on_view_graph=self._open_analytics_for_session,
            on_reassign_account=self._on_session_reassigned
        )
        self.session_table.pack(fill="both", expand=True, pady=(0, 4))

        # 8. Pinned Status Footer
        self._build_footer(self.main_container)

    def _build_side_panel(self, parent):
        """Builds a collapsible slide-out Tools & Actions drawer."""
        self.is_sidebar_open = False

        self.sidebar_frame = ctk.CTkFrame(
            parent,
            width=230,
            corner_radius=12,
            fg_color=("white", "#161b26"),
            border_width=1,
            border_color=("#cbd5e1", "#283042")
        )
        self.sidebar_frame.pack_propagate(False)

        # Side panel header
        s_top = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        s_top.pack(fill="x", padx=12, pady=(12, 6))

        s_title = ctk.CTkLabel(
            s_top,
            text="🧭 Tools & Actions",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#0f172a", "#f8fafc")
        )
        s_title.pack(side="left")

        s_close = ctk.CTkButton(
            s_top,
            text="✕",
            width=24,
            height=24,
            corner_radius=6,
            fg_color="transparent",
            hover_color=("#e2e8f0", "#283042"),
            text_color=("#64748b", "#94a3b8"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.toggle_side_panel
        )
        s_close.pack(side="right")

        ctk.CTkFrame(self.sidebar_frame, height=1, fg_color=("#e2e8f0", "#283042")).pack(fill="x", padx=12, pady=(0, 8))

        # Quick Actions List
        self.sidebar_refresh_btn = ctk.CTkButton(
            self.sidebar_frame,
            text="🔄  Refresh Data",
            anchor="w",
            height=32,
            corner_radius=8,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            text_color="#ffffff",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.refresh_data
        )
        self.sidebar_refresh_btn.pack(fill="x", padx=10, pady=2)

        self.sidebar_analytics_btn = ctk.CTkButton(
            self.sidebar_frame,
            text="📊  Usage Analytics",
            anchor="w",
            height=32,
            corner_radius=8,
            fg_color=("#f1f5f9", "#1f2633"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._open_analytics_dialog
        )
        self.sidebar_analytics_btn.pack(fill="x", padx=10, pady=2)

        self.sidebar_pin_btn = ctk.CTkButton(
            self.sidebar_frame,
            text="📌  Pin Always on Top",
            anchor="w",
            height=32,
            corner_radius=8,
            fg_color=("#f1f5f9", "#1f2633"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._toggle_always_on_top_sidebar
        )
        self.sidebar_pin_btn.pack(fill="x", padx=10, pady=2)

        self.sidebar_hud_btn = ctk.CTkButton(
            self.sidebar_frame,
            text="🗕  Floating Mini HUD",
            anchor="w",
            height=32,
            corner_radius=8,
            fg_color=("#f1f5f9", "#1f2633"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.show_mini_hud
        )
        self.sidebar_hud_btn.pack(fill="x", padx=10, pady=2)

        self.sidebar_bubble_btn = ctk.CTkButton(
            self.sidebar_frame,
            text="🫧  Floating Bubble",
            anchor="w",
            height=32,
            corner_radius=8,
            fg_color=("#f1f5f9", "#1f2633"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.show_floating_bubble
        )
        self.sidebar_bubble_btn.pack(fill="x", padx=10, pady=2)

        self.sidebar_cleaner_btn = ctk.CTkButton(
            self.sidebar_frame,
            text="🧹  Storage Cleaner",
            anchor="w",
            height=32,
            corner_radius=8,
            fg_color=("#f1f5f9", "#1f2633"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._open_cleaner_dialog
        )
        self.sidebar_cleaner_btn.pack(fill="x", padx=10, pady=2)

        self.sidebar_settings_btn = ctk.CTkButton(
            self.sidebar_frame,
            text="⚙  Settings & Paths",
            anchor="w",
            height=32,
            corner_radius=8,
            fg_color=("#f1f5f9", "#1f2633"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._open_settings_dialog
        )
        self.sidebar_settings_btn.pack(fill="x", padx=10, pady=2)

        # Theme Selector Row
        ctk.CTkFrame(self.sidebar_frame, height=1, fg_color=("#e2e8f0", "#283042")).pack(fill="x", padx=12, pady=(10, 8))

        theme_row = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        theme_row.pack(fill="x", padx=12, pady=2)

        ctk.CTkLabel(
            theme_row,
            text="🌓 Theme",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#475569", "#94a3b8")
        ).pack(side="left")

        self.theme_menu = ctk.CTkOptionMenu(
            theme_row,
            values=["Dark", "Light", "System"],
            command=self._on_theme_changed,
            height=26,
            width=85,
            font=ctk.CTkFont(size=10, weight="bold")
        )
        self.theme_menu.set(str(config.get("theme") or "dark").capitalize())
        self.theme_menu.pack(side="right")

    def toggle_side_panel(self):
        """Toggles the visibility of the Tools & Actions side panel."""
        self.is_sidebar_open = not self.is_sidebar_open
        if self.is_sidebar_open:
            self.body_scroll.pack_forget()
            self.sidebar_frame.pack(side="left", fill="y", padx=(0, 8))
            self.body_scroll.pack(side="left", fill="both", expand=True)
            if hasattr(self, "sidebar_toggle_btn"):
                self.sidebar_toggle_btn.configure(
                    fg_color=("#ef4444", "#dc2626"),
                    hover_color=("#dc2626", "#b91c1c"),
                    text_color="#ffffff",
                    text="✕ Panel"
                )
        else:
            self.sidebar_frame.pack_forget()
            if hasattr(self, "sidebar_toggle_btn"):
                self.sidebar_toggle_btn.configure(
                    fg_color=("#3B82F6", "#2563eb"),
                    hover_color=("#2563eb", "#1d4ed8"),
                    text_color="#ffffff",
                    text="🧭 Panel"
                )

    def _toggle_always_on_top_sidebar(self):
        self._toggle_always_on_top()
        if hasattr(self, "sidebar_pin_btn"):
            self.sidebar_pin_btn.configure(
                text="📌  Pinned (Always Top)" if self.is_pinned else "📌  Pin Always on Top",
                fg_color="#3B82F6" if self.is_pinned else ("#f1f5f9", "#1f2633"),
                text_color="#ffffff" if self.is_pinned else ("#0f172a", "#f8fafc")
            )

    def _on_theme_changed(self, new_theme: str):
        theme_val = new_theme.lower()
        ctk.set_appearance_mode(theme_val)
        config.set("theme", theme_val)
        self._update_all_titlebar_themes(theme_val)

    def _update_all_titlebar_themes(self, theme_val: Optional[str] = None):
        apply_windows_dark_titlebar(self, theme_val)
        if self.settings_dialog_window and self.settings_dialog_window.winfo_exists():
            apply_windows_dark_titlebar(self.settings_dialog_window, theme_val)
        if self.analytics_dialog_window and self.analytics_dialog_window.winfo_exists():
            apply_windows_dark_titlebar(self.analytics_dialog_window, theme_val)
        if self.cleaner_dialog_window and self.cleaner_dialog_window.winfo_exists():
            apply_windows_dark_titlebar(self.cleaner_dialog_window, theme_val)

    def _build_header(self, parent):
        self.header_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.header_frame.pack(fill="x", pady=(0, 8))

        # Left: Panel Toggle Button + App Brand & Live status badge & Account switcher
        self.header_left = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.header_left.pack(side="left")

        # 1. 🧭 Panel Toggle Button (Bright, high-contrast, fully clickable)
        self.sidebar_toggle_btn = ctk.CTkButton(
            self.header_left,
            text="🧭 Panel",
            width=72,
            height=28,
            corner_radius=6,
            fg_color=("#3B82F6", "#2563eb"),
            hover_color=("#2563eb", "#1d4ed8"),
            text_color="#ffffff",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.toggle_side_panel
        )
        self.sidebar_toggle_btn.pack(side="left", padx=(0, 6))

        self.title_label = ctk.CTkLabel(
            self.header_left,
            text="⚡ Gemini Monitor",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=("#0f172a", "#f8fafc")
        )
        self.title_label.pack(side="left", padx=(0, 6))

        self.live_badge = ctk.CTkLabel(
            self.header_left,
            text="● Live",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("#15803d", "#10B981"),
            corner_radius=10,
            fg_color=("#dcfce7", "#162520"),
            padx=7,
            pady=2
        )
        self.live_badge.pack(side="left", padx=(0, 6))

        # Compact Interactive Account Dropdown Selector (Never overflows)
        self.account_menu = ctk.CTkOptionMenu(
            self.header_left,
            values=["All"],
            command=self._on_main_account_selected,
            height=28,
            width=130,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("#dbeafe", "#1e3a5f"),
            text_color=("#1d4ed8", "#93c5fd"),
            button_color=("#bfdbfe", "#2563eb"),
            button_hover_color=("#93c5fd", "#1d4ed8")
        )
        self.account_menu.pack(side="left")

        self._update_account_badge()

        # Right: Pin + Mini HUD + Refresh + Tools Dropdown
        self.header_right = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.header_right.pack(side="right")

        # 1. ☰ Tools Dropdown Menu (on the far right)
        self.tools_menu = ctk.CTkOptionMenu(
            self.header_right,
            values=[
                "📊 Usage Analytics",
                "🧹 Storage Cleaner",
                "⚙ Settings & Paths",
                "🌓 Switch Theme"
            ],
            command=self._on_tools_menu_selected,
            height=28,
            width=100,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("#2563eb", "#3B82F6"),
            text_color="#ffffff",
            button_color=("#1d4ed8", "#2563eb"),
            button_hover_color=("#1e40af", "#1d4ed8")
        )
        self.tools_menu.set("☰ Tools ▾")
        self.tools_menu.pack(side="right", padx=(3, 0))

        # 2. 1-Click Refresh Button
        self.refresh_btn = ctk.CTkButton(
            self.header_right,
            text="🔄 Refresh",
            width=76,
            height=28,
            corner_radius=6,
            fg_color=("#e2e8f0", "#1e222d"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.refresh_data
        )
        self.refresh_btn.pack(side="right", padx=3)

        # 3. Mini HUD Button
        self.hud_btn = ctk.CTkButton(
            self.header_right,
            text="🗕 Mini HUD",
            width=78,
            height=28,
            corner_radius=6,
            fg_color=("#e2e8f0", "#1e222d"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.show_mini_hud
        )
        self.hud_btn.pack(side="right", padx=3)

        # 4. Floating Bubble Button
        self.bubble_btn = ctk.CTkButton(
            self.header_right,
            text="🫧 Bubble",
            width=76,
            height=28,
            corner_radius=6,
            fg_color=("#e2e8f0", "#1e222d"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.show_floating_bubble
        )
        self.bubble_btn.pack(side="right", padx=3)

        # 5. Pin Button
        self.pin_btn = ctk.CTkButton(
            self.header_right,
            text="📌 Pinned" if self.is_pinned else "📌 Pin",
            width=65,
            height=28,
            corner_radius=6,
            fg_color="#3B82F6" if self.is_pinned else ("#e2e8f0", "#1e222d"),
            hover_color=("#2563eb", "#3B82F6"),
            text_color="#ffffff" if self.is_pinned else ("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._toggle_always_on_top
        )
        self.pin_btn.pack(side="right", padx=3)

    def _on_tools_menu_selected(self, value: str):
        if "Analytics" in value or "📊" in value:
            self._open_analytics_dialog()
        elif "HUD" in value or "🗕" in value:
            self.show_mini_hud()
        elif "Cleaner" in value or "🧹" in value:
            self._open_cleaner_dialog()
        elif "Settings" in value or "⚙" in value:
            self._open_settings_dialog()
        elif "Pin" in value or "📌" in value:
            self._toggle_always_on_top()
        elif "Theme" in value or "🌓" in value:
            cur = config.get("theme") or "dark"
            new_t = "light" if cur == "dark" else "dark"
            self._on_theme_changed(new_t)
        self.tools_menu.set("☰ Tools ▾")

    def _build_quota_section(self, parent):
        self.quota_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.quota_frame.pack(fill="x", pady=(0, 10))
        self.quota_frame.columnconfigure((0, 1), weight=1, uniform="quota_col")

        limit_5h = int(config.get("limit_5h") or 1000000)
        limit_7d = int(config.get("limit_7d") or 4000000)

        # 5-Hour Quota Gauge
        self.gauge_5h = QuotaGauge(
            self.quota_frame,
            title="5-Hour Limit",
            icon="⏳",
            default_limit=limit_5h
        )
        self.gauge_5h.grid(row=0, column=0, padx=(0, 4), sticky="nsew")

        # 7-Day Quota Gauge
        self.gauge_7d = QuotaGauge(
            self.quota_frame,
            title="7-Day Limit",
            icon="📅",
            default_limit=limit_7d
        )
        self.gauge_7d.grid(row=0, column=1, padx=(4, 0), sticky="nsew")
        self._quota_layout_mode = "2col"

    def _build_footer(self, parent):
        self.footer_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.footer_frame.pack(fill="x", side="bottom")

        brain_dirs = find_all_brain_dirs()
        path_str = str(brain_dirs[0]) if brain_dirs else "Not Found"
        if len(path_str) > 60:
            path_str = "..." + path_str[-55:]

        self.brain_label = ctk.CTkLabel(
            self.footer_frame,
            text=f"📁 Brain Path: {path_str}",
            font=ctk.CTkFont(size=11),
            text_color=("#475569", "#64748b")
        )
        self.brain_label.pack(side="left")

        self.velocity_label = ctk.CTkLabel(
            self.footer_frame,
            text="⚡ Burn Velocity: Idle",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#1d4ed8", "#60a5fa")
        )
        self.velocity_label.pack(side="left", padx=(20, 0))

        self.time_label = ctk.CTkLabel(
            self.footer_frame,
            text="🕒 Initializing...",
            font=ctk.CTkFont(size=11),
            text_color=("#475569", "#64748b")
        )
        self.time_label.pack(side="right")

    def _on_watcher_update(self, active_report: Dict[str, Any], all_report: Dict[str, Any], sessions: List[Dict]):
        def _apply_from_worker():
            if not self.winfo_exists():
                return
            from core.account_manager import get_active_google_account
            active_email = get_active_google_account()
            if self.selected_account_filter in ("active", "active user", "👤 active user", "Default", ""):
                if active_email and not self.is_all_mode:
                    self.selected_account_filter = active_email

            self.current_report = active_report
            self.all_report = all_report
            self._schedule_apply_current_view(delay_ms=20)

        self._safe_after(0, _apply_from_worker)

    def _apply_current_view(self):
        """
        Synchronously computes and applies multi-dimensional filtered metrics to all UI widgets:
          Target Data = f(Account, Active Sessions Only, Time Window)
        """
        if not self.winfo_exists():
            return
        from core.account_manager import get_active_google_account
        active_google_account = get_active_google_account() or "Default"
        sessions = self.watcher.latest_sessions or []
        active_sid = sessions[0].get("session_id") if sessions else None

        # Resolve target account alias if needed
        if self.selected_account_filter in ("active", "active user", "👤 active user"):
            if active_google_account and active_google_account not in ("Default", "Local"):
                self.selected_account_filter = active_google_account
                self.is_all_mode = False

        # 1. Compute dual reports for the dashboard cards (with smart fingerprint caching)
        import time
        now = time.time()
        view_fp = (
            self.selected_account_filter,
            self.selected_session_id,
            self.selected_timeframe,
            self.active_sessions_only,
            active_sid,
            getattr(self.watcher, "_last_sessions_fingerprint", None)
        )
        if (
            view_fp == getattr(self, "_last_view_fp", None)
            and getattr(self, "_cached_active_report", None) is not None
            and getattr(self, "_cached_all_report", None) is not None
            and (now - getattr(self, "_last_view_calc_time", 0.0) < 3.0)
        ):
            active_report = self._cached_active_report
            all_report = self._cached_all_report
        else:
            active_report = ledger.get_filtered_report(
                account_email=self.selected_account_filter,
                active_only=True,
                session_id=self.selected_session_id,
                timeframe=self.selected_timeframe,
                active_session_id=active_sid
            )
            all_report = ledger.get_filtered_report(
                account_email=self.selected_account_filter,
                active_only=False,
                session_id=self.selected_session_id,
                timeframe=self.selected_timeframe,
                active_session_id=active_sid
            )
            self._last_view_fp = view_fp
            self._cached_active_report = active_report
            self._cached_all_report = all_report
            self._last_view_calc_time = now
        
        # We still use one primary report for table and gauge logic (mostly all_report)
        display_report = all_report

        limit_5h = int(config.get("limit_5h") or 1000000)
        limit_7d = int(config.get("limit_7d") or 4000000)

        # Check if main dashboard UI is visible in viewport
        is_main_viewable = False
        try:
            is_main_viewable = bool(self.winfo_exists() and self.state() == "normal" and self.winfo_viewable())
        except Exception:
            pass

        if is_main_viewable:
            # 2. Update Scope / Live Badge
            if hasattr(self, "live_badge"):
                if self.active_sessions_only or self.selected_session_id == "ACTIVE_CHAT":
                    self.live_badge.configure(
                        text="● Active",
                        fg_color=("#dcfce7", "#162520"),
                        text_color=("#15803d", "#10B981")
                    )
                elif self.selected_session_id and self.selected_session_id != "ACTIVE_CHAT":
                    self.live_badge.configure(
                        text="💬 Chat",
                        fg_color=("#fef3c7", "#2d2315"),
                        text_color=("#b45309", "#f59e0b")
                    )
                elif self.is_all_mode or self.selected_account_filter in ("all", "all accounts", "", None):
                    self.live_badge.configure(
                        text="★ All",
                        fg_color=("#ede9fe", "#261b3d"),
                        text_color=("#6d28d9", "#c084fc")
                    )
                else:
                    self.live_badge.configure(
                        text="👤 User",
                        fg_color=("#dbeafe", "#1e3a5f"),
                        text_color=("#1d4ed8", "#93c5fd")
                    )

            self._update_session_scope_btn_style()

            # 3. Update Gauges with Quotas and Google Recovery times
            pct_5h_rem = display_report.get("pct_5h_remaining", 0.0)
            pct_7d_rem = display_report.get("pct_7d_remaining", 0.0)

            self.gauge_5h.set_title("⏳  5-Hour Limit")
            self.gauge_7d.set_title("📅  7-Day Limit")

            self.gauge_5h.update_data(
                display_report.get("tokens_5h", 0),
                display_report.get("reset_5h_str", "No recent usage"),
                pct_remaining=pct_5h_rem,
                custom_limit=limit_5h,
                active_thinking_toks=active_report.get("thinking_5h", 0),
                active_prompt_toks=active_report.get("prompt_5h", 0),
                active_candidates_toks=active_report.get("candidates_5h", 0),
                all_thinking_toks=all_report.get("thinking_5h", 0),
                all_prompt_toks=all_report.get("prompt_5h", 0),
                all_candidates_toks=all_report.get("candidates_5h", 0),
                active_total_toks=active_report.get("tokens_5h", 0),
                all_total_toks=all_report.get("tokens_5h", 0),
            )
            self.gauge_7d.update_data(
                display_report.get("tokens_7d", 0),
                display_report.get("reset_7d_str", "No weekly usage"),
                pct_remaining=pct_7d_rem,
                custom_limit=limit_7d,
                active_thinking_toks=active_report.get("thinking_7d", 0),
                active_prompt_toks=active_report.get("prompt_7d", 0),
                active_candidates_toks=active_report.get("candidates_7d", 0),
                all_thinking_toks=all_report.get("thinking_7d", 0),
                all_prompt_toks=all_report.get("prompt_7d", 0),
                all_candidates_toks=all_report.get("candidates_7d", 0),
                active_total_toks=active_report.get("tokens_7d", 0),
                all_total_toks=all_report.get("tokens_7d", 0),
            )

            # 5. Update Usage Graph with time-series records matching selected scope & timeframe
            self.usage_chart.set_dual_records(
                active_records=active_report.get("records", []),
                all_records=all_report.get("records", []),
                timeframe=self.selected_timeframe
            )

            # 6. Update Session Table matching active account and active_only filter
            matching_ids = display_report.get("matching_session_ids", [])
            target_clean = self.selected_account_filter.lower()
            target_user = target_clean.split('@')[0] if '@' in target_clean else target_clean

            if self.is_all_mode or self.selected_account_filter in ("all", "all accounts", "", None):
                if self.active_sessions_only:
                    table_sessions = [sessions[0]] if sessions else []
                else:
                    table_sessions = sessions
            else:
                table_sessions = []
                for s in sessions:
                    sid = s.get("session_id", "")
                    sess_entry = ledger.sessions.get(sid, {})
                    acc_usage = sess_entry.get("account_usage", {})
                    s_act = s.get("account", "").lower()
                    is_match = (
                        sid in matching_ids
                        or s_act == target_clean
                        or s_act == target_user
                        or ('@' in s_act and s_act.split('@')[0] == target_user)
                        or (target_clean == active_google_account.lower() and s_act in ("default", "local", ""))
                    )
                    u_tok = 0
                    for k, udata in acc_usage.items():
                        k_clean = k.lower()
                        if k_clean == target_clean or ('@' in k_clean and k_clean.split('@')[0] == target_user) or (target_clean == active_google_account.lower() and k_clean in ("default", "local", "")):
                            is_match = True
                            u_tok += udata.get("total", 0)

                    if is_match:
                        s_dict = dict(s)
                        if u_tok > 0:
                            s_dict["tokens"] = u_tok
                        s_dict["account"] = self.selected_account_filter
                        table_sessions.append(s_dict)

                if self.active_sessions_only and table_sessions:
                    table_sessions = [table_sessions[0]]

            self.session_table.set_sessions(table_sessions)
            self.session_table.set_selection_mode(
                is_all=self.is_all_mode,
                session_id=self.selected_session_id,
                active_only=self.active_sessions_only
            )

            # 7. Update Footer & Velocity
            burn_rate_str = display_report.get("burn_rate_str", "Idle")
            if hasattr(self, "velocity_label"):
                self.velocity_label.configure(text=f"⚡ Burn Velocity: {burn_rate_str}")

            now_str = datetime.now().strftime("%I:%M:%S %p")
            self.time_label.configure(text=f"🕒 Updated at {now_str}")

            # 8. Update Account Dropdown Menu
            self._update_account_badge()

        # 9. Store display report and update Mini HUD with pre-computed reports
        self.current_report = display_report
        if self.mini_hud_window and self.mini_hud_window.winfo_exists():
            self.mini_hud_window.update_data(report=all_report, session_report=active_report)

        # 10. Update System Tray Tooltip & Icon
        used_5h = display_report.get("tokens_5h", 0)
        pct_5h = (used_5h / limit_5h) * 100 if limit_5h > 0 else 0
        tray_text = format_tray_tooltip(
            display_report=display_report,
            active_report=active_report,
            all_report=all_report,
            account_name=active_google_account
        )
        tray_color = "#EF4444" if pct_5h >= 85 else ("#F59E0B" if pct_5h >= 60 else "#3B82F6")
        self.tray.update_tooltip(tray_text, status_color=tray_color)

        # 11. Refresh active Analytics Dialog if open
        if self.analytics_dialog_window and self.analytics_dialog_window.winfo_exists():
            try:
                if self.analytics_dialog_window.state() != "iconic":
                    self.analytics_dialog_window._load_data()
            except Exception:
                pass

    def _on_session_selected(self, session_id: Optional[str], mode_all: bool):
        if mode_all:
            self.selected_account_filter = "all"
            self.is_all_mode = True
            self.selected_session_id = None
            self.active_sessions_only = False
            self.watcher.set_target(session_id=None, mode_all=True)
        elif session_id == "ACTIVE_CHAT":
            self.active_sessions_only = True
            self.selected_session_id = None
            self.watcher.set_target(session_id="ACTIVE_CHAT", mode_all=False)
        elif session_id is None:
            # Active User quick-select clicked
            from core.account_manager import get_active_google_account
            active_email = get_active_google_account()
            self.selected_account_filter = active_email or "active"
            self.is_all_mode = False
            self.selected_session_id = None
            self.active_sessions_only = False
            self.watcher.set_target(session_id=None, mode_all=False)
        else:
            self.selected_session_id = session_id
            self.watcher.set_target(session_id=session_id, mode_all=False)

        config.set("selected_account", self.selected_account_filter, save_now=False)
        config.set("active_sessions_only", self.active_sessions_only, save_now=False)
        self._apply_current_view()
        self.watcher.force_refresh()

    def _on_session_reassigned(self, session_id: str, new_account: str):
        self.watcher.force_refresh()
        self._schedule_apply_current_view(50)

    def _toggle_always_on_top(self):
        self.is_pinned = not self.is_pinned
        self.attributes("-topmost", self.is_pinned)
        config.set("always_on_top", self.is_pinned)
        for dlg in (self.settings_dialog_window, self.analytics_dialog_window, self.cleaner_dialog_window):
            if dlg and dlg.winfo_exists():
                try:
                    dlg.attributes("-topmost", self.is_pinned)
                except Exception:
                    pass
        if hasattr(self, "pin_btn"):
            self.pin_btn.configure(
                text="📌 Pinned" if self.is_pinned else "📌 Pin",
                fg_color="#3B82F6" if self.is_pinned else ("#e2e8f0", "#1e222d"),
                text_color="#ffffff" if self.is_pinned else ("#0f172a", "#f8fafc")
            )
        if hasattr(self, "sidebar_pin_btn"):
            self.sidebar_pin_btn.configure(
                text="📌  Pinned (Always Top)" if self.is_pinned else "📌  Pin Always on Top",
                fg_color="#3B82F6" if self.is_pinned else ("#f1f5f9", "#1f2633"),
                text_color="#ffffff" if self.is_pinned else ("#0f172a", "#f8fafc")
            )

    def show_mini_hud(self):
        self.withdraw()
        
        # Ensure latest calculations matching current dropdown selection are computed
        self._apply_current_view()

        if self.mini_hud_window is None or not self.mini_hud_window.winfo_exists():
            self.mini_hud_window = MiniHUD(
                self,
                on_restore_callback=self.show_dashboard,
                on_visibility_change=self._update_watcher_activity
            )
        
        # Always display the full Mini-Hub window when opened from parent dashboard
        self.mini_hud_window.is_minimized = False
        self.mini_hud_window.is_hover_expanded = False
        self.mini_hud_window._apply_view_mode()
        self.mini_hud_window.deiconify()
        self.mini_hud_window.lift()
        self.mini_hud_window.focus_force()
        if getattr(self.mini_hud_window, "is_pinned", False):
            self.mini_hud_window.attributes("-topmost", True)
        if self.current_report:
            self.mini_hud_window.update_data(self.current_report)
        self.mini_hud_window._recalculate_geometry()
        self._update_watcher_activity()

    def show_floating_bubble(self):
        """Directly activates and displays the compact Floating Bubble mode from the parent dashboard."""
        self.withdraw()
        
        # Ensure latest calculations matching current dropdown selection are computed
        self._apply_current_view()

        if self.mini_hud_window is None or not self.mini_hud_window.winfo_exists():
            self.mini_hud_window = MiniHUD(
                self,
                on_restore_callback=self.show_dashboard,
                on_visibility_change=self._update_watcher_activity
            )
        
        # Open directly in compact Floating Bubble mode
        self.mini_hud_window.is_minimized = True
        self.mini_hud_window.is_hover_expanded = False
        config.set("hud_minimized", True, save_now=False)
        self.mini_hud_window._apply_view_mode()
        self.mini_hud_window.deiconify()
        self.mini_hud_window.lift()
        self.mini_hud_window.focus_force()
        if getattr(self.mini_hud_window, "is_pinned", False):
            self.mini_hud_window.attributes("-topmost", True)
        if self.current_report:
            self.mini_hud_window.update_data(self.current_report)
        self.mini_hud_window._recalculate_geometry()
        self._update_watcher_activity()

    def show_dashboard(self):
        if self.mini_hud_window and self.mini_hud_window.winfo_exists():
            self.mini_hud_window.withdraw()
        self.deiconify()
        self.lift()
        self.focus_force()
        self._update_watcher_activity()
        self.refresh_data()

    def refresh_data(self):
        self._update_account_badge()
        self._apply_current_view()
        self.watcher.force_refresh()

    def _init_window_geometry(self):
        """
        Initializes window geometry and positioning:
        - Compact, balanced default size (900x600) centered on screen for Full HD and all displays.
        - Dynamically adjusted to never exceed screen boundaries.
        - Flexible minimum window size (540x440) for user resizing freedom.
        - Restores custom window size and position accurately, ignoring full-screen snaps.
        """
        default_w = 900
        default_h = 600

        try:
            self.update_idletasks()
            scale = get_window_scale(self)
            wl, wt, wr, wb = get_screen_work_area(self)
            work_w = wr - wl
            work_h = wb - wt

            phys_def_w = int(round(default_w * scale))
            phys_def_h = int(round(default_h * scale))

            target_w = default_w if phys_def_w <= work_w else max(540, int(work_w / scale))
            target_h = default_h if phys_def_h <= work_h else max(440, int(work_h / scale))
            t_phys_w = int(round(target_w * scale))
            t_phys_h = int(round(target_h * scale))

            raw_geom = config.get("window_geometry") or ""
            if raw_geom:
                import re
                match = re.match(r"^(\d+)x(\d+)(?:([+-]?\d+)([+-]\d+))?$", str(raw_geom).strip())
                if match:
                    lw = int(match.group(1))
                    lh = int(match.group(2))
                    if lw > 1400 or lh > 1000:
                        # Revert legacy oversized/maximized full-screen geometry to 900x600 centered
                        cx = max(wl, wl + (work_w - t_phys_w) // 2)
                        cy = max(wt, wt + (work_h - t_phys_h) // 2)
                        final_geom = f"{target_w}x{target_h}+{cx}+{cy}"
                    else:
                        w = max(540, min(lw, int(work_w / scale)))
                        h = max(440, min(lh, int(work_h / scale)))
                        pw = int(round(w * scale))
                        ph = int(round(h * scale))
                        x_str = match.group(3)
                        y_str = match.group(4)

                        if x_str is not None and y_str is not None:
                            x = int(x_str)
                            y = int(y_str)
                            if (wl - pw + 50) <= x <= (wr - 50) and (wt - ph + 50) <= y <= (wb - 50):
                                final_geom = f"{w}x{h}+{x}+{y}"
                            else:
                                cx = max(wl, wl + (work_w - pw) // 2)
                                cy = max(wt, wt + (work_h - ph) // 2)
                                final_geom = f"{w}x{h}+{cx}+{cy}"
                        else:
                            cx = max(wl, wl + (work_w - pw) // 2)
                            cy = max(wt, wt + (work_h - ph) // 2)
                            final_geom = f"{w}x{h}+{cx}+{cy}"
                else:
                    cx = max(wl, wl + (work_w - t_phys_w) // 2)
                    cy = max(wt, wt + (work_h - t_phys_h) // 2)
                    final_geom = f"{target_w}x{target_h}+{cx}+{cy}"
            else:
                cx = max(wl, wl + (work_w - t_phys_w) // 2)
                cy = max(wt, wt + (work_h - t_phys_h) // 2)
                final_geom = f"{target_w}x{target_h}+{cx}+{cy}"
        except Exception:
            final_geom = f"{default_w}x{default_h}"

        self.geometry(final_geom)
        self.minsize(540, 440)

    def _reflow_responsive_layout(self, width: int, height: int):
        """Dynamically reflows header title, metric cards, and quota gauges based on window width."""
        # 1. Header title reflow
        if hasattr(self, "title_label"):
            if width < 720:
                self.title_label.configure(text="⚡ Gemini", font=ctk.CTkFont(size=15, weight="bold"))
            else:
                self.title_label.configure(text="⚡ Gemini Monitor", font=ctk.CTkFont(size=16, weight="bold"))

        # 2. Quota Gauges reflow (2 cols vs 1 col stacked)
        if hasattr(self, "quota_frame"):
            if width >= 750:
                if self._quota_layout_mode != "2col":
                    self._quota_layout_mode = "2col"
                    self.quota_frame.columnconfigure((0, 1), weight=1, uniform="quota_col")
                    self.gauge_5h.grid(row=0, column=0, columnspan=1, padx=(0, 4), pady=0, sticky="nsew")
                    self.gauge_7d.grid(row=0, column=1, columnspan=1, padx=(4, 0), pady=0, sticky="nsew")
            else:
                if self._quota_layout_mode != "1col":
                    self._quota_layout_mode = "1col"
                    self.quota_frame.columnconfigure((0, 1), weight=1, uniform="")
                    self.gauge_5h.grid(row=0, column=0, columnspan=2, padx=0, pady=(0, 6), sticky="nsew")
                    self.gauge_7d.grid(row=1, column=0, columnspan=2, padx=0, pady=0, sticky="nsew")

    def _save_current_window_geometry(self, save_now: bool = True):
        try:
            # Do not save dimensions if window is minimized (iconic) or maximized (zoomed)
            if self.state() not in ("iconic", "zoomed"):
                w = self.winfo_width()
                h = self.winfo_height()
                x = self.winfo_x()
                y = self.winfo_y()
                if 400 <= w <= 1600 and 300 <= h <= 1200:
                    geo = f"{w}x{h}{'+' if x >= 0 else ''}{x}{'+' if y >= 0 else ''}{y}"
                    config.set("window_geometry", geo, save_now=save_now)
        except Exception:
            pass

    def _on_window_close(self):
        self._save_current_window_geometry(save_now=True)
        if self.mini_hud_window and self.mini_hud_window.winfo_exists():
            try:
                self.mini_hud_window._save_position()
            except Exception:
                pass
        if config.get("close_to_tray"):
            self.withdraw()
            self._update_watcher_activity()
        else:
            self.quit_application()

    def _on_window_map(self, event):
        if event.widget == self:
            self._safe_after(50, self._update_watcher_activity)
            self._schedule_apply_current_view(delay_ms=60)

    def _on_window_unmap(self, event):
        if event.widget == self:
            self._safe_after(50, self._update_watcher_activity)

    def _on_window_visibility(self, event):
        if event.widget == self:
            self._safe_after(50, self._update_watcher_activity)
            self._schedule_apply_current_view(delay_ms=60)

    def _heartbeat_watcher_activity(self):
        """Periodic 10-second safety check ensuring background watcher pause/resume stays in exact sync with UI state."""
        try:
            self._update_watcher_activity()
        finally:
            if self.winfo_exists():
                self._safe_after(10000, self._heartbeat_watcher_activity)

    @staticmethod
    def _is_window_active(win) -> bool:
        """Helper returning True if a Tk/CTk window exists, is mapped, and is not minimized or withdrawn."""
        try:
            return bool(win and win.winfo_exists() and win.state() in ("normal", "zoomed") and win.winfo_viewable())
        except Exception:
            return False

    def _update_watcher_activity(self):
        """
        Dynamically controls background watcher synchronization:
        - If ANY window of this tool (main parent window, Mini-Hub, Floating Bubble, dialogs, popups)
          is visible and active -> watcher runs normally.
        - If ALL UI windows are minimized, closed to tray, or hidden -> watcher is paused
          with 0% CPU, 0 disk I/O, and zero background processing.
        """
        import tkinter as tk

        # 1. Collect root window and all child toplevels (MiniHUD, Bubble, dialogs)
        candidate_windows = [self]
        try:
            candidate_windows.extend(w for w in self.winfo_children() if isinstance(w, (ctk.CTkToplevel, tk.Toplevel)))
        except Exception:
            pass

        # 2. Also check explicitly tracked window attributes in case any is detached or separately managed
        for attr in ("mini_hud_window", "analytics_dialog_window", "cleaner_dialog_window", "settings_dialog_window"):
            w = getattr(self, attr, None)
            if w and w not in candidate_windows:
                candidate_windows.append(w)

        # 3. Single-place unified evaluation
        ui_is_in_view = any(self._is_window_active(w) for w in candidate_windows)

        if ui_is_in_view:
            if self.watcher.is_paused():
                self.watcher.resume()
        else:
            if not self.watcher.is_paused():
                self.watcher.pause()

    def _on_window_resize(self, event):
        if event.widget == self:
            w = event.width
            h = event.height
            if (w, h) != getattr(self, "_last_window_dim", (None, None)):
                self._last_window_dim = (w, h)
                self._reflow_responsive_layout(w, h)
                self._save_current_window_geometry(save_now=False)

    def _on_main_account_selected(self, value: str):
        if hasattr(self, "account_map") and value in self.account_map:
            target_acc = self.account_map[value]
        elif "all" in value.lower():
            target_acc = "all"
        else:
            from core.account_manager import get_active_google_account, get_all_known_accounts_list
            active_email = get_active_google_account()
            known_accounts = get_all_known_accounts_list()
            cleaned = value.replace("👤", "").strip()
            matched_acc = next((a for a in known_accounts if a.split('@')[0].lower() == cleaned.lower() or a.lower() == cleaned.lower()), None)
            if not matched_acc:
                if active_email and (active_email.split('@')[0].lower() == cleaned.lower() or active_email.lower() == cleaned.lower()):
                    matched_acc = active_email
                else:
                    matched_acc = cleaned
            target_acc = matched_acc

        if target_acc == "all":
            self.selected_account_filter = "all"
            self.is_all_mode = True
            config.set("selected_account", "all", save_now=False)
        else:
            self.selected_account_filter = target_acc
            self.is_all_mode = False
            config.set("selected_account", self.selected_account_filter, save_now=False)

        self.selected_session_id = None
        self._apply_current_view()
        self.watcher.force_refresh()

    def _toggle_session_scope(self):
        pass

    def _update_session_scope_btn_style(self):
        pass

    def _on_session_scope_changed(self, value: str):
        self.active_sessions_only = (value == "Active Session")
        self.selected_session_id = None
        config.set("active_sessions_only", self.active_sessions_only, save_now=False)
        self._update_session_scope_btn_style()
        self._apply_current_view()
        self.watcher.force_refresh()

    def _on_timeframe_changed(self, timeframe: str):
        self.selected_timeframe = timeframe
        config.set("dashboard_timeframe", self.selected_timeframe, save_now=False)
        self._apply_current_view()

    def _update_account_badge(self):
        """Updates the active account dropdown menu options."""
        from core.account_manager import get_active_google_account, get_all_known_accounts_list
        active_email = get_active_google_account()
        known_accounts = get_all_known_accounts_list()

        last_active = getattr(self, "_last_detected_active_email", None)
        if active_email and (last_active is None or active_email.lower() != last_active.lower()):
            self._last_detected_active_email = active_email

        valid_known = [a for a in known_accounts if a not in ("Default", "Local", "Default / Local Account")]
        num_accs = len(valid_known) if valid_known else (1 if active_email else 0)
        all_label = f"★ All Accounts ({num_accs})" if num_accs > 0 else "★ All Accounts"
        user_clean = active_email.split('@')[0] if active_email else "User"
        active_label = f"👤 {user_clean}"

        self.account_map = {all_label: "all", "All": "all", "★ All Accounts": "all"}
        menu_values = [all_label]

        # Followed by the active user account if present
        if active_email and active_email not in ("Default", "Local", "Default / Local Account"):
            menu_values.append(active_label)
            self.account_map[active_label] = active_email

        # Followed by other known accounts
        for acc in known_accounts:
            if acc != active_email and acc not in ("Default", "Local", "Default / Local Account"):
                acc_clean = acc.split('@')[0] if '@' in acc else acc
                lbl = f"👤 {acc_clean}"
                if lbl in self.account_map:
                    lbl = f"👤 {acc}"
                if lbl not in menu_values:
                    menu_values.append(lbl)
                    self.account_map[lbl] = acc

        if hasattr(self, "account_menu"):
            if getattr(self, "_last_account_menu_values", None) != menu_values:
                self._last_account_menu_values = list(menu_values)
                self.account_menu.configure(values=menu_values)

            if self.is_all_mode or self.selected_account_filter in ("all", "all accounts", "", None) or "all" in str(self.selected_account_filter).lower():
                target_label = all_label
            else:
                target_label = None
                for lbl, acc in self.account_map.items():
                    if acc.lower() == self.selected_account_filter.lower():
                        target_label = lbl
                        break
                if not target_label:
                    acc_clean = self.selected_account_filter.split('@')[0] if '@' in self.selected_account_filter else self.selected_account_filter
                    target_label = next((m for m in menu_values if acc_clean.lower() in m.lower()), all_label)

            if self.account_menu.get() != target_label:
                self.account_menu.set(target_label)

        if hasattr(self, "session_scope_seg"):
            target_seg = "Active Session" if self.active_sessions_only else "All Sessions"
            if self.session_scope_seg.get() != target_seg:
                self.session_scope_seg.set(target_seg)

    def _open_analytics_dialog(self):
        acc = "all" if self.is_all_mode else self.selected_account_filter
        active_only = self.active_sessions_only
        sess_id = self.selected_session_id
        timeframe = self.selected_timeframe

        if self.analytics_dialog_window and self.analytics_dialog_window.winfo_exists():
            self.analytics_dialog_window.sync_with_dashboard(
                account_email=acc,
                active_only=active_only,
                session_id=sess_id,
                timeframe=timeframe
            )
            self._raise_analytics_dialog()
            self._safe_after(50, self._raise_analytics_dialog)
            return

        self.analytics_dialog_window = AnalyticsDialog(
            self,
            account_email=acc,
            active_only=active_only,
            session_id=sess_id,
            timeframe=timeframe
        )
        self._safe_after(50, self._raise_analytics_dialog)
        self._update_watcher_activity()

    def _open_analytics_for_session(self, session_id: str):
        if self.analytics_dialog_window and self.analytics_dialog_window.winfo_exists():
            self.analytics_dialog_window.sync_with_dashboard(
                account_email="all",
                active_only=False,
                session_id=session_id,
                timeframe=self.selected_timeframe
            )
            self._raise_analytics_dialog()
            self._safe_after(50, self._raise_analytics_dialog)
            self._update_watcher_activity()
            return

        self.analytics_dialog_window = AnalyticsDialog(
            self,
            account_email="all",
            active_only=False,
            session_id=session_id,
            timeframe=self.selected_timeframe
        )
        self._safe_after(50, self._raise_analytics_dialog)
        self._update_watcher_activity()

    def _raise_analytics_dialog(self):
        """Ensures the analytics dialog is brought smoothly to the foreground above main window."""
        if self.analytics_dialog_window and self.analytics_dialog_window.winfo_exists():
            try:
                if self.analytics_dialog_window.state() == "iconic":
                    self.analytics_dialog_window.state("normal")
                self.analytics_dialog_window.deiconify()
                self.analytics_dialog_window.lift()
                self.analytics_dialog_window.focus_force()
                if hasattr(self.analytics_dialog_window, "_bring_to_front"):
                    self.analytics_dialog_window._bring_to_front()
            except Exception:
                pass
            self._update_watcher_activity()

    def _open_cleaner_dialog(self):
        if self.cleaner_dialog_window and self.cleaner_dialog_window.winfo_exists():
            self.cleaner_dialog_window._refresh_session_list()
            self.cleaner_dialog_window.deiconify()
            self.cleaner_dialog_window.lift()
            self.cleaner_dialog_window.focus_force()
            self._update_watcher_activity()
            return

        self.cleaner_dialog_window = CleanerDialog(self, on_cleanup_complete=self.refresh_data)
        self._update_watcher_activity()

    def _open_settings_dialog(self):
        from tkinter import filedialog

        if self.settings_dialog_window and self.settings_dialog_window.winfo_exists():
            self.settings_dialog_window.deiconify()
            self.settings_dialog_window.lift()
            self.settings_dialog_window.focus_force()
            return

        dialog = ctk.CTkToplevel(self)
        dialog.withdraw()  # Withdraw during setup to prevent initial white frame flash
        dialog.title("Settings - Gemini Token Monitor")
        dialog.geometry("620x680")
        dialog.minsize(560, 600)
        dialog.resizable(True, True)
        self.settings_dialog_window = dialog

        # Maintain parent-child window stacking relationship
        try:
            dialog.transient(self)
        except Exception:
            pass

        # Inherit topmost if main window is pinned / topmost
        try:
            if self.is_pinned or (hasattr(self, "attributes") and self.attributes("-topmost")):
                dialog.attributes("-topmost", True)
        except Exception:
            pass

        scroll_container = ctk.CTkScrollableFrame(
            dialog,
            fg_color=("white", "#161b26"),
            border_width=1,
            border_color=("#e2e8f0", "#2a3040")
        )
        scroll_container.pack(fill="both", expand=True, padx=16, pady=16)

        # Title
        ctk.CTkLabel(
            scroll_container,
            text="⚙ Settings & Preferences",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=("#0f172a", "#f8fafc")
        ).pack(anchor="w", pady=(0, 14))

        # ---------------- Section 1: Quota Limits & Display ----------------
        sec1_frame = ctk.CTkFrame(
            scroll_container,
            corner_radius=10,
            fg_color=("#f8fafc", "#1e222d"),
            border_width=1,
            border_color=("#e2e8f0", "#2a3040")
        )
        sec1_frame.pack(fill="x", pady=(0, 14), padx=2)

        ctk.CTkLabel(
            sec1_frame,
            text="📊 QUOTA LIMITS & DASHBOARD DISPLAY",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#475569", "#94a3b8")
        ).pack(anchor="w", padx=14, pady=(10, 6))

        # Manual Limits Checkbox
        show_limits_var = ctk.BooleanVar(value=bool(config.get("show_manual_limits", False)))
        show_limits_cb = ctk.CTkCheckBox(
            sec1_frame,
            text="Show manual token limit caps on dashboard (e.g. / 1.0M limit)",
            variable=show_limits_var,
            onvalue=True,
            offvalue=False,
            font=ctk.CTkFont(size=12),
            text_color=("#0f172a", "#f8fafc")
        )
        if show_limits_var.get():
            show_limits_cb.select()
        else:
            show_limits_cb.deselect()
        show_limits_cb.pack(anchor="w", padx=14, pady=(2, 6))

        # Windows Startup Checkbox
        startup_var = ctk.BooleanVar(value=is_startup_enabled())
        startup_cb = ctk.CTkCheckBox(
            sec1_frame,
            text="Launch Gemini Token Monitor automatically on Windows Startup",
            variable=startup_var,
            onvalue=True,
            offvalue=False,
            font=ctk.CTkFont(size=12),
            text_color=("#0f172a", "#f8fafc")
        )
        if startup_var.get():
            startup_cb.select()
        else:
            startup_cb.deselect()
        startup_cb.pack(anchor="w", padx=14, pady=(2, 10))

        # 5h Limit
        ctk.CTkLabel(sec1_frame, text="5-Hour Token Limit (Quota):", font=ctk.CTkFont(size=12), text_color=("#0f172a", "#f8fafc")).pack(anchor="w", padx=14)
        lim_5h_entry = ctk.CTkEntry(sec1_frame, height=30, fg_color=("white", "#161b26"), border_color=("#cbd5e1", "#2d3748"), text_color=("#0f172a", "#f8fafc"))
        lim_5h_entry.insert(0, str(config.get("limit_5h")))
        lim_5h_entry.pack(fill="x", padx=14, pady=(2, 8))

        # 7d Limit
        ctk.CTkLabel(sec1_frame, text="7-Day (Weekly) Token Limit:", font=ctk.CTkFont(size=12), text_color=("#0f172a", "#f8fafc")).pack(anchor="w", padx=14)
        lim_7d_entry = ctk.CTkEntry(sec1_frame, height=30, fg_color=("white", "#161b26"), border_color=("#cbd5e1", "#2d3748"), text_color=("#0f172a", "#f8fafc"))
        lim_7d_entry.insert(0, str(config.get("limit_7d")))
        lim_7d_entry.pack(fill="x", padx=14, pady=(2, 8))

        # Refresh Interval & Theme in 2 cols
        opts_row = ctk.CTkFrame(sec1_frame, fg_color="transparent")
        opts_row.pack(fill="x", padx=14, pady=(0, 12))
        opts_row.columnconfigure((0, 1), weight=1)

        ref_col = ctk.CTkFrame(opts_row, fg_color="transparent")
        ref_col.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkLabel(ref_col, text="Auto-Refresh (sec):", font=ctk.CTkFont(size=12), text_color=("#0f172a", "#f8fafc")).pack(anchor="w")
        interval_entry = ctk.CTkEntry(ref_col, height=30, fg_color=("white", "#161b26"), border_color=("#cbd5e1", "#2d3748"), text_color=("#0f172a", "#f8fafc"))
        interval_entry.insert(0, str(config.get("refresh_interval_sec")))
        interval_entry.pack(fill="x", pady=(2, 0))

        theme_col = ctk.CTkFrame(opts_row, fg_color="transparent")
        theme_col.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ctk.CTkLabel(theme_col, text="Appearance Theme:", font=ctk.CTkFont(size=12), text_color=("#0f172a", "#f8fafc")).pack(anchor="w")
        theme_menu = ctk.CTkOptionMenu(theme_col, values=["dark", "light", "system"], height=30)
        theme_menu.set(str(config.get("theme")))
        theme_menu.pack(fill="x", pady=(2, 0))

        # ---------------- Section 2: Mini HUD Customization ----------------
        sec2_frame = ctk.CTkFrame(
            scroll_container,
            corner_radius=10,
            fg_color=("#f8fafc", "#1e222d"),
            border_width=1,
            border_color=("#e2e8f0", "#2a3040")
        )
        sec2_frame.pack(fill="x", pady=(0, 14), padx=2)

        ctk.CTkLabel(
            sec2_frame,
            text="🗕 FLOATING MINI HUD (MINI HUB) OPTIONS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#475569", "#94a3b8")
        ).pack(anchor="w", padx=14, pady=(10, 6))

        hud_5h_var = ctk.BooleanVar(value=bool(config.get("hud_show_5h", True)))
        hud_7d_var = ctk.BooleanVar(value=bool(config.get("hud_show_7d", True)))
        hud_sess_var = ctk.BooleanVar(value=bool(config.get("hud_show_session", True)))
        hud_think_var = ctk.BooleanVar(value=bool(config.get("hud_show_thinking", True)))
        hud_io_var = ctk.BooleanVar(value=bool(config.get("hud_show_io", True)))
        hud_prog_var = ctk.BooleanVar(value=bool(config.get("hud_show_progress", True)))
        hud_mini_var = ctk.BooleanVar(value=bool(config.get("hud_minimized", False)))

        cb_grid = ctk.CTkFrame(sec2_frame, fg_color="transparent")
        cb_grid.pack(fill="x", padx=14, pady=(0, 8))
        cb_grid.columnconfigure((0, 1), weight=1)

        cb1 = ctk.CTkCheckBox(cb_grid, text="⏳ 5-Hour Burn & Reset", variable=hud_5h_var, onvalue=True, offvalue=False, font=ctk.CTkFont(size=12), text_color=("#0f172a", "#f8fafc"))
        cb1.grid(row=0, column=0, sticky="w", pady=4)
        if hud_5h_var.get(): cb1.select()
        else: cb1.deselect()

        cb2 = ctk.CTkCheckBox(cb_grid, text="📅 7-Day / Weekly Burn", variable=hud_7d_var, onvalue=True, offvalue=False, font=ctk.CTkFont(size=12), text_color=("#0f172a", "#f8fafc"))
        cb2.grid(row=0, column=1, sticky="w", pady=4)
        if hud_7d_var.get(): cb2.select()
        else: cb2.deselect()

        cb3 = ctk.CTkCheckBox(cb_grid, text="⚡ Active Session Total", variable=hud_sess_var, onvalue=True, offvalue=False, font=ctk.CTkFont(size=12), text_color=("#0f172a", "#f8fafc"))
        cb3.grid(row=1, column=0, sticky="w", pady=4)
        if hud_sess_var.get(): cb3.select()
        else: cb3.deselect()

        cb4 = ctk.CTkCheckBox(cb_grid, text="🧠 Thinking Tokens", variable=hud_think_var, onvalue=True, offvalue=False, font=ctk.CTkFont(size=12), text_color=("#0f172a", "#f8fafc"))
        cb4.grid(row=1, column=1, sticky="w", pady=4)
        if hud_think_var.get(): cb4.select()
        else: cb4.deselect()

        cb5 = ctk.CTkCheckBox(cb_grid, text="📥 Input / Output Breakdown", variable=hud_io_var, onvalue=True, offvalue=False, font=ctk.CTkFont(size=12), text_color=("#0f172a", "#f8fafc"))
        cb5.grid(row=2, column=0, sticky="w", pady=4)
        if hud_io_var.get(): cb5.select()
        else: cb5.deselect()

        cb6 = ctk.CTkCheckBox(cb_grid, text="📊 Google Recovery Bar", variable=hud_prog_var, onvalue=True, offvalue=False, font=ctk.CTkFont(size=12), text_color=("#0f172a", "#f8fafc"))
        cb6.grid(row=2, column=1, sticky="w", pady=4)
        if hud_prog_var.get(): cb6.select()
        else: cb6.deselect()

        cb7 = ctk.CTkCheckBox(cb_grid, text="🫧 Start in Floating Bubble Mode", variable=hud_mini_var, onvalue=True, offvalue=False, font=ctk.CTkFont(size=12), text_color=("#0f172a", "#f8fafc"))
        cb7.grid(row=3, column=0, columnspan=2, sticky="w", pady=4)
        if hud_mini_var.get(): cb7.select()
        else: cb7.deselect()

        # Opacity Slider
        op_row = ctk.CTkFrame(sec2_frame, fg_color="transparent")
        op_row.pack(fill="x", padx=14, pady=(4, 12))
        
        cur_op = float(config.get("mini_hud_opacity") if config.get("mini_hud_opacity") is not None else 1.0)
        op_label = ctk.CTkLabel(op_row, text=f"Mini HUD Opacity: {int(cur_op*100)}%", font=ctk.CTkFont(size=12), text_color=("#0f172a", "#f8fafc"))
        op_label.pack(anchor="w")

        def _on_op_change(val):
            op_label.configure(text=f"Mini HUD Opacity: {int(val*100)}%")

        op_slider = ctk.CTkSlider(op_row, from_=0.50, to=1.00, number_of_steps=50, command=_on_op_change)
        op_slider.set(cur_op)
        op_slider.pack(fill="x", pady=(2, 0))

        # ---------------- Section 3: Brain & .gemini Paths Manager ----------------
        sec3_frame = ctk.CTkFrame(
            scroll_container,
            corner_radius=10,
            fg_color=("#f8fafc", "#1e222d"),
            border_width=1,
            border_color=("#e2e8f0", "#2a3040")
        )
        sec3_frame.pack(fill="x", pady=(0, 14), padx=2)

        ctk.CTkLabel(
            sec3_frame,
            text="📁 DISCOVERED & CUSTOM .GEMINI PATHS (WINDOWS & WSL2)",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#475569", "#94a3b8")
        ).pack(anchor="w", padx=14, pady=(10, 6))

        paths_list_frame = ctk.CTkFrame(sec3_frame, fg_color="transparent")
        paths_list_frame.pack(fill="x", padx=14, pady=(0, 8))

        custom_paths_list = list(config.get("custom_brain_dirs") or [])

        def _refresh_paths_ui():
            for child in paths_list_frame.winfo_children():
                child.destroy()

            summaries = get_brain_dirs_summary(custom_dirs=custom_paths_list)
            for item in summaries:
                row = ctk.CTkFrame(paths_list_frame, corner_radius=6, fg_color=("white", "#161b26"), height=32, border_width=1, border_color=("#e2e8f0", "#232936"))
                row.pack(fill="x", pady=2)

                badge_bg = "#3B82F6" if "WSL" in item["type"] else ("#8B5CF6" if "Custom" in item["type"] else "#10B981")
                type_lbl = ctk.CTkLabel(
                    row,
                    text=f" {item['type']} ",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    text_color="#ffffff",
                    corner_radius=4,
                    fg_color=badge_bg,
                    height=20
                )
                type_lbl.pack(side="left", padx=(6, 6), pady=4)

                p_text = item["path"]
                if len(p_text) > 42:
                    p_text = "..." + p_text[-38:]

                p_lbl = ctk.CTkLabel(
                    row,
                    text=f"{p_text} ({item['session_count']} sessions)",
                    font=ctk.CTkFont(size=11),
                    text_color=("#0f172a", "#cbd5e1"),
                    anchor="w"
                )
                p_lbl.pack(side="left", fill="x", expand=True, padx=4)

                if item["is_custom"] or item["path"] in custom_paths_list:
                    rem_btn = ctk.CTkButton(
                        row,
                        text="✕",
                        width=22,
                        height=22,
                        corner_radius=4,
                        fg_color="#ef4444",
                        hover_color="#dc2626",
                        text_color="#ffffff",
                        font=ctk.CTkFont(size=11, weight="bold"),
                        command=lambda p=item["path"]: _remove_custom_path(p)
                    )
                    rem_btn.pack(side="right", padx=6, pady=4)

        def _remove_custom_path(path_str):
            if path_str in custom_paths_list:
                custom_paths_list.remove(path_str)
            _refresh_paths_ui()

        # Add Custom Path Row
        add_row = ctk.CTkFrame(sec3_frame, fg_color="transparent")
        add_row.pack(fill="x", padx=14, pady=(0, 12))

        custom_path_entry = ctk.CTkEntry(
            add_row,
            placeholder_text="Enter or paste custom path (Windows / WSL UNC / Drive)...",
            height=32,
            fg_color=("white", "#161b26"),
            border_color=("#cbd5e1", "#2d3748"),
            text_color=("#0f172a", "#f8fafc")
        )
        custom_path_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        def _browse_dir():
            chosen = filedialog.askdirectory(title="Select .gemini Brain Directory", parent=dialog)
            if chosen:
                custom_path_entry.delete(0, "end")
                custom_path_entry.insert(0, chosen)

        browse_btn = ctk.CTkButton(
            add_row,
            text="📁 Browse",
            width=75,
            height=32,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=_browse_dir
        )
        browse_btn.pack(side="left", padx=(0, 6))

        def _add_custom():
            val = custom_path_entry.get().strip()
            if val and val not in custom_paths_list:
                custom_paths_list.append(val)
                custom_path_entry.delete(0, "end")
                _refresh_paths_ui()

        add_btn = ctk.CTkButton(
            add_row,
            text="+ Add",
            width=65,
            height=32,
            corner_radius=6,
            fg_color="#3B82F6",
            hover_color="#2563EB",
            text_color="#ffffff",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=_add_custom
        )
        add_btn.pack(side="left")

        _refresh_paths_ui()

        # ---------------- Section 4: Google Account & Cloud Quotas ----------------
        sec4_frame = ctk.CTkFrame(
            scroll_container,
            corner_radius=10,
            fg_color=("#f8fafc", "#1e222d"),
            border_width=1,
            border_color=("#e2e8f0", "#2a3040")
        )
        sec4_frame.pack(fill="x", pady=(0, 14), padx=2)

        ctk.CTkLabel(
            sec4_frame,
            text="👤 GOOGLE ACCOUNT IDENTITY & CLOUD LIMITS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#475569", "#94a3b8")
        ).pack(anchor="w", padx=14, pady=(10, 4))

        from core.account_manager import get_active_google_account, get_all_google_accounts
        acc_info = get_all_google_accounts()
        active_email_text = acc_info.get("active_account", "Local Account")

        acc_box = ctk.CTkFrame(sec4_frame, corner_radius=6, fg_color=("white", "#161b26"), border_width=1, border_color=("#e2e8f0", "#232936"))
        acc_box.pack(fill="x", padx=14, pady=(2, 6))

        ctk.CTkLabel(
            acc_box,
            text=f"Active Google Login: {active_email_text}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#1d4ed8", "#93c5fd")
        ).pack(anchor="w", padx=10, pady=(6, 2))

        ctk.CTkLabel(
            acc_box,
            text="💡 Note: Google rate limits are tracked cloud-side per Google Account. Active Session mode measures your current chat's burn rate matching Antigravity 2.0.",
            font=ctk.CTkFont(size=10),
            text_color=("#64748b", "#94a3b8"),
            wraplength=480,
            justify="left"
        ).pack(anchor="w", padx=10, pady=(0, 8))

        # ---------------- Save Button ----------------
        def _save_settings():
            try:
                new_5h = int(lim_5h_entry.get().replace(",", "").strip())
                new_7d = int(lim_7d_entry.get().replace(",", "").strip())
                new_int = int(interval_entry.get().strip())
                new_theme = theme_menu.get()
                new_show_limits = bool(show_limits_var.get())

                old_theme = str(config.get("theme", "dark"))
                old_custom_paths = list(config.get("custom_brain_dirs") or [])

                config.set("limit_5h", new_5h, save_now=False)
                config.set("limit_7d", new_7d, save_now=False)
                config.set("show_manual_limits", new_show_limits, save_now=False)
                config.set("refresh_interval_sec", new_int, save_now=False)
                config.set("theme", new_theme, save_now=False)
                config.set("custom_brain_dirs", custom_paths_list, save_now=False)

                # Save HUD options
                config.set("hud_show_5h", bool(hud_5h_var.get()), save_now=False)
                config.set("hud_show_7d", bool(hud_7d_var.get()), save_now=False)
                config.set("hud_show_session", bool(hud_sess_var.get()), save_now=False)
                config.set("hud_show_thinking", bool(hud_think_var.get()), save_now=False)
                config.set("hud_show_io", bool(hud_io_var.get()), save_now=False)
                config.set("hud_show_progress", bool(hud_prog_var.get()), save_now=False)
                config.set("hud_minimized", bool(hud_mini_var.get()), save_now=False)
                config.set("mini_hud_opacity", round(op_slider.get(), 2), save_now=True)

                # Only redraw theme if actually changed
                if new_theme != old_theme:
                    ctk.set_appearance_mode(new_theme)

                # Update startup shortcut non-blockingly
                set_startup_enabled(startup_var.get())

                # Only clear cache if custom brain paths changed
                if custom_paths_list != old_custom_paths:
                    clear_wsl_cache()

                # Destroy settings dialog cleanly and immediately for 0ms instant UI response
                self.settings_dialog_window = None
                dialog.destroy()

                # Instant UI refresh on main window
                self._apply_current_view()

                # Update mini hud if active
                if self.mini_hud_window and self.mini_hud_window.winfo_exists():
                    self.mini_hud_window.is_minimized = bool(hud_mini_var.get())
                    self.mini_hud_window._apply_view_mode()
                    self.mini_hud_window._build_sections()
                    if self.current_report:
                        self.mini_hud_window.update_data(self.current_report)

                # Trigger background refresh without blocking
                self.watcher.force_refresh()
            except ValueError:
                pass

        clean_btn = ctk.CTkButton(
            scroll_container,
            text="🧹 Clean Old Sessions & Free Disk Space",
            height=34,
            corner_radius=8,
            fg_color=("#fee2e2", "#2e1818"),
            hover_color=("#fecaca", "#dc2626"),
            text_color=("#b91c1c", "#f87171"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._open_cleaner_dialog
        )
        clean_btn.pack(fill="x", pady=(0, 10))

        save_btn = ctk.CTkButton(
            scroll_container,
            text="Save Settings & Re-scan",
            height=38,
            corner_radius=8,
            fg_color="#3B82F6",
            hover_color="#2563EB",
            text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=_save_settings
        )
        save_btn.pack(fill="x", pady=(0, 12))

        # Center dialog and apply dark titlebar attributes BEFORE displaying on screen
        center_window_on_screen(dialog, 580, 620)
        dialog.minsize(520, 500)
        apply_windows_dark_titlebar(dialog)

        def _on_dialog_close():
            self.settings_dialog_window = None
            try:
                dialog.destroy()
            except Exception:
                pass
            self._update_watcher_activity()

        dialog.protocol("WM_DELETE_WINDOW", _on_dialog_close)
        dialog.bind("<Escape>", lambda e: _on_dialog_close())

        # Show fully rendered window smoothly
        dialog.deiconify()
        dialog.lift()
        dialog.focus_force()
        self._update_watcher_activity()

    def destroy(self):
        cancel_all_pending_after_events(self)
        try:
            self.update_idletasks()
        except Exception:
            pass
        try:
            if hasattr(self, "watcher") and self.watcher:
                self.watcher.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "tray") and self.tray:
                self.tray.stop()
        except Exception:
            pass
        for dlg in (getattr(self, "settings_dialog_window", None),
                    getattr(self, "analytics_dialog_window", None),
                    getattr(self, "cleaner_dialog_window", None),
                    getattr(self, "mini_hud_window", None)):
            if dlg and hasattr(dlg, "winfo_exists") and dlg.winfo_exists():
                try:
                    cancel_all_pending_after_events(dlg)
                    dlg.destroy()
                except Exception:
                    pass
        cancel_all_pending_after_events(self)
        super().destroy()

    def quit_application(self):
        self._save_current_window_geometry(save_now=True)
        if self.mini_hud_window and self.mini_hud_window.winfo_exists():
            try:
                self.mini_hud_window._save_position()
            except Exception:
                pass
        config.save()
        try:
            from core.ledger import ledger
            ledger.flush_to_disk(force=True)
        except Exception:
            pass
        self.watcher.stop()
        self.tray.stop()
        self.destroy()
        sys.exit(0)
