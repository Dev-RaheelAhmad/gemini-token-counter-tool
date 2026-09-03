import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from typing import Optional, Callable, Dict, List, Any

from core.cleaner import (
    get_disk_usage_summary,
    delete_session_files,
    prune_sessions_by_age,
    prune_sessions_keep_latest,
    prune_empty_sessions,
    prune_all_previous,
    format_bytes,
    open_storage_folder,
    open_session_folder,
    sync_and_prune_orphaned_sessions,
    paginate_items,
)
from gui.window_utils import apply_windows_dark_titlebar, center_window_on_screen


class CleanerDialog(ctk.CTkToplevel):
    """
    Dedicated Session Cleaner & Storage Compactor dialog.
    Allows deleting past session transcripts from disk and ledger
    to free storage and maintain a compact history.
    """

    def __init__(self, master, on_cleanup_complete: Optional[Callable[[], None]] = None, **kwargs):
        super().__init__(master, **kwargs)
        self.withdraw()  # Withdraw during setup to prevent initial white frame flash
        self.title("🧹 Session Cleaner & Storage Compactor")
        center_window_on_screen(self, 700, 580)
        self.minsize(620, 500)
        self.on_cleanup_complete = on_cleanup_complete

        # Maintain parent-child window stacking relationship
        try:
            self.transient(master)
        except Exception:
            pass

        # Inherit topmost state if parent is pinned / topmost
        try:
            if getattr(master, "is_pinned", False) or (hasattr(master, "attributes") and master.attributes("-topmost")):
                self.attributes("-topmost", True)
        except Exception:
            pass

        # State
        self.session_data: List[Dict[str, Any]] = []
        self.selected_session_ids: set = set()  # Decoupled global selection set across all pages
        self.checkbox_vars: Dict[str, ctk.BooleanVar] = {}
        self.active_session_id: Optional[str] = None
        self.delete_disk_files_var = ctk.BooleanVar(value=False)

        # Pagination State (Strict max 10 sessions per page)
        self.current_page: int = 1
        self.page_size: int = 10
        self.total_pages: int = 1

        self._build_ui()
        self._refresh_session_list()

        # Key bindings and protocols
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda e: self.destroy())

        # Apply dark titlebar attributes BEFORE displaying on screen
        apply_windows_dark_titlebar(self)

        # Show fully rendered window smoothly
        self.deiconify()
        self.lift()
        self.focus_force()

    def _build_ui(self):
        self.main_container = ctk.CTkScrollableFrame(
            self,
            fg_color=("white", "#161b26"),
            border_width=1,
            border_color=("#e2e8f0", "#2a3040")
        )
        self.main_container.pack(fill="both", expand=True, padx=16, pady=16)

        # 1. Header & Storage Summary
        self.header_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.header_frame.pack(fill="x", pady=(0, 10))

        left_hdr = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        left_hdr.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            left_hdr,
            text="🧹 Clean Sessions & Compact Storage",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=("#0f172a", "#f8fafc")
        ).pack(anchor="w")

        self.storage_summary_lbl = ctk.CTkLabel(
            left_hdr,
            text="Calculating storage usage...",
            font=ctk.CTkFont(size=12),
            text_color=("#475569", "#94a3b8")
        )
        self.storage_summary_lbl.pack(anchor="w", pady=(2, 0))

        right_hdr = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        right_hdr.pack(side="right")

        ctk.CTkButton(
            right_hdr,
            text="📂 Open Storage Folder",
            height=30,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._open_storage_folder
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            right_hdr,
            text="🔄 Sync with Disk",
            height=30,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._sync_with_disk
        ).pack(side="left")

        # Scope & Explanation Card
        info_card = ctk.CTkFrame(
            self.main_container,
            corner_radius=8,
            fg_color=("#eff6ff", "#131e30"),
            border_width=1,
            border_color=("#bfdbfe", "#1d4ed8")
        )
        info_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            info_card,
            text="ℹ️ Storage & Deletion Scope Explained:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#1d4ed8", "#93c5fd")
        ).pack(anchor="w", padx=12, pady=(8, 2))

        ctk.CTkLabel(
            info_card,
            text=(
                "• What gets deleted: Selected past conversation folders and transcript files (.jsonl) located inside '.gemini/.../brain/<session_id>/' to free physical SSD disk space.\n"
                "• App ledger cleanup: Purges historical tracking records from our local database (account_usage.json) and cache.\n"
                "• Protected items: Your active conversation, workspace code, and global credentials are NEVER deleted."
            ),
            font=ctk.CTkFont(size=11),
            text_color=("#334155", "#cbd5e1"),
            justify="left"
        ).pack(anchor="w", padx=12, pady=(0, 8))

        # Disk deletion toggle option
        ctk.CTkCheckBox(
            info_card,
            text="Permanently delete physical transcript files from .gemini/brain to reclaim SSD space",
            variable=self.delete_disk_files_var,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#0f172a", "#f8fafc"),
            fg_color="#3B82F6"
        ).pack(anchor="w", padx=12, pady=(0, 8))

        # 2. Quick Action Presets Box
        presets_box = ctk.CTkFrame(
            self.main_container,
            corner_radius=10,
            fg_color=("#f8fafc", "#1e222d"),
            border_width=1,
            border_color=("#e2e8f0", "#2a3040")
        )
        presets_box.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(
            presets_box,
            text="⚡ QUICK CLEANUP PRESETS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#475569", "#94a3b8")
        ).pack(anchor="w", padx=12, pady=(10, 6))

        p_row1 = ctk.CTkFrame(presets_box, fg_color="transparent")
        p_row1.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkButton(
            p_row1,
            text="Older than 7 Days",
            height=30,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#dc2626"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda: self._run_quick_prune("7d")
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            p_row1,
            text="Older than 30 Days",
            height=30,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#dc2626"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda: self._run_quick_prune("30d")
        ).pack(side="left", fill="x", expand=True, padx=6)

        ctk.CTkButton(
            p_row1,
            text="Keep Latest 5 Only",
            height=30,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#dc2626"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda: self._run_quick_prune("keep5")
        ).pack(side="left", fill="x", expand=True, padx=(6, 0))

        p_row2 = ctk.CTkFrame(presets_box, fg_color="transparent")
        p_row2.pack(fill="x", padx=12, pady=(0, 10))

        ctk.CTkButton(
            p_row2,
            text="🧹 Remove 0-Token / Empty",
            height=30,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#dc2626"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda: self._run_quick_prune("empty")
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            p_row2,
            text="⚡ Delete All Previous (Keep Active Only)",
            height=30,
            corner_radius=6,
            fg_color="#ef4444",
            hover_color="#dc2626",
            text_color="#ffffff",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda: self._run_quick_prune("all_previous")
        ).pack(side="left", fill="x", expand=True, padx=(6, 0))

        # 3. Interactive Selection List
        list_box = ctk.CTkFrame(
            self.main_container,
            corner_radius=10,
            fg_color=("#f8fafc", "#1e222d"),
            border_width=1,
            border_color=("#e2e8f0", "#2a3040")
        )
        list_box.pack(fill="both", expand=True, pady=(0, 14))

        # Selection Toolbar
        sel_tb = ctk.CTkFrame(list_box, fg_color="transparent")
        sel_tb.pack(fill="x", padx=12, pady=(10, 6))

        ctk.CTkLabel(
            sel_tb,
            text="📁 SELECT SESSIONS TO DELETE",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#475569", "#94a3b8")
        ).pack(side="left")

        self.copied_feedback_lbl = ctk.CTkLabel(
            sel_tb,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#10B981"
        )
        self.copied_feedback_lbl.pack(side="left", padx=(12, 0))

        # Select All / Deselect All buttons
        ctk.CTkButton(
            sel_tb,
            text="Select All (Excl. Active)",
            width=140,
            height=26,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self._select_all
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            sel_tb,
            text="Deselect All",
            width=90,
            height=26,
            corner_radius=6,
            fg_color=("#e2e8f0", "#283042"),
            hover_color=("#cbd5e1", "#3B82F6"),
            text_color=("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self._deselect_all
        ).pack(side="right")

        # Scrollable Rows
        self.rows_container = ctk.CTkFrame(list_box, fg_color="transparent")
        self.rows_container.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        # Pagination Control Bar
        self.pagination_frame = ctk.CTkFrame(list_box, fg_color="transparent")
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

        # 4. Action Footer
        self.delete_btn = ctk.CTkButton(
            self.main_container,
            text="🗑️ Delete Selected Sessions (0 selected)",
            height=38,
            corner_radius=8,
            fg_color="#ef4444",
            hover_color="#dc2626",
            text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._delete_selected
        )
        self.delete_btn.pack(fill="x", pady=(0, 6))

    def _go_first_page(self):
        if self.current_page > 1:
            self.current_page = 1
            self._render_current_page()

    def _go_prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self._render_current_page()

    def _go_next_page(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self._render_current_page()

    def _go_last_page(self):
        if self.current_page < self.total_pages:
            self.current_page = self.total_pages
            self._render_current_page()

    def _update_pagination_bar(self, paginated: Dict[str, Any]):
        """Updates pagination button states and indicator label in cleaner dialog."""
        self.current_page = paginated["page"]
        self.total_pages = paginated["total_pages"]
        total_cnt = paginated["total_count"]

        if total_cnt == 0:
            self.page_info_lbl.configure(text="Page 1 of 1 (0 sessions)")
        else:
            start_num = paginated["start_idx"]
            end_num = paginated["end_idx"]
            self.page_info_lbl.configure(
                text=f"Page {self.current_page} of {self.total_pages} (Showing {start_num}-{end_num} of {total_cnt} sessions)"
            )

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

    def _refresh_session_list(self):
        summary = get_disk_usage_summary()
        self.session_data = summary.get("sessions", [])

        tot_sessions = summary.get("total_sessions", 0)
        tot_size = summary.get("total_size_str", "0 B")
        self.storage_summary_lbl.configure(text=f"Total: {tot_sessions} sessions occupying {tot_size} on disk")

        self.active_session_id = self.session_data[0]["session_id"] if self.session_data else None

        # Clean up selected session IDs that no longer exist
        existing_sids = {s["session_id"] for s in self.session_data}
        self.selected_session_ids = {sid for sid in self.selected_session_ids if sid in existing_sids}

        self._render_current_page()

    def _render_current_page(self):
        # Clear existing rows
        for child in self.rows_container.winfo_children():
            child.destroy()
        self.checkbox_vars.clear()

        if not self.session_data:
            lbl = ctk.CTkLabel(
                self.rows_container,
                text="No session transcripts found.",
                font=ctk.CTkFont(size=12),
                text_color=("#64748b", "#64748b")
            )
            lbl.pack(pady=20)
            self._update_pagination_bar({
                "page": 1, "total_pages": 1, "total_count": 0, "has_prev": False, "has_next": False, "start_idx": 0, "end_idx": 0
            })
            self._update_delete_button_label()
            return

        # Slice 10 items for current page
        paginated = paginate_items(self.session_data, page=self.current_page, page_size=self.page_size)
        self.current_page = paginated["page"]
        self.total_pages = paginated["total_pages"]
        sliced_items = paginated["items"]

        self._update_pagination_bar(paginated)

        for s in sliced_items:
            sid = s["session_id"]
            is_active = (sid == self.active_session_id)
            is_checked = (sid in self.selected_session_ids)

            row = ctk.CTkFrame(
                self.rows_container,
                corner_radius=6,
                fg_color=("white", "#161b26"),
                height=34,
                border_width=1,
                border_color=("#e2e8f0", "#232936")
            )
            row.pack(fill="x", pady=2)

            cb_var = ctk.BooleanVar(value=is_checked)
            self.checkbox_vars[sid] = cb_var

            # Checkbox bound to decoupled selection state
            cb = ctk.CTkCheckBox(
                row,
                text="",
                variable=cb_var,
                width=24,
                checkbox_width=18,
                checkbox_height=18,
                command=lambda target_sid=sid, var=cb_var: self._on_checkbox_toggled(target_sid, var.get())
            )
            cb.pack(side="left", padx=(8, 4), pady=4)

            # Click & context handlers
            def _make_click_handler(target_sid):
                return lambda e: self._copy_session_id(target_sid)

            def _make_context_handler(target_s):
                return lambda e: self._show_context_menu(e, target_s)

            row_click = _make_click_handler(sid)
            row_context = _make_context_handler(s)

            row.bind("<Button-1>", row_click)
            row.bind("<Button-3>", row_context)
            row.bind("<Button-2>", row_context)

            # Dot & Title
            title_text = s.get("first_prompt") or s.get("title") or sid
            if len(title_text) > 38:
                title_text = title_text[:36] + "..."

            active_tag = " [ACTIVE - PROTECTED]" if is_active else ""
            title_lbl = ctk.CTkLabel(
                row,
                text=f"{'● ' if is_active else ''}{title_text}{active_tag}",
                font=ctk.CTkFont(size=11, weight="bold" if is_active else "normal"),
                text_color=("#15803d", "#10B981") if is_active else ("#0f172a", "#f8fafc"),
                anchor="w"
            )
            title_lbl.pack(side="left", fill="x", expand=True, padx=4)
            title_lbl.bind("<Button-1>", row_click)
            title_lbl.bind("<Button-3>", row_context)
            title_lbl.bind("<Button-2>", row_context)

            # Open in Explorer button
            open_btn = ctk.CTkButton(
                row,
                text="📁",
                width=26,
                height=22,
                corner_radius=4,
                fg_color="transparent",
                hover_color=("#e2e8f0", "#283042"),
                text_color=("#475569", "#94a3b8"),
                font=ctk.CTkFont(size=11),
                command=lambda target_s=s: self._open_session_in_explorer(target_s)
            )
            open_btn.pack(side="right", padx=(2, 6))

            # Tokens Badge
            tok = s.get("tokens", 0)
            tok_str = f"{tok/1000:.1f}K tok" if tok >= 1000 else f"{tok} tok"
            tok_lbl = ctk.CTkLabel(
                row,
                text=tok_str,
                font=ctk.CTkFont(size=10),
                text_color=("#475569", "#94a3b8")
            )
            tok_lbl.pack(side="right", padx=6)
            tok_lbl.bind("<Button-1>", row_click)
            tok_lbl.bind("<Button-3>", row_context)
            tok_lbl.bind("<Button-2>", row_context)

            # Size Badge
            size_badge = ctk.CTkLabel(
                row,
                text=s.get("size_str", "0 B"),
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=("#475569", "#cbd5e1"),
                corner_radius=4,
                fg_color=("#e2e8f0", "#283042"),
                padx=6,
                pady=1
            )
            size_badge.pack(side="right", padx=4)
            size_badge.bind("<Button-1>", row_click)
            size_badge.bind("<Button-3>", row_context)
            size_badge.bind("<Button-2>", row_context)

        self._update_delete_button_label()

    def _on_checkbox_toggled(self, sid: str, is_checked: bool):
        """Updates the global selection set when an individual checkbox is toggled."""
        if is_checked:
            self.selected_session_ids.add(sid)
        else:
            self.selected_session_ids.discard(sid)
        self._update_delete_button_label()

    def _select_all(self):
        """Selects all non-active sessions across ALL pages."""
        for s in self.session_data:
            sid = s["session_id"]
            if sid != self.active_session_id:
                self.selected_session_ids.add(sid)

        # Sync visible checkboxes on current page
        for sid, var in self.checkbox_vars.items():
            if sid != self.active_session_id:
                var.set(True)
        self._update_delete_button_label()

    def _deselect_all(self):
        """Clears all session selections across ALL pages."""
        self.selected_session_ids.clear()
        for var in self.checkbox_vars.values():
            var.set(False)
        self._update_delete_button_label()

    def _update_delete_button_label(self):
        """Accurately calculates total count and byte size across ALL selected items in dataset."""
        selected_count = len(self.selected_session_ids)
        selected_bytes = sum(
            s.get("size_bytes", 0) for s in self.session_data
            if s["session_id"] in self.selected_session_ids
        )
        size_str = format_bytes(selected_bytes)
        self.delete_btn.configure(text=f"🗑️ Delete Selected ({selected_count} sessions, ~{size_str})")

    def _delete_selected(self):
        selected_ids = list(self.selected_session_ids)
        if not selected_ids:
            messagebox.showinfo("No Selection", "Please select at least one session to delete.")
            return

        delete_disk = self.delete_disk_files_var.get()
        has_active = self.active_session_id in selected_ids
        target_desc = "from disk and ledger" if delete_disk else "from the app ledger"
        warn_msg = f"Are you sure you want to remove {len(selected_ids)} session(s) {target_desc}?\nThis action cannot be undone."
        if has_active:
            warn_msg += "\n\n⚠️ WARNING: The currently active session is included in this selection!"

        confirm = messagebox.askyesno("Confirm Removal", warn_msg, icon="warning")
        if not confirm:
            return

        freed_total = 0
        deleted_count = 0

        for s in self.session_data:
            sid = s["session_id"]
            if sid in selected_ids:
                ok, freed, _ = delete_session_files(
                    sid,
                    folder_path=s.get("folder"),
                    file_path=s.get("file"),
                    delete_disk_files=delete_disk
                )
                if ok:
                    deleted_count += 1
                    freed_total += freed

        # Clear selection set after deletion
        self.selected_session_ids.clear()

        result_str = f"Freed {format_bytes(freed_total)} of disk space!" if delete_disk else "Removed records from ledger."
        messagebox.showinfo(
            "Cleanup Complete",
            f"Successfully removed {deleted_count} session(s).\n{result_str}"
        )

        self._refresh_session_list()
        if self.on_cleanup_complete:
            self.on_cleanup_complete()

    def _run_quick_prune(self, mode: str):
        delete_disk = self.delete_disk_files_var.get()
        target_desc = "from disk and ledger" if delete_disk else "from ledger"

        if mode == "7d":
            confirm = messagebox.askyesno("Prune Old Sessions", f"Delete all sessions older than 7 days {target_desc} (preserving active session)?")
            if not confirm: return
            res = prune_sessions_by_age(7, keep_active=True, delete_disk_files=delete_disk)
        elif mode == "30d":
            confirm = messagebox.askyesno("Prune Old Sessions", f"Delete all sessions older than 30 days {target_desc} (preserving active session)?")
            if not confirm: return
            res = prune_sessions_by_age(30, keep_active=True, delete_disk_files=delete_disk)
        elif mode == "keep5":
            confirm = messagebox.askyesno("Keep Latest 5", f"Keep only the 5 most recent sessions and delete all older ones {target_desc}?")
            if not confirm: return
            res = prune_sessions_keep_latest(5, keep_active=True, delete_disk_files=delete_disk)
        elif mode == "empty":
            res = prune_empty_sessions(delete_disk_files=delete_disk)
        elif mode == "all_previous":
            confirm = messagebox.askyesno("Delete All Previous", f"Are you sure you want to delete ALL historical sessions {target_desc} (keeping only active)?")
            if not confirm: return
            res = prune_all_previous(keep_active=True, delete_disk_files=delete_disk)
        else:
            return

        cnt = res.get("deleted_count", 0)
        freed = res.get("freed_str", "0 B")
        res_text = f"Freed {freed} of disk space!" if delete_disk else "Purged records from ledger."
        messagebox.showinfo("Prune Complete", f"Processed {cnt} session(s).\n{res_text}")
        self._refresh_session_list()
        if self.on_cleanup_complete:
            self.on_cleanup_complete()

    def _open_storage_folder(self):
        """Opens the primary .gemini/brain directory in Explorer."""
        ok, msg = open_storage_folder()
        if not ok:
            messagebox.showwarning("Storage Folder", msg)

    def _sync_with_disk(self):
        """Synchronizes account_usage.json ledger with physical files on disk, pruning orphaned records with a safety confirmation prompt."""
        warn_msg = (
            "Syncing with disk storage will inspect all '.gemini/brain' directories and permanently purge "
            "all session history records from 'account_usage.json' whose physical files no longer exist on disk.\n\n"
            "⚠️ WARNING: This operation will permanently delete all unmatched ledger records and is IRREVERSIBLE.\n\n"
            "Are you sure you want to proceed with the disk synchronization?"
        )
        confirm = messagebox.askyesno("Confirm Storage Sync & Ledger Prune", warn_msg, icon="warning")
        if not confirm:
            return

        res = sync_and_prune_orphaned_sessions()
        cnt = res.get("orphaned_count", 0)
        if cnt > 0:
            messagebox.showinfo(
                "Sync Complete",
                f"Ledger synced with disk storage.\nRemoved {cnt} orphaned/unmatched session record(s) from account_usage.json."
            )
        else:
            messagebox.showinfo(
                "Sync Complete",
                "Ledger is already in sync with on-disk storage.\nNo unmatched records were found."
            )
        self._refresh_session_list()
        if self.on_cleanup_complete:
            self.on_cleanup_complete()

    def _copy_session_id(self, sid: str):
        """Copies session ID to system clipboard with visual feedback."""
        try:
            self.clipboard_clear()
            self.clipboard_append(sid)
            self._show_copied_feedback(sid)
        except Exception:
            pass

    def _show_copied_feedback(self, sid: str):
        """Displays temporary confirmation text next to the list title."""
        if not self.winfo_exists():
            return
        short_id = sid[:18] + ("..." if len(sid) > 18 else "")
        self.copied_feedback_lbl.configure(text=f"📋 Copied: {short_id}")
        if getattr(self, "_copied_feedback_timer", None):
            try:
                self.after_cancel(self._copied_feedback_timer)
            except Exception:
                pass
        self._copied_feedback_timer = self.after(
            2500,
            lambda: self.copied_feedback_lbl.configure(text="") if self.winfo_exists() and hasattr(self, "copied_feedback_lbl") else None
        )

    def destroy(self):
        if getattr(self, "_active_context_menu", None) is not None:
            try:
                self._active_context_menu.destroy()
            except Exception:
                pass
            self._active_context_menu = None
        if getattr(self, "_copied_feedback_timer", None):
            try:
                self.after_cancel(self._copied_feedback_timer)
            except Exception:
                pass
            self._copied_feedback_timer = None
        if hasattr(self.master, "cleaner_dialog_window") and self.master.cleaner_dialog_window == self:
            self.master.cleaner_dialog_window = None
        super().destroy()
        if hasattr(self.master, "_update_watcher_activity"):
            self.master._update_watcher_activity()

    def _open_session_in_explorer(self, session_dict: Dict[str, Any]):
        """Opens the folder of a specific session in the OS file explorer."""
        sid = session_dict.get("session_id", "")
        folder = session_dict.get("session_root_dir") or session_dict.get("folder")
        ok, msg = open_session_folder(sid, folder_path=folder)
        if not ok:
            messagebox.showwarning("Open Folder", msg)

    def _delete_single_session(self, session_dict: Dict[str, Any]):
        """Deletes a single session from context menu."""
        sid = session_dict.get("session_id", "")
        is_active = (sid == self.active_session_id)
        delete_disk = self.delete_disk_files_var.get()
        target_desc = "from disk and ledger" if delete_disk else "from the app ledger"

        warn_msg = f"Are you sure you want to remove session '{sid[:16]}...' {target_desc}?"
        if is_active:
            warn_msg += "\n\n⚠️ WARNING: This is the currently active session!"

        confirm = messagebox.askyesno("Confirm Deletion", warn_msg, icon="warning")
        if not confirm:
            return

        ok, _, msg = delete_session_files(
            sid,
            folder_path=session_dict.get("folder"),
            file_path=session_dict.get("file"),
            delete_disk_files=delete_disk
        )
        if ok:
            messagebox.showinfo("Session Deleted", msg)
            self._refresh_session_list()
            if self.on_cleanup_complete:
                self.on_cleanup_complete()

    def _show_context_menu(self, event, session_dict: Dict[str, Any]):
        """Renders right-click context menu for an individual session row with rapid-click debouncing."""
        import time
        now = time.time()
        if now - getattr(self, "_last_context_menu_time", 0.0) < 0.25:
            return
        self._last_context_menu_time = now

        sid = session_dict.get("session_id", "")
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
        menu.add_command(
            label="📋 Copy Session ID",
            command=lambda: self._copy_session_id(sid)
        )
        menu.add_command(
            label="📁 Open in File Explorer",
            command=lambda: self._open_session_in_explorer(session_dict)
        )
        menu.add_separator()
        menu.add_command(
            label="🗑️ Delete This Session",
            command=lambda: self._delete_single_session(session_dict)
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
