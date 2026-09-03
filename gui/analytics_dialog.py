import customtkinter as ctk
from tkinter import filedialog, messagebox
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple

from core.ledger import ledger
from core.account_manager import get_active_google_account, get_all_known_accounts_list
from core.session_finder import get_all_session_files
from core.cleaner import paginate_items
from core.analytics import (
    export_analytics_csv,
    export_analytics_json
)
from gui.components.usage_chart import UsageChart
from gui.components.stat_card import StatCard
from gui.window_utils import apply_windows_dark_titlebar, center_window_on_screen


class AnalyticsDialog(ctk.CTkToplevel):
    """
    Dedicated, full-featured Usage Graph & Analytics Window.
    Provides comprehensive time-series analysis, scope switching,
    an interactive canvas chart, breakdown data table, and CSV/JSON export tools.
    Fully synchronized with the main dashboard view logic and controls.
    """

    def __init__(
        self,
        master,
        default_session_id: Optional[str] = None,
        account_email: Optional[str] = None,
        active_only: bool = False,
        session_id: Optional[str] = None,
        timeframe: Optional[str] = None,
        **kwargs
    ):
        super().__init__(master, **kwargs)
        self.withdraw()  # Withdraw during setup to prevent initial white frame flash
        self.title("📊 Gemini Token Analytics & Usage Graph")
        center_window_on_screen(self, 1040, 680)
        self.minsize(860, 560)
        self.resizable(True, True)

        self.transient(master)

        # Inherit topmost state if parent is pinned / topmost
        try:
            if getattr(master, "is_pinned", False) or (hasattr(master, "attributes") and master.attributes("-topmost")):
                self.attributes("-topmost", True)
        except Exception:
            pass

        # Resolve initial scope:
        # Default: Active user, All Sessions (active_only=False), Timeframe=5H
        active_email = get_active_google_account()
        self.target_account: str = active_email or "active"
        self.target_active_only: bool = False
        self.target_session_id: Optional[str] = None

        if account_email is not None or active_only or session_id is not None:
            self.target_account = account_email if account_email is not None else (active_email or "active")
            self.target_active_only = active_only
            self.target_session_id = session_id
        elif default_session_id:
            if default_session_id in ("active_session", "session", "ACTIVE_CHAT"):
                self.target_account = active_email or "active"
                self.target_active_only = True
                self.target_session_id = None
            elif default_session_id in ("active_user", "active"):
                self.target_account = active_email or "active"
                self.target_active_only = False
                self.target_session_id = None
            elif default_session_id == "all":
                self.target_account = "all"
                self.target_active_only = False
                self.target_session_id = None
            elif default_session_id.startswith("account:"):
                self.target_account = default_session_id.replace("account:", "").strip()
                self.target_active_only = False
                self.target_session_id = None
            else:
                self.target_account = "all"
                self.target_active_only = False
                self.target_session_id = default_session_id

        self.selected_timeframe: str = (timeframe or "5h").lower()
        self.raw_records: List[Tuple[Optional[datetime], int, int, int]] = []
        self.current_buckets: List[Dict[str, Any]] = []
        self.current_summary: Dict[str, Any] = {}
        self.account_map: Dict[str, Tuple[str, Optional[str]]] = {}

        # Table Pagination State (Strict max 10 intervals per page)
        self.table_page: int = 1
        self.table_page_size: int = 10
        self.table_total_pages: int = 1

        self._build_ui()
        self._load_data()

        # Key bindings
        self.bind("<Escape>", lambda e: self.destroy())

        # Apply dark titlebar attributes BEFORE displaying on screen
        apply_windows_dark_titlebar(self)

        # Show fully rendered window smoothly and guarantee foreground elevation
        self.deiconify()
        self.lift()
        self.focus_force()
        self._safe_after(20, self._bring_to_front)
        self._safe_after(120, self._bring_to_front)

    def _safe_after(self, delay_ms: int, func, *args):
        """Safely schedules after callback if window exists."""
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

    def _bring_to_front(self):
        """Ensures the analytics window is raised above the parent dashboard and focused."""
        if not self.winfo_exists():
            return
        try:
            if self.state() == "iconic":
                self.state("normal")
            self.deiconify()
            self.lift()
            is_parent_topmost = getattr(self.master, "is_pinned", False) or (
                hasattr(self.master, "attributes") and self.master.attributes("-topmost")
            )
            # Momentarily enforce topmost to guarantee z-order elevation above parent on Windows
            self.attributes("-topmost", True)
            if not is_parent_topmost:
                self._safe_after(250, self._release_topmost)
            self.focus_force()
            import sys
            if sys.platform.startswith("win"):
                import ctypes
                hwnd = self.winfo_id()
                ctypes.windll.user32.BringWindowToTop(hwnd)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _release_topmost(self):
        """Releases the temporary topmost flag so window stacks normally."""
        if not self.winfo_exists():
            return
        try:
            is_parent_topmost = getattr(self.master, "is_pinned", False) or (
                hasattr(self.master, "attributes") and self.master.attributes("-topmost")
            )
            if not is_parent_topmost:
                self.attributes("-topmost", False)
        except Exception:
            pass

    @property
    def selected_scope(self) -> str:
        """Backward-compatibility property for legacy callers & tests."""
        if self.target_session_id:
            return self.target_session_id
        if self.target_active_only:
            return "active_session"
        if self.target_account in ("all", "all accounts", "", None):
            return "all"
        if self.target_account in ("active", "active user"):
            return "active_user"
        return f"account:{self.target_account}"

    @selected_scope.setter
    def selected_scope(self, val: str):
        """Backward-compatibility setter for legacy callers & tests."""
        if val in ("active_session", "session", "ACTIVE_CHAT"):
            self.target_active_only = True
            self.target_session_id = None
        elif val in ("active_user", "active"):
            self.target_account = "active"
            self.target_session_id = None
        elif val in ("all", "all accounts"):
            self.target_account = "all"
            self.target_session_id = None
        elif val.startswith("account:"):
            self.target_account = val.replace("account:", "").strip()
            self.target_session_id = None
        else:
            self.target_account = "all"
            self.target_session_id = val

        matched_lbl = self._find_matching_account_label(
            self.target_account,
            self.target_session_id
        )
        if hasattr(self, "account_menu") and matched_lbl:
            self.account_menu.set(matched_lbl)
        if hasattr(self, "session_scope_seg"):
            self.session_scope_seg.set("Active Session" if self.target_active_only else "All Sessions")

    def _build_ui(self):
        # Scrollable master frame
        self.main_container = ctk.CTkScrollableFrame(
            self,
            fg_color=("#f1f5f9", "#0f131a"),
            corner_radius=0
        )
        self.main_container.pack(fill="both", expand=True)

        # 1. Header Toolbar & Filters
        self._build_filters(self.main_container)

        # 2. Stat Summary Cards Row (4 cards)
        self._build_stat_cards(self.main_container)

        # 3. Chart Container
        self.chart_container = ctk.CTkFrame(
            self.main_container,
            corner_radius=12,
            fg_color=("white", "#1e222d"),
            border_width=1,
            border_color=("#e2e8f0", "#2a3040")
        )
        self.chart_container.pack(fill="x", padx=16, pady=(0, 14))

        self.chart = UsageChart(
            self.chart_container,
            on_expand_callback=None,
            on_timeframe_changed=self._on_timeframe_changed
        )
        self.chart.canvas_height = 180
        self.chart.canvas.configure(height=180)
        self.chart.pack(fill="both", expand=True, padx=4, pady=4)

        # 4. Detailed Data Table Frame
        self._build_data_table(self.main_container)

        # 5. Export Actions Footer
        self._build_footer(self.main_container)

    def _build_filters(self, parent):
        hdr = ctk.CTkFrame(
            parent,
            corner_radius=12,
            fg_color=("white", "#1e222d"),
            border_width=1,
            border_color=("#e2e8f0", "#2a3040")
        )
        hdr.pack(fill="x", padx=16, pady=(16, 14))

        # Title & Account Count Badge
        top_row = ctk.CTkFrame(hdr, fg_color="transparent")
        top_row.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            top_row,
            text="📊 Historical Token Consumption & Usage Graphs",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=("#0f172a", "#f8fafc")
        ).pack(side="left")

        active_email = get_active_google_account()
        known_accounts = get_all_known_accounts_list()
        valid_known = [a for a in known_accounts if a not in ("Default", "Local", "Default / Local Account")]
        num_accs = len(valid_known) if valid_known else (1 if active_email else 0)

        if num_accs > 0:
            ctk.CTkLabel(
                top_row,
                text=f"👥 {num_accs} Accounts Tracked",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=("#1d4ed8", "#38bdf8"),
                fg_color=("#dbeafe", "#1e293b"),
                corner_radius=6,
                padx=8,
                pady=3
            ).pack(side="right", padx=(0, 4))

        # Scope Selector & Timeframe Row
        filter_row = ctk.CTkFrame(hdr, fg_color="transparent")
        filter_row.pack(fill="x", padx=14, pady=(0, 12))

        # Left 1: Account Dropdown Selector
        ctk.CTkLabel(
            filter_row,
            text="Account:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#475569", "#94a3b8")
        ).pack(side="left", padx=(0, 6))

        all_label = f"★ All Accounts ({num_accs})" if num_accs > 0 else "★ All Accounts"
        user_clean = active_email.split('@')[0] if active_email else "User"
        active_label = f"👤 {user_clean}" if active_email else "👤 Active User"

        account_values = [all_label]
        self.account_map = {
            all_label: ("all", None),
            "All": ("all", None),
            "★ All Accounts": ("all", None)
        }

        # Add active user
        if active_email and active_email not in ("Default", "Local", "Default / Local Account"):
            account_values.append(active_label)
            self.account_map[active_label] = (active_email, None)

        # Add other known accounts
        for acc in known_accounts:
            if acc != active_email and acc not in ("Default", "Local", "Default / Local Account"):
                acc_clean = acc.split('@')[0] if '@' in acc else acc
                lbl = f"👤 {acc_clean}"
                if lbl not in account_values:
                    account_values.append(lbl)
                    self.account_map[lbl] = (acc, None)

        self.account_menu = ctk.CTkOptionMenu(
            filter_row,
            values=account_values,
            command=self._on_account_changed,
            width=200,
            height=30,
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.scope_menu = self.account_menu  # Legacy alias

        matched_account_label = self._find_matching_account_label(
            self.target_account,
            self.target_session_id
        )
        self.account_menu.set(matched_account_label)
        self.account_menu.pack(side="left", padx=(0, 10))

        spacer = ctk.CTkFrame(filter_row, width=0, height=0, fg_color="transparent")
        spacer.pack(side="left", expand=True, fill="x")

        # Right: Timeframe Segmented Control (Default: 5H)
        ctk.CTkLabel(
            filter_row,
            text="Timeframe:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#475569", "#94a3b8")
        ).pack(side="left", padx=(0, 6))

        self.timeframe_seg = ctk.CTkSegmentedButton(
            filter_row,
            values=["5H", "24H", "7D", "30D", "Month", "Year", "Session"],
            command=self._on_timeframe_changed,
            height=30,
            selected_color="#3B82F6",
            selected_hover_color="#2563EB"
        )
        tf_display_map = {
            "5h": "5H",
            "24h": "24H",
            "7d": "7D",
            "30d": "30D",
            "month": "Month",
            "year": "Year",
            "session": "Session"
        }
        self.timeframe_seg.set(tf_display_map.get(self.selected_timeframe, "5H"))
        self.timeframe_seg.pack(side="left")

    def _find_matching_account_label(
        self,
        account_email: Optional[str],
        session_id: Optional[str]
    ) -> str:
        active_email = get_active_google_account()
        user_clean = active_email.split('@')[0] if active_email else ""

        # 1. Match specific session ID
        if session_id and session_id.upper() not in ("ALL", "ALL_CHATS", "ACTIVE_CHAT", "NONE", ""):
            for lbl, (acc, sid) in self.account_map.items():
                if sid and session_id.lower() in sid.lower():
                    return lbl
            return f"💬 {session_id[:20]}"

        # 2. Match All Accounts
        is_all = account_email in ("all", "all accounts", "★ all accounts", "*", "", None) or (account_email and "all" in account_email.lower())
        if is_all:
            for lbl in self.account_map:
                if "all" in lbl.lower():
                    return lbl
            return "★ All Accounts"

        # 3. Match Active User
        if account_email in ("active", "active user", "👤 active user") or (active_email and account_email and account_email.lower() == active_email.lower()):
            for lbl, (acc, sid) in self.account_map.items():
                if sid is None and (acc == "active" or (active_email and acc == active_email)):
                    return lbl
            return f"👤 {user_clean}" if user_clean else "👤 Active User"

        # 4. Match specific other account
        if account_email:
            acc_clean = account_email.replace("👤", "").strip().lower()
            for lbl, (acc, sid) in self.account_map.items():
                if sid is None and acc:
                    if acc.lower() == acc_clean or acc_clean in acc.lower() or ('@' in acc and acc.split('@')[0].lower() == acc_clean):
                        return lbl

        # Default fallback
        for lbl in self.account_map:
            if "all" in lbl.lower():
                return lbl
        return "★ All Accounts"

    def _refresh_account_menu_options(self):
        """Refreshes the account dropdown items dynamically with latest accounts."""
        if not hasattr(self, "account_menu"):
            return
        from core.account_manager import get_active_google_account, get_all_known_accounts_list
        active_email = get_active_google_account()
        known_accounts = get_all_known_accounts_list()
        valid_known = [a for a in known_accounts if a not in ("Default", "Local", "Default / Local Account")]
        num_accs = len(valid_known) if valid_known else (1 if active_email else 0)
        all_label = f"★ All Accounts ({num_accs})" if num_accs > 0 else "★ All Accounts"
        user_clean = active_email.split('@')[0] if active_email else "User"
        active_label = f"👤 {user_clean}" if active_email else "👤 Active User"

        account_values = [all_label]
        self.account_map = {
            all_label: ("all", None),
            "All": ("all", None),
            "★ All Accounts": ("all", None)
        }

        if active_email and active_email not in ("Default", "Local", "Default / Local Account"):
            account_values.append(active_label)
            self.account_map[active_label] = (active_email, None)

        for acc in known_accounts:
            if acc != active_email and acc not in ("Default", "Local", "Default / Local Account"):
                acc_clean = acc.split('@')[0] if '@' in acc else acc
                lbl = f"👤 {acc_clean}"
                if lbl not in account_values:
                    account_values.append(lbl)
                    self.account_map[lbl] = (acc, None)

        self.account_menu.configure(values=account_values)

    def sync_with_dashboard(
        self,
        account_email: Optional[str] = None,
        active_only: bool = False,
        session_id: Optional[str] = None,
        timeframe: Optional[str] = "5h"
    ):
        """Synchronizes the analytics window state dynamically with the main dashboard."""
        if account_email is not None:
            self.target_account = account_email
        self.target_active_only = active_only
        self.target_session_id = session_id

        if timeframe:
            self.selected_timeframe = timeframe.lower()

        self._refresh_account_menu_options()
        matched_account_label = self._find_matching_account_label(
            self.target_account,
            self.target_session_id
        )
        if hasattr(self, "account_menu") and matched_account_label:
            self.account_menu.set(matched_account_label)

        if hasattr(self, "session_scope_seg"):
            self.session_scope_seg.set("Active Session" if self.target_active_only else "All Sessions")

        tf_display_map = {
            "5h": "5H",
            "24h": "24H",
            "7d": "7D",
            "30d": "30D",
            "month": "Month",
            "year": "Year",
            "session": "Session"
        }
        if hasattr(self, "timeframe_seg"):
            self.timeframe_seg.set(tf_display_map.get(self.selected_timeframe, "5H"))

        self.table_page = 1
        self._load_data()
        self._safe_after(20, self._bring_to_front)

    def _on_account_changed(self, value: str):
        if value in self.account_map:
            self.target_account, self.target_session_id = self.account_map[value]
        elif value == "All" or "All" in value:
            self.target_account = "all"
            self.target_session_id = None
        else:
            from core.account_manager import get_active_google_account, get_all_known_accounts_list
            active_email = get_active_google_account()
            known_accounts = get_all_known_accounts_list()
            cleaned = value.replace("👤", "").strip()
            matched = next((a for a in known_accounts if a.split('@')[0].lower() == cleaned.lower() or a.lower() == cleaned.lower()), cleaned)
            self.target_account = matched
            self.target_session_id = None
        self.table_page = 1
        self._load_data()

    def _on_scope_changed(self, value: str):
        """Legacy compatibility handler."""
        self._on_account_changed(value)

    def _on_session_scope_changed(self, value: str):
        pass

    def _build_stat_cards(self, parent):
        cards_row = ctk.CTkFrame(parent, fg_color="transparent")
        cards_row.pack(fill="x", padx=16, pady=(0, 14))
        cards_row.columnconfigure((0, 1, 2, 3), weight=1, uniform="analytics_col")

        self.card_total = StatCard(cards_row, title="Period Total", icon="★", accent_color="#F59E0B")
        self.card_total.grid(row=0, column=0, padx=(0, 6), sticky="nsew")

        self.card_prompt = StatCard(cards_row, title="Input Tokens", icon="📥", accent_color="#3B82F6")
        self.card_prompt.grid(row=0, column=1, padx=6, sticky="nsew")

        self.card_thinking = StatCard(cards_row, title="Reasoning Tokens", icon="🧠", accent_color="#8B5CF6")
        self.card_thinking.grid(row=0, column=2, padx=6, sticky="nsew")

        self.card_candidates = StatCard(cards_row, title="Output Tokens", icon="📤", accent_color="#10B981")
        self.card_candidates.grid(row=0, column=3, padx=(6, 0), sticky="nsew")

    def _build_data_table(self, parent):
        table_frame = ctk.CTkFrame(
            parent,
            corner_radius=12,
            fg_color=("white", "#1e222d"),
            border_width=1,
            border_color=("#e2e8f0", "#2a3040")
        )
        table_frame.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        # Table Header
        tbl_hdr = ctk.CTkFrame(table_frame, fg_color="transparent")
        tbl_hdr.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            tbl_hdr,
            text="📋 Interval Breakdown Table",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#0f172a", "#f8fafc")
        ).pack(side="left")

        # Table Column Names
        cols_row = ctk.CTkFrame(table_frame, fg_color=("#f8fafc", "#161b26"), height=28, corner_radius=6)
        cols_row.pack(fill="x", padx=14, pady=(4, 6))

        headers = [
            ("Time Interval", 0.30, "w"),
            ("Prompt", 0.16, "e"),
            ("Thinking", 0.16, "e"),
            ("Output", 0.16, "e"),
            ("Total Tokens", 0.22, "e"),
        ]

        for title, _, anchor in headers:
            lbl = ctk.CTkLabel(
                cols_row,
                text=title,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=("#475569", "#94a3b8"),
                anchor=anchor
            )
            lbl.pack(side="left", fill="x", expand=True, padx=6)

        # Scrollable rows list
        self.table_rows_frame = ctk.CTkFrame(table_frame, fg_color="transparent")
        self.table_rows_frame.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        # Compact Pagination Control Bar for Interval Table
        self.table_pagination_frame = ctk.CTkFrame(table_frame, fg_color="transparent")
        self.table_pagination_frame.pack(fill="x", padx=14, pady=(0, 10))

        self.btn_table_first = ctk.CTkButton(
            self.table_pagination_frame,
            text="⏮ First",
            width=60,
            height=26,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self._go_table_first_page
        )
        self.btn_table_first.pack(side="left", padx=(0, 4))

        self.btn_table_prev = ctk.CTkButton(
            self.table_pagination_frame,
            text="◀ Prev",
            width=60,
            height=26,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self._go_table_prev_page
        )
        self.btn_table_prev.pack(side="left", padx=(0, 6))

        self.table_page_info_lbl = ctk.CTkLabel(
            self.table_pagination_frame,
            text="Page 1 of 1 (0 intervals)",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#475569", "#94a3b8")
        )
        self.table_page_info_lbl.pack(side="left", expand=True)

        self.btn_table_next = ctk.CTkButton(
            self.table_pagination_frame,
            text="Next ▶",
            width=60,
            height=26,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self._go_table_next_page
        )
        self.btn_table_next.pack(side="right", padx=(4, 0))

        self.btn_table_last = ctk.CTkButton(
            self.table_pagination_frame,
            text="Last ⏭",
            width=60,
            height=26,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self._go_table_last_page
        )
        self.btn_table_last.pack(side="right", padx=(6, 0))

    def _go_table_first_page(self):
        if self.table_page > 1:
            self.table_page = 1
            self._render_table_rows()

    def _go_table_prev_page(self):
        if self.table_page > 1:
            self.table_page -= 1
            self._render_table_rows()

    def _go_table_next_page(self):
        if self.table_page < self.table_total_pages:
            self.table_page += 1
            self._render_table_rows()

    def _go_table_last_page(self):
        if self.table_page < self.table_total_pages:
            self.table_page = self.table_total_pages
            self._render_table_rows()

    def _update_table_pagination_bar(self, paginated: Dict[str, Any]):
        self.table_page = paginated["page"]
        self.table_total_pages = paginated["total_pages"]
        total_cnt = paginated["total_count"]

        if total_cnt == 0:
            self.table_page_info_lbl.configure(text="Page 1 of 1 (0 intervals)")
        else:
            start_num = paginated["start_idx"]
            end_num = paginated["end_idx"]
            self.table_page_info_lbl.configure(
                text=f"Page {self.table_page} of {self.table_total_pages} (Showing {start_num}-{end_num} of {total_cnt} intervals)"
            )

        has_prev = paginated["has_prev"]
        has_next = paginated["has_next"]

        self.btn_table_first.configure(
            state="normal" if has_prev else "disabled",
            fg_color=("#e2e8f0", "#283042") if has_prev else ("#f1f5f9", "#1a202c"),
            text_color=("#0f172a", "#f8fafc") if has_prev else ("#94a3b8", "#64748b")
        )
        self.btn_table_prev.configure(
            state="normal" if has_prev else "disabled",
            fg_color=("#e2e8f0", "#283042") if has_prev else ("#f1f5f9", "#1a202c"),
            text_color=("#0f172a", "#f8fafc") if has_prev else ("#94a3b8", "#64748b")
        )
        self.btn_table_next.configure(
            state="normal" if has_next else "disabled",
            fg_color=("#e2e8f0", "#283042") if has_next else ("#f1f5f9", "#1a202c"),
            text_color=("#0f172a", "#f8fafc") if has_next else ("#94a3b8", "#64748b")
        )
        self.btn_table_last.configure(
            state="normal" if has_next else "disabled",
            fg_color=("#e2e8f0", "#283042") if has_next else ("#f1f5f9", "#1a202c"),
            text_color=("#0f172a", "#f8fafc") if has_next else ("#94a3b8", "#64748b")
        )

    def _build_footer(self, parent):
        ftr = ctk.CTkFrame(parent, fg_color="transparent")
        ftr.pack(fill="x", padx=16, pady=(0, 16))

        self.export_csv_btn = ctk.CTkButton(
            ftr,
            text="💾 Export CSV",
            width=120,
            height=34,
            corner_radius=8,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._export_csv
        )
        self.export_csv_btn.pack(side="left", padx=(0, 8))

        self.export_json_btn = ctk.CTkButton(
            ftr,
            text="💾 Export JSON",
            width=120,
            height=34,
            corner_radius=8,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._export_json
        )
        self.export_json_btn.pack(side="left")

        self.close_btn = ctk.CTkButton(
            ftr,
            text="Close",
            width=90,
            height=34,
            corner_radius=8,
            fg_color="#3B82F6",
            hover_color="#2563EB",
            text_color="#ffffff",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.destroy
        )
        self.close_btn.pack(side="right")

    def _on_timeframe_changed(self, value: str):
        val_map = {
            "5H": "5h",
            "24H": "24h",
            "7D": "7d",
            "30D": "30d",
            "Month": "month",
            "Year": "year",
            "Session": "session"
        }
        self.selected_timeframe = val_map.get(value, "5h")
        self.table_page = 1
        self._load_data()

    def _load_data(self):
        active_sid = None
        if hasattr(self.master, "watcher") and getattr(self.master.watcher, "latest_sessions", None):
            active_sid = self.master.watcher.latest_sessions[0].get("session_id")
        elif ledger.sessions:
            active_sid = max(ledger.sessions.values(), key=lambda s: s.get("mtime", 0.0)).get("session_id")
        else:
            sessions = get_all_session_files()
            active_sid = sessions[0].get("session_id") if sessions else None

        active_report = ledger.get_filtered_report(
            account_email=self.target_account,
            active_only=True,
            session_id=self.target_session_id,
            timeframe=self.selected_timeframe,
            active_session_id=active_sid
        )
        all_report = ledger.get_filtered_report(
            account_email=self.target_account,
            active_only=False,
            session_id=self.target_session_id,
            timeframe=self.selected_timeframe,
            active_session_id=active_sid
        )

        self.raw_records = all_report.get("records", [])
        self.current_buckets = all_report.get("buckets", [])
        self.current_summary = all_report.get("summary", {})

        # Update Chart Dual Series
        active_records = active_report.get("records", [])
        all_records = all_report.get("records", [])
        if hasattr(self.chart, "set_dual_records"):
            self.chart.set_dual_records(active_records, all_records, timeframe=self.selected_timeframe)
        else:
            self.chart.set_records(all_records, timeframe=self.selected_timeframe)

        # Update Stat Cards Dual Values
        active_p = active_report.get("prompt", active_report.get("prompt_total", 0))
        active_th = active_report.get("thinking", active_report.get("thinking_total", 0))
        active_c = active_report.get("candidates", active_report.get("candidates_total", 0))
        active_tot = active_report.get("total", active_report.get("tokens_total", 0))

        all_p = all_report.get("prompt", all_report.get("prompt_total", 0))
        all_th = all_report.get("thinking", all_report.get("thinking_total", 0))
        all_c = all_report.get("candidates", all_report.get("candidates_total", 0))
        all_tot = all_report.get("total", all_report.get("tokens_total", 0))

        if hasattr(self, "card_prompt") and hasattr(self.card_prompt, "update_values"):
            self.card_prompt.update_values(active_p, all_p)
            self.card_thinking.update_values(active_th, all_th)
            self.card_candidates.update_values(active_c, all_c)
            self.card_total.update_values(active_tot, all_tot, custom_badge=f"{len(self.current_buckets)} intervals")
        elif hasattr(self, "card_prompt"):
            self.card_prompt.update_value(all_p)
            self.card_thinking.update_value(all_th)
            self.card_candidates.update_value(all_c)
            self.card_total.update_value(all_tot)

        # Render Table Rows
        self._render_table_rows()

    def _render_table_rows(self):
        for child in self.table_rows_frame.winfo_children():
            child.destroy()

        # Filter buckets that have usage (or all if none non-zero)
        non_zero = [b for b in reversed(self.current_buckets) if b.get("total", 0) > 0]
        display_buckets = non_zero if non_zero else list(reversed(self.current_buckets))

        if not display_buckets:
            lbl = ctk.CTkLabel(
                self.table_rows_frame,
                text="No data intervals found for this scope.",
                font=ctk.CTkFont(size=12),
                text_color=("#64748b", "#64748b")
            )
            lbl.pack(pady=12)
            self._update_table_pagination_bar({
                "page": 1, "total_pages": 1, "total_count": 0, "has_prev": False, "has_next": False, "start_idx": 0, "end_idx": 0
            })
            return

        paginated = paginate_items(display_buckets, page=self.table_page, page_size=self.table_page_size)
        self.table_page = paginated["page"]
        self.table_total_pages = paginated["total_pages"]
        sliced_buckets = paginated["items"]

        self._update_table_pagination_bar(paginated)

        # Render sorted in reverse chronological order for table readability
        for b in sliced_buckets:
            tot = b.get("total", 0)

            row = ctk.CTkFrame(
                self.table_rows_frame,
                corner_radius=6,
                fg_color=("#f8fafc", "#161b26"),
                height=30,
                border_width=1,
                border_color=("#e2e8f0", "#232936")
            )
            row.pack(fill="x", pady=2)

            lbl_text = b.get("full_label") or b.get("key", "")
            p_text = f"{b.get('prompt', 0):,}"
            th_text = f"{b.get('thinking', 0):,}"
            c_text = f"{b.get('candidates', 0):,}"
            tot_text = f"{tot:,}"

            # Interval
            ctk.CTkLabel(
                row,
                text=f"📅 {lbl_text}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=("#0f172a", "#f8fafc"),
                anchor="w"
            ).pack(side="left", fill="x", expand=True, padx=8)

            # Prompt
            ctk.CTkLabel(
                row,
                text=p_text,
                font=ctk.CTkFont(size=11),
                text_color="#3B82F6",
                anchor="e"
            ).pack(side="left", fill="x", expand=True, padx=6)

            # Thinking
            ctk.CTkLabel(
                row,
                text=th_text,
                font=ctk.CTkFont(size=11),
                text_color="#8B5CF6",
                anchor="e"
            ).pack(side="left", fill="x", expand=True, padx=6)

            # Output
            ctk.CTkLabel(
                row,
                text=c_text,
                font=ctk.CTkFont(size=11),
                text_color="#10B981",
                anchor="e"
            ).pack(side="left", fill="x", expand=True, padx=6)

            # Total
            ctk.CTkLabel(
                row,
                text=tot_text,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=("#0f172a", "#f8fafc"),
                anchor="e"
            ).pack(side="left", fill="x", expand=True, padx=8)

    def _export_csv(self):
        if not self.current_buckets:
            messagebox.showwarning("No Data", "No usage data to export.")
            return
        save_path = filedialog.asksaveasfilename(
            title="Export Usage Data as CSV",
            defaultextension=".csv",
            initialfile=f"gemini_usage_{self.selected_timeframe}_{datetime.now().strftime('%Y%m%d')}.csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if save_path:
            try:
                export_analytics_csv(self.current_buckets, save_path)
                messagebox.showinfo("Export Successful", f"Usage analytics exported to:\n{save_path}")
            except Exception as e:
                messagebox.showerror("Export Failed", f"Could not export CSV: {e}")

    def _export_json(self):
        if not self.current_buckets:
            messagebox.showwarning("No Data", "No usage data to export.")
            return
        save_path = filedialog.asksaveasfilename(
            title="Export Usage Data as JSON",
            defaultextension=".json",
            initialfile=f"gemini_usage_{self.selected_timeframe}_{datetime.now().strftime('%Y%m%d')}.json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
        )
        if save_path:
            try:
                export_analytics_json(self.current_buckets, self.current_summary, save_path)
                messagebox.showinfo("Export Successful", f"Usage analytics exported to:\n{save_path}")
            except Exception as e:
                messagebox.showerror("Export Failed", f"Could not export JSON: {e}")

    def destroy(self):
        """Cleanly destroys the analytics dialog without affecting global app timers."""
        if hasattr(self.master, "analytics_dialog_window") and self.master.analytics_dialog_window == self:
            self.master.analytics_dialog_window = None
        super().destroy()
        if hasattr(self.master, "_update_watcher_activity"):
            self.master._update_watcher_activity()

