import customtkinter as ctk
from datetime import datetime, date
from typing import List, Dict, Callable, Optional, Any


def format_relative_timestamp(dt: Optional[datetime], raw_str: str) -> str:
    """Formats a datetime into a friendly relative label in local OS time (e.g. 'Today at 11:20 AM')."""
    if not dt and raw_str:
        try:
            from core.engine import parse_iso_time
            dt = parse_iso_time(raw_str)
            if not dt:
                dt = datetime.strptime(raw_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    if not dt:
        return raw_str
    try:
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        today = date.today()
        d = dt.date()
        time_part = dt.strftime("%I:%M %p").lstrip("0")
        if d == today:
            return f"Today at {time_part}"
        elif (today - d).days == 1:
            return f"Yesterday at {time_part}"
        elif (today - d).days < 7:
            return f"{dt.strftime('%A')} at {time_part}"
        else:
            return dt.strftime("%Y-%m-%d %I:%M %p")
    except Exception:
        return raw_str


from core.cleaner import paginate_items


class SessionTable(ctk.CTkFrame):
    """An interactive session list with search filtering, pagination (max 10/page), selection, and mode toggling in Light/Dark themes."""

    def __init__(
        self,
        master,
        on_select_session: Callable[[Optional[str], bool], None],
        on_open_cleaner: Optional[Callable[[], None]] = None,
        on_view_graph: Optional[Callable[[str], None]] = None,
        on_reassign_account: Optional[Callable[[str, str], None]] = None,
        **kwargs
    ):
        super().__init__(
            master,
            corner_radius=12,
            fg_color=("white", "#1e222d"),
            border_width=1,
            border_color=("#e2e8f0", "#2a3040"),
            **kwargs
        )
        self.on_select_session = on_select_session
        self.on_open_cleaner = on_open_cleaner
        self.on_view_graph = on_view_graph
        self.on_reassign_account = on_reassign_account
        self.sessions: List[Dict] = []
        self.selected_session_id: Optional[str] = None  # None = User Account Total
        self.is_all_mode: bool = False

        # Pagination State (Strict max 10 sessions per page)
        self.current_page: int = 1
        self.page_size: int = 10
        self.total_pages: int = 1
        self.total_filtered_count: int = 0
        self.filtered_sessions: List[Dict] = []

        # Top Control Bar (Search & Mode Buttons)
        self.controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.controls_frame.pack(fill="x", padx=12, pady=(10, 6))

        # Search Box
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *args: self._on_search_changed())
        self.search_entry = ctk.CTkEntry(
            self.controls_frame,
            placeholder_text="🔍 Search session ID or topic...",
            textvariable=self.search_var,
            height=32,
            corner_radius=8,
            border_width=1,
            fg_color=("#f8fafc", "#161b26"),
            border_color=("#cbd5e1", "#2d3748"),
            text_color=("#0f172a", "#f8fafc")
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Mode Buttons Frame
        self.btn_frame = ctk.CTkFrame(self.controls_frame, fg_color="transparent")
        self.btn_frame.pack(side="right")

        self.btn_user = ctk.CTkButton(
            self.btn_frame,
            text="👤 Active User",
            width=95,
            height=32,
            corner_radius=8,
            fg_color="#3B82F6",
            hover_color="#2563EB",
            text_color="#ffffff",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._select_user_mode
        )
        self.btn_user.pack(side="left", padx=(0, 4))

        self.btn_chat = ctk.CTkButton(
            self.btn_frame,
            text="⚡ Active Session",
            width=105,
            height=32,
            corner_radius=8,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#374151"),
            text_color=("#0f172a", "#e2e8f0"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._select_chat_mode
        )
        self.btn_chat.pack(side="left", padx=(0, 4))

        self.btn_all = ctk.CTkButton(
            self.btn_frame,
            text="★ All",
            width=60,
            height=32,
            corner_radius=8,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#374151"),
            text_color=("#0f172a", "#e2e8f0"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._select_all_mode
        )
        self.btn_all.pack(side="left", padx=(0, 4))

        if self.on_open_cleaner:
            self.btn_clean = ctk.CTkButton(
                self.btn_frame,
                text="🧹 Clean",
                width=70,
                height=32,
                corner_radius=8,
                fg_color=("#fee2e2", "#2e1818"),
                hover_color=("#fecaca", "#dc2626"),
                text_color=("#b91c1c", "#f87171"),
                font=ctk.CTkFont(size=11, weight="bold"),
                command=self.on_open_cleaner
            )
            self.btn_clean.pack(side="left")

        # Scrollable List of Sessions (Max 10 per page)
        self.scroll_frame = ctk.CTkScrollableFrame(
            self,
            corner_radius=8,
            fg_color=("#f8fafc", "#161b26"),
            label_text="CONVERSATION LOGS (SELECT FOR CHAT DRILL-DOWN)",
            label_font=ctk.CTkFont(size=11, weight="bold"),
            label_text_color=("#475569", "#64748b")
        )
        self.scroll_frame.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        # Bottom Pagination Control Bar
        self.pagination_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.pagination_frame.pack(fill="x", padx=12, pady=(0, 10))

        self.btn_first = ctk.CTkButton(
            self.pagination_frame,
            text="⏮ First",
            width=65,
            height=28,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self._go_first_page
        )
        self.btn_first.pack(side="left", padx=(0, 4))

        self.btn_prev = ctk.CTkButton(
            self.pagination_frame,
            text="◀ Prev",
            width=65,
            height=28,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self._go_prev_page
        )
        self.btn_prev.pack(side="left", padx=(0, 6))

        self.page_info_lbl = ctk.CTkLabel(
            self.pagination_frame,
            text="Page 1 of 1 (0 sessions)",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#475569", "#94a3b8")
        )
        self.page_info_lbl.pack(side="left", expand=True)

        self.btn_next = ctk.CTkButton(
            self.pagination_frame,
            text="Next ▶",
            width=65,
            height=28,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self._go_next_page
        )
        self.btn_next.pack(side="right", padx=(4, 0))

        self.btn_last = ctk.CTkButton(
            self.pagination_frame,
            text="Last ⏭",
            width=65,
            height=28,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self._go_last_page
        )
        self.btn_last.pack(side="right", padx=(6, 0))

        # Keyboard Navigation Bindings
        self.bind("<Left>", lambda e: self._go_prev_page())
        self.bind("<Right>", lambda e: self._go_next_page())
        self.bind("<Prior>", lambda e: self._go_prev_page())  # Page Up
        self.bind("<Next>", lambda e: self._go_next_page())   # Page Down

        self.row_frames: List[tuple] = []
        self._last_rendered_data_fp: Optional[tuple] = None
        self.active_only: bool = False

    def set_sessions(self, sessions: List[Dict]):
        self.sessions = sessions
        self._filter_sessions(reset_page=False)

    def set_selection_mode(self, is_all: bool, session_id: Optional[str] = None, active_only: bool = False):
        """Programmatically updates the selection mode and button highlights (e.g. when dropdown or session scope changes)."""
        target_sid = None if is_all else session_id
        if self.is_all_mode == is_all and self.selected_session_id == target_sid and getattr(self, "active_only", False) == active_only:
            return
        self.is_all_mode = is_all
        self.selected_session_id = target_sid
        self.active_only = active_only or (session_id == "ACTIVE_CHAT")
        self._update_button_styles()
        self._filter_sessions(reset_page=False)

    def _on_search_changed(self):
        """Reset page to 1 when search text changes."""
        self.current_page = 1
        self._filter_sessions(reset_page=False)

    def _select_user_mode(self):
        self.is_all_mode = False
        self.active_only = False
        self.selected_session_id = None
        self.current_page = 1
        self._update_button_styles()
        self.on_select_session(None, False)

    def _select_chat_mode(self):
        self.is_all_mode = False
        self.active_only = True
        self.selected_session_id = "ACTIVE_CHAT"
        self.current_page = 1
        self._update_button_styles()
        self.on_select_session("ACTIVE_CHAT", False)

    def _select_all_mode(self):
        self.is_all_mode = True
        self.active_only = False
        self.selected_session_id = None
        self.current_page = 1
        self._update_button_styles()
        self.on_select_session(None, True)

    def _select_specific_session(self, session_id: str):
        self.is_all_mode = False
        self.selected_session_id = session_id
        self._update_button_styles()
        self.on_select_session(session_id, False)

    def _go_first_page(self):
        if self.current_page > 1:
            self.current_page = 1
            self._filter_sessions(reset_page=False)

    def _go_prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self._filter_sessions(reset_page=False)

    def _go_next_page(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self._filter_sessions(reset_page=False)

    def _go_last_page(self):
        if self.current_page < self.total_pages:
            self.current_page = self.total_pages
            self._filter_sessions(reset_page=False)

    def _update_button_styles(self):
        if getattr(self, "active_only", False) or self.selected_session_id == "ACTIVE_CHAT":
            self.btn_chat.configure(fg_color="#3B82F6", text_color="#ffffff")
            self.btn_user.configure(fg_color=("#e2e8f0", "#283042"), text_color=("#0f172a", "#e2e8f0"))
            self.btn_all.configure(fg_color=("#e2e8f0", "#283042"), text_color=("#0f172a", "#e2e8f0"))
        elif self.is_all_mode:
            self.btn_all.configure(fg_color="#8B5CF6", text_color="#ffffff")
            self.btn_user.configure(fg_color=("#e2e8f0", "#283042"), text_color=("#0f172a", "#e2e8f0"))
            self.btn_chat.configure(fg_color=("#e2e8f0", "#283042"), text_color=("#0f172a", "#e2e8f0"))
        elif self.selected_session_id is None:
            self.btn_user.configure(fg_color="#3B82F6", text_color="#ffffff")
            self.btn_chat.configure(fg_color=("#e2e8f0", "#283042"), text_color=("#0f172a", "#e2e8f0"))
            self.btn_all.configure(fg_color=("#e2e8f0", "#283042"), text_color=("#0f172a", "#e2e8f0"))
        else:
            self.btn_user.configure(fg_color=("#e2e8f0", "#283042"), text_color=("#0f172a", "#e2e8f0"))
            self.btn_chat.configure(fg_color=("#e2e8f0", "#283042"), text_color=("#0f172a", "#e2e8f0"))
            self.btn_all.configure(fg_color=("#e2e8f0", "#283042"), text_color=("#0f172a", "#e2e8f0"))

    def _update_row_selection_styles(self):
        """Updates row background and border colors in-place without destroying any widgets."""
        for idx, item in enumerate(self.row_frames):
            try:
                sid = item[0]
                row_widget = item[1]
                # Is active session on the first row of page 1
                is_active_session = (self.current_page == 1 and idx == 0)
                is_selected = (
                    (self.selected_session_id == "ACTIVE_CHAT" and is_active_session and not self.is_all_mode) or
                    (self.selected_session_id == sid and not self.is_all_mode)
                )
                row_bg = ("#dbeafe", "#1e3a5f") if is_selected else ("white", "#1e222d")
                row_border = ("#3b82f6", "#3b82f6") if is_selected else ("#e2e8f0", "#283042")
                row_widget.configure(fg_color=row_bg, border_color=row_border)
            except Exception:
                pass

    def _update_pagination_bar(self, paginated: Dict[str, Any]):
        """Updates pagination button states and indicator label."""
        self.current_page = paginated["page"]
        self.total_pages = paginated["total_pages"]
        self.total_filtered_count = paginated["total_count"]

        if self.total_filtered_count == 0:
            self.page_info_lbl.configure(text="Page 1 of 1 (0 sessions)")
        else:
            start_num = paginated["start_idx"]
            end_num = paginated["end_idx"]
            self.page_info_lbl.configure(
                text=f"Page {self.current_page} of {self.total_pages} (Showing {start_num}-{end_num} of {self.total_filtered_count} sessions)"
            )

        # Configure button interactive states
        has_prev = paginated["has_prev"]
        has_next = paginated["has_next"]

        self.btn_first.configure(
            state="normal" if has_prev else "disabled",
            fg_color=("#e2e8f0", "#283042") if has_prev else ("#f1f5f9", "#1a202c"),
            text_color=("#0f172a", "#f8fafc") if has_prev else ("#94a3b8", "#64748b")
        )
        self.btn_prev.configure(
            state="normal" if has_prev else "disabled",
            fg_color=("#e2e8f0", "#283042") if has_prev else ("#f1f5f9", "#1a202c"),
            text_color=("#0f172a", "#f8fafc") if has_prev else ("#94a3b8", "#64748b")
        )
        self.btn_next.configure(
            state="normal" if has_next else "disabled",
            fg_color=("#e2e8f0", "#283042") if has_next else ("#f1f5f9", "#1a202c"),
            text_color=("#0f172a", "#f8fafc") if has_next else ("#94a3b8", "#64748b")
        )
        self.btn_last.configure(
            state="normal" if has_next else "disabled",
            fg_color=("#e2e8f0", "#283042") if has_next else ("#f1f5f9", "#1a202c"),
            text_color=("#0f172a", "#f8fafc") if has_next else ("#94a3b8", "#64748b")
        )

    def _filter_sessions(self, reset_page: bool = False):
        if reset_page:
            self.current_page = 1

        query = self.search_var.get().strip().lower()
        filtered = [
            s for s in self.sessions
            if not query or
               query in s["session_id"].lower() or
               query in s.get("last_active_str", "").lower() or
               query in s.get("first_prompt", "").lower() or
               query in s.get("title", "").lower()
        ]
        self.filtered_sessions = filtered

        # Slice 10 items for current page
        paginated = paginate_items(filtered, page=self.current_page, page_size=self.page_size)
        self.current_page = paginated["page"]
        self.total_pages = paginated["total_pages"]
        sliced_items = paginated["items"]

        # Update footer pagination bar
        self._update_pagination_bar(paginated)

        data_fingerprint = (
            self.current_page,
            query,
            tuple((s.get("session_id"), s.get("mtime"), s.get("size"), s.get("first_prompt", ""), s.get("account", "")) for s in sliced_items)
        )

        if getattr(self, "_last_rendered_data_fp", None) == data_fingerprint and self.row_frames:
            # Data on this page has not changed; update row highlights in-place with zero widget recreation
            self._update_row_selection_styles()
            return

        self._last_rendered_data_fp = data_fingerprint

        # Check if existing row widgets can be updated in-place without destroying and recreating widgets
        current_sids = [s["session_id"] for s in sliced_items]
        rendered_sids = [item[0] for item in self.row_frames] if self.row_frames else []

        if current_sids and current_sids == rendered_sids and len(self.row_frames) == len(sliced_items):
            for idx, s in enumerate(sliced_items):
                try:
                    item = self.row_frames[idx]
                    sid, row = item[0], item[1]
                    id_lbl = item[2] if len(item) > 2 else None
                    prompt_lbl = item[3] if len(item) > 3 else None
                    time_lbl = item[4] if len(item) > 4 else None
                    tok_badge = item[5] if len(item) > 5 else None
                    size_badge = item[6] if len(item) > 6 else None
                    dot_lbl = item[7] if len(item) > 7 else None

                    is_active_session = (self.current_page == 1 and idx == 0)
                    is_selected = (
                        (self.selected_session_id == "ACTIVE_CHAT" and is_active_session and not self.is_all_mode) or
                        (self.selected_session_id == sid and not self.is_all_mode)
                    )
                    row_bg = ("#dbeafe", "#1e3a5f") if is_selected else ("white", "#1e222d")
                    row_border = ("#3b82f6", "#3b82f6") if is_selected else ("#e2e8f0", "#283042")
                    row.configure(fg_color=row_bg, border_color=row_border)

                    if dot_lbl:
                        dot_color = "#10B981" if is_active_session else "#94a3b8"
                        dot_lbl.configure(text_color=dot_color)

                    if id_lbl:
                        short_id = sid if len(sid) <= 32 else f"{sid[:16]}...{sid[-8:]}"
                        id_lbl.configure(text=f"{short_id}{' (Active)' if is_active_session else ''}")

                    first_prompt = s.get("first_prompt") or s.get("title")
                    if prompt_lbl and first_prompt and first_prompt != sid:
                        prompt_lbl.configure(text=f"💬 {first_prompt}")

                    if time_lbl:
                        rel_time = format_relative_timestamp(s.get("last_active"), s.get("last_active_str", ""))
                        time_lbl.configure(text=f"Last Active: {rel_time}")

                    if tok_badge:
                        from core.ledger import ledger
                        tok_count = s.get("tokens") or ledger.sessions.get(sid, {}).get("total", 0)
                        if tok_count >= 1000000:
                            tok_str = f"{tok_count/1000000:.2f}M tok"
                        elif tok_count >= 1000:
                            tok_str = f"{tok_count/1000:.1f}K tok"
                        else:
                            tok_str = f"{tok_count:,} tok"
                        tok_badge.configure(text=tok_str)

                    if size_badge:
                        size_kb = s.get("size", 0) / 1024.0
                        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024.0:.1f} MB"
                        size_badge.configure(text=size_str)
                except Exception:
                    pass
            return

        # Clear existing rows cleanly
        for child in self.scroll_frame.winfo_children():
            child.destroy()
        self.row_frames.clear()

        if not sliced_items:
            empty_lbl = ctk.CTkLabel(
                self.scroll_frame,
                text="No matching sessions found.",
                font=ctk.CTkFont(size=12),
                text_color=("#64748b", "#64748b")
            )
            empty_lbl.pack(pady=20)
            return

        for idx, s in enumerate(sliced_items):
            is_active_session = (self.current_page == 1 and idx == 0)
            is_selected = (
                (self.selected_session_id == "ACTIVE_CHAT" and is_active_session and not self.is_all_mode) or
                (self.selected_session_id == s["session_id"] and not self.is_all_mode)
            )

            # Row Frame styling
            row_bg = ("#dbeafe", "#1e3a5f") if is_selected else ("white", "#1e222d")
            row_border = ("#3b82f6", "#3b82f6") if is_selected else ("#e2e8f0", "#283042")

            row = ctk.CTkFrame(
                self.scroll_frame,
                corner_radius=8,
                fg_color=row_bg,
                border_width=1,
                border_color=row_border,
                cursor="hand2"
            )
            row.pack(fill="x", pady=3, padx=2)

            session_id = s["session_id"]
            click_handler = (lambda sid=session_id: lambda e: self._select_specific_session(sid))(session_id)
            context_handler = (lambda sess=s: lambda e: self._show_context_menu(e, sess))(s)

            row.bind("<Button-1>", click_handler)
            row.bind("<Button-3>", context_handler)

            # Left side
            left_frame = ctk.CTkFrame(row, fg_color="transparent")
            left_frame.pack(side="left", fill="x", expand=True, padx=8, pady=5)
            left_frame.bind("<Button-1>", click_handler)
            left_frame.bind("<Button-3>", context_handler)

            title_row = ctk.CTkFrame(left_frame, fg_color="transparent")
            title_row.pack(fill="x")
            title_row.bind("<Button-1>", click_handler)
            title_row.bind("<Button-3>", context_handler)

            dot_color = "#10B981" if is_active_session else "#94a3b8"
            dot_label = ctk.CTkLabel(
                title_row,
                text="●",
                font=ctk.CTkFont(size=10),
                text_color=dot_color
            )
            dot_label.pack(side="left", padx=(0, 4))
            dot_label.bind("<Button-1>", click_handler)
            dot_label.bind("<Button-3>", context_handler)

            short_id = session_id if len(session_id) <= 32 else f"{session_id[:16]}...{session_id[-8:]}"
            id_lbl = ctk.CTkLabel(
                title_row,
                text=f"{short_id}{' (Active)' if is_active_session else ''}",
                font=ctk.CTkFont(size=12, weight="bold" if is_selected else "normal"),
                text_color=("#0f172a", "#f8fafc")
            )
            id_lbl.pack(side="left")
            id_lbl.bind("<Button-1>", click_handler)
            id_lbl.bind("<Button-3>", context_handler)

            # Prompt Snippet / Subtitle
            prompt_lbl = None
            first_prompt = s.get("first_prompt") or s.get("title")
            if first_prompt and first_prompt != session_id:
                prompt_lbl = ctk.CTkLabel(
                    left_frame,
                    text=f"💬 {first_prompt}",
                    font=ctk.CTkFont(size=11),
                    text_color=("#334155", "#94a3b8"),
                    anchor="w"
                )
                prompt_lbl.pack(anchor="w", padx=(14, 0), pady=(1, 1))
                prompt_lbl.bind("<Button-1>", click_handler)
                prompt_lbl.bind("<Button-3>", context_handler)

            rel_time = format_relative_timestamp(s.get("last_active"), s.get("last_active_str", ""))
            time_lbl = ctk.CTkLabel(
                left_frame,
                text=f"Last Active: {rel_time}",
                font=ctk.CTkFont(size=10),
                text_color=("#64748b", "#64748b")
            )
            time_lbl.pack(anchor="w", padx=(14, 0))
            time_lbl.bind("<Button-1>", click_handler)
            time_lbl.bind("<Button-3>", context_handler)

            # Right side
            right_frame = ctk.CTkFrame(row, fg_color="transparent")
            right_frame.pack(side="right", padx=10)
            right_frame.bind("<Button-1>", click_handler)
            right_frame.bind("<Button-3>", context_handler)

            # Token count badge
            from core.ledger import ledger
            tok_count = s.get("tokens") or ledger.sessions.get(session_id, {}).get("total", 0)
            if tok_count >= 1000000:
                tok_str = f"{tok_count/1000000:.2f}M tok"
            elif tok_count >= 1000:
                tok_str = f"{tok_count/1000:.1f}K tok"
            else:
                tok_str = f"{tok_count:,} tok"

            tok_badge = ctk.CTkLabel(
                right_frame,
                text=tok_str,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=("#1d4ed8", "#93c5fd"),
                corner_radius=4,
                fg_color=("#dbeafe", "#1e3a5f"),
                padx=7,
                pady=2
            )
            tok_badge.pack(side="left", padx=(0, 6))
            tok_badge.bind("<Button-1>", click_handler)
            tok_badge.bind("<Button-3>", context_handler)

            size_kb = s["size"] / 1024.0
            size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024.0:.1f} MB"

            size_badge = ctk.CTkLabel(
                right_frame,
                text=size_str,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=("#475569", "#94a3b8"),
                corner_radius=4,
                fg_color=("#e2e8f0", "#283042"),
                padx=6,
                pady=2
            )
            size_badge.pack(side="left")
            size_badge.bind("<Button-1>", click_handler)
            size_badge.bind("<Button-3>", context_handler)

            self.row_frames.append((s["session_id"], row, id_lbl, prompt_lbl, time_lbl, tok_badge, size_badge, dot_label))

    def _show_context_menu(self, event, session: Dict):
        """Displays a context menu for the clicked session with rapid-click debouncing."""
        import time
        now = time.time()
        if now - getattr(self, "_last_context_menu_time", 0.0) < 0.25:
            return
        self._last_context_menu_time = now

        import os
        import json
        import tkinter as tk
        from tkinter import filedialog

        sid = session["session_id"]
        folder = session.get("folder")

        if getattr(self, "_active_context_menu", None) is not None:
            try:
                self._active_context_menu.destroy()
            except Exception:
                pass
            self._active_context_menu = None

        is_dark = ctk.get_appearance_mode().lower() == "dark"
        menu = tk.Menu(
            self,
            tearoff=0,
            bg="#1e222d" if is_dark else "#ffffff",
            fg="#f8fafc" if is_dark else "#0f172a",
            activebackground="#3b82f6",
            activeforeground="#ffffff",
            bd=1
        )
        self._active_context_menu = menu

        def _copy_id():
            self.clipboard_clear()
            self.clipboard_append(sid)

        def _open_folder():
            if folder and os.path.exists(str(folder)):
                try:
                    if os.name == "nt":
                        os.startfile(str(folder))
                    else:
                        import subprocess
                        subprocess.Popen(["xdg-open", str(folder)])
                except Exception:
                    pass

        def _export_json():
            from core.engine import get_single_session_report
            report = get_single_session_report(session)
            save_path = filedialog.asksaveasfilename(
                title="Export Session Report",
                defaultextension=".json",
                initialfile=f"session_{sid[:12]}_report.json",
                filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
            )
            if save_path:
                try:
                    with open(save_path, "w", encoding="utf-8") as f:
                        json.dump(report, f, indent=2, default=str)
                except Exception:
                    pass

        def _view_graph():
            if self.on_view_graph:
                self.on_view_graph(sid)

        def _delete_session():
            from tkinter import messagebox
            from core.cleaner import delete_session_files
            confirm = messagebox.askyesno(
                "Delete Session",
                f"Are you sure you want to permanently delete session '{sid[:16]}...'?\nThis will remove transcripts from disk and free disk space.",
                icon="warning"
            )
            if confirm:
                ok, _, msg = delete_session_files(sid, folder_path=session.get("folder"), file_path=session.get("file"))
                if ok:
                    messagebox.showinfo("Session Deleted", msg)
                    if self.on_open_cleaner:
                        # Triggers watcher refresh
                        pass

        def _reassign_to_account(new_acc):
            self._reassign_session(sid, new_acc)

        menu.add_command(label="📊 View Usage Graph", command=_view_graph)
        menu.add_command(label="📋 Copy Session ID", command=_copy_id)
        menu.add_command(label="📁 Open Folder in Explorer", command=_open_folder)
        menu.add_command(label="💾 Export Session Report (JSON)", command=_export_json)

        try:
            from core.account_manager import get_all_known_accounts_list
            known_accs = get_all_known_accounts_list()
            if known_accs:
                menu.add_separator()
                reassign_menu = tk.Menu(
                    menu,
                    tearoff=0,
                    bg="#1e222d" if is_dark else "#ffffff",
                    fg="#f8fafc" if is_dark else "#0f172a",
                    activebackground="#3b82f6",
                    activeforeground="#ffffff",
                    bd=1
                )
                curr_acc = session.get("account", "").strip()
                for acc in known_accs:
                    acc_clean = acc.strip()
                    is_current = (acc_clean.lower() == curr_acc.lower())
                    mark = "✓ " if is_current else ""
                    reassign_menu.add_command(
                        label=f"{mark}👤 {acc_clean}",
                        command=lambda a=acc_clean: _reassign_to_account(a)
                    )
                menu.add_cascade(label="👤 Assign to Account", menu=reassign_menu)
        except Exception:
            pass

        menu.add_separator()
        menu.add_command(label="🗑️ Delete Session (Free Disk)", command=_delete_session)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _reassign_session(self, session_id: str, new_account: str):
        from core.ledger import ledger
        if ledger.reassign_session_account(session_id, new_account):
            if self.on_reassign_account:
                self.on_reassign_account(session_id, new_account)

    def destroy(self):
        if getattr(self, "_active_context_menu", None) is not None:
            try:
                self._active_context_menu.destroy()
            except Exception:
                pass
            self._active_context_menu = None
        super().destroy()

