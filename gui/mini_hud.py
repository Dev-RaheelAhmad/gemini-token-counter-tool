import customtkinter as ctk
from typing import Callable, Optional, Dict, Any, Tuple
from core.config import config
from core.account_manager import get_active_google_account
from gui.window_utils import get_screen_work_area, get_window_scale


class MiniHUDContextMenu(ctk.CTkToplevel):
    """Modern CustomTkinter popup context menu with 100% reliable cross-platform rendering."""
    def __init__(self, parent_hud, x: int, y: int):
        self._deactivate_windows_window_header_manipulation = True
        super().__init__(parent_hud)
        self.parent_hud = parent_hud
        
        # Borderless, Topmost & Clean Background
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=("#ffffff", "#1e222d"))

        is_dark = ctk.get_appearance_mode().lower() == "dark"
        
        # Card container with sleek border and rounded corners
        self.card = ctk.CTkFrame(
            self,
            corner_radius=8,
            fg_color=("#ffffff", "#1e222d"),
            border_width=1,
            border_color=("#94a3b8", "#334155")
        )
        self.card.pack(fill="both", expand=True, padx=2, pady=2)

        # Build Menu Items
        self._build_menu_items(is_dark)

        # Calculate snug dimensions & position safely on screen right at mouse cursor
        self.update_idletasks()
        scale = getattr(self.parent_hud, "_get_scale", lambda: 1.0)()
        req_w = max(195, int(round((self.card.winfo_reqwidth() + 4) / scale)))
        req_h = max(10, int(round((self.card.winfo_reqheight() + 4) / scale)))
        
        phys_w = int(round(req_w * scale))
        phys_h = int(round(req_h * scale))
        
        wl, wt, wr, wb = get_screen_work_area(self)
        clamped_x = max(wl, min(x, wr - phys_w))
        clamped_y = max(wt, min(y, wb - phys_h))
            
        self.geometry(f"{req_w}x{req_h}+{clamped_x}+{clamped_y}")

        # Auto-dismiss on Esc or FocusOut
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<FocusOut>", self._on_focus_out)
        self.after(50, lambda: self.focus_force() if self.winfo_exists() else None)

    def _build_menu_items(self, is_dark: bool):
        hud = self.parent_hud
        
        items = []
        is_bubble_mode = hud.is_minimized and not hud.is_hover_expanded
        if is_bubble_mode:
            items.append(("🗖", "Expand Mini-Hub", hud._expand_on_click))
        else:
            items.append(("🗕", "Minimize to Bubble", hud._collapse_to_bubble))

        items.append(("🖥️", "Open Full Dashboard", hud._restore_dashboard))
        items.append("---")
        
        pin_text = "Unpin (Disable Topmost)" if hud.is_pinned else "Pin (Always on Top)"
        items.append(("📌", pin_text, hud._toggle_pin))
        
        scope_text = "Hide 7-Day Window" if hud.show_7d_expanded else "Show 7-Day Window"
        items.append(("📅", scope_text, hud._toggle_7d_view))
        
        items.append(("🔄", "Refresh Live Stats", hud._recalculate_hud_view))
        items.append("---")
        
        # Opacity Presets
        cur_op = float(config.get("mini_hud_opacity") if config.get("mini_hud_opacity") is not None else 1.0)
        presets = [
            (1.0, "Opacity: 100% (Default)"),
            (0.92, "Opacity: 92%"),
            (0.75, "Opacity: 75% (Transparent)"),
            (0.50, "Opacity: 50% (Glass)")
        ]
        for op_val, op_lbl in presets:
            is_active = abs(cur_op - op_val) < 0.05
            prefix = "✓ " if is_active else "   "
            items.append((prefix, op_lbl, lambda v=op_val: hud._set_opacity(v)))

        items.append("---")
        items.append(("❌", "Close Mini-Hub", hud.withdraw))

        text_color = ("#0f172a", "#f8fafc")
        hover_bg = ("#e0e7ff", "#2563eb")

        for item in items:
            if item == "---":
                sep = ctk.CTkFrame(self.card, height=1, fg_color=("#e2e8f0", "#334155"))
                sep.pack(fill="x", padx=6, pady=3)
            else:
                icon, label, cmd = item
                full_text = f"{icon}  {label}" if icon else label
                
                is_close = "Close" in label
                item_fg = ("#dc2626", "#f87171") if is_close else text_color
                item_hover = ("#fee2e2", "#7f1d1d") if is_close else hover_bg
                
                btn = ctk.CTkButton(
                    self.card,
                    text=full_text,
                    anchor="w",
                    height=26,
                    corner_radius=5,
                    font=ctk.CTkFont(size=11),
                    fg_color="transparent",
                    text_color=item_fg,
                    hover_color=item_hover,
                    command=self._wrap_action(cmd)
                )
                btn.pack(fill="x", padx=4, pady=1)

    def _wrap_action(self, cmd):
        def _execute():
            self.destroy()
            if cmd:
                cmd()
        return _execute

    def _on_focus_out(self, event):
        if not self.winfo_exists():
            return
        try:
            focus = self.focus_get()
            if focus is None or not str(focus).startswith(str(self)):
                self.destroy()
        except Exception:
            pass

    def destroy(self):
        if getattr(self, "parent_hud", None) and getattr(self.parent_hud, "_context_menu_win", None) is self:
            self.parent_hud._context_menu_win = None
        super().destroy()


class MiniHUD(ctk.CTkToplevel):
    """
    A floating, draggable, customizable widget for desktop token monitoring.
    Features dedicated 5-Hour and 7-Day cards, window-scoped breakdowns,
    a 1-click 7D toggle button, and a dedicated Always-On-Top Pin/Unpin button.
    """

    def __init__(
        self,
        master,
        on_restore_callback: Callable[[], None],
        on_visibility_change: Optional[Callable[[], None]] = None,
        on_toggle_scope_callback: Optional[Callable[[bool], None]] = None,
        **kwargs
    ):
        # Deactivate CustomTkinter Windows header manipulation so it does not inject taskbar icons or trigger withdraw loops
        self._deactivate_windows_window_header_manipulation = True

        super().__init__(master, **kwargs)
        self.on_restore_callback = on_restore_callback
        self.on_visibility_change = on_visibility_change
        self.on_toggle_scope_callback = on_toggle_scope_callback

        # Suppress async titlebar icon insertion which interferes with borderless windows
        self._iconbitmap_method_called = True

        # Window properties - borderless popup
        self.title("Gemini Token Monitor - Mini HUD")
        self.overrideredirect(True)

        # Apply safe Win32 taskbar configuration
        self._hide_from_taskbar()

        # Pin / Always on Top state
        self.is_pinned = bool(config.get("hud_always_on_top"))
        self.attributes("-topmost", self.is_pinned)

        # Minimized Floating Hover Bubble state (defaults to False for full Mini-Hub window display)
        self.is_minimized = False
        self.is_hover_expanded = False
        self._tooltip_win = None
        self._tooltip_timer = None
        self._context_menu_win = None

        # Load independent bubble anchor and full HUD window positions
        self._bubble_pos = None
        saved_bubble_geo = config.get("mini_hud_bubble_geometry") or ""
        if saved_bubble_geo:
            import re
            m = re.search(r"([+-]?\d+)([+-]\d+)$", str(saved_bubble_geo))
            if m:
                self._bubble_pos = (int(m.group(1)), int(m.group(2)))

        self._hud_pos = None
        saved_hud_geo = config.get("mini_hud_geometry") or ""
        if saved_hud_geo:
            import re
            m = re.search(r"([+-]?\d+)([+-]\d+)$", str(saved_hud_geo))
            if m:
                self._hud_pos = (int(m.group(1)), int(m.group(2)))

        self.apply_opacity()
        self.resizable(False, False)
        self.bind("<FocusOut>", self._on_focus_out_handler)

        self._offset_x = 0
        self._offset_y = 0
        self._press_x = 0
        self._press_y = 0
        self._is_dragging = False

        # Timer references for leak-free teardown
        self._hover_collapse_timer = None
        self._focus_collapse_timer = None
        self._tooltip_timer = None
        self._tooltip_leave_timer = None

        self.show_7d_expanded = bool(config.get("hud_show_7d_expanded"))
        self.last_report: Optional[Dict[str, Any]] = None

        # Main Container Frame with Light/Dark support
        self.main_frame = ctk.CTkFrame(
            self,
            corner_radius=16 if (self.is_minimized and not self.is_hover_expanded) else 14,
            fg_color=("white", "#131722"),
            border_width=1,
            border_color=("#cbd5e1", "#2563eb")
        )
        self.main_frame.pack(fill="both", expand=True, padx=2, pady=2)
        self._bind_drag(self.main_frame)

        # ---------------- 1. FLOATING BUBBLE VIEW (Minimized) ----------------
        self.bubble_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.bubble_frame.grid_columnconfigure(0, weight=0)  # Time Frame
        self.bubble_frame.grid_columnconfigure(1, weight=1)  # Active Session
        self.bubble_frame.grid_columnconfigure(2, weight=1)  # All Sessions
        self.bubble_frame.grid_columnconfigure(3, weight=0)  # Quota

        # Row 0: Header Row
        self.bubble_hdr_tf = ctk.CTkLabel(
            self.bubble_frame,
            text="Time",
            font=ctk.CTkFont(size=8, weight="bold"),
            text_color=("#64748b", "#94a3b8"),
            anchor="w"
        )
        self.bubble_hdr_tf.grid(row=0, column=0, padx=(4, 6), pady=(2, 1), sticky="w")

        self.bubble_hdr_act = ctk.CTkLabel(
            self.bubble_frame,
            text="Active",
            font=ctk.CTkFont(size=8, weight="bold"),
            text_color=("#64748b", "#94a3b8"),
            anchor="w"
        )
        self.bubble_hdr_act.grid(row=0, column=1, padx=(2, 6), pady=(2, 1), sticky="w")

        self.bubble_hdr_all = ctk.CTkLabel(
            self.bubble_frame,
            text="All",
            font=ctk.CTkFont(size=8, weight="bold"),
            text_color=("#64748b", "#94a3b8"),
            anchor="w"
        )
        self.bubble_hdr_all.grid(row=0, column=2, padx=(2, 6), pady=(2, 1), sticky="w")

        self.bubble_hdr_quota = ctk.CTkLabel(
            self.bubble_frame,
            text="Quota",
            font=ctk.CTkFont(size=8, weight="bold"),
            text_color=("#64748b", "#94a3b8"),
            anchor="e"
        )
        self.bubble_hdr_quota.grid(row=0, column=3, padx=(2, 4), pady=(2, 1), sticky="e")

        # Row 1: Header Underline Separator
        self.bubble_hdr_sep = ctk.CTkFrame(self.bubble_frame, height=1, fg_color=("#cbd5e1", "#283042"))
        self.bubble_hdr_sep.grid(row=1, column=0, columnspan=4, sticky="ew", padx=2, pady=1)

        # Row 2: 5H Section (Blue Theme: 5H badge, Active ⚡, All ★, Quota %)
        self.bubble_5h_badge = ctk.CTkLabel(
            self.bubble_frame,
            text="5H",
            width=22,
            height=16,
            corner_radius=3,
            fg_color=("#dbeafe", "#1e293b"),
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=("#1d4ed8", "#60a5fa")
        )
        self.bubble_5h_badge.grid(row=2, column=0, padx=(4, 6), pady=(1, 1), sticky="w")

        self.bubble_5h_act_lbl = ctk.CTkLabel(
            self.bubble_frame,
            text="0",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("#1d4ed8", "#60a5fa"),
            anchor="w"
        )
        self.bubble_5h_act_lbl.grid(row=2, column=1, padx=(2, 6), pady=(1, 1), sticky="w")

        self.bubble_5h_all_lbl = ctk.CTkLabel(
            self.bubble_frame,
            text="0",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("#2563eb", "#93c5fd"),
            anchor="w"
        )
        self.bubble_5h_all_lbl.grid(row=2, column=2, padx=(2, 6), pady=(1, 1), sticky="w")

        self.bubble_5h_pct_lbl = ctk.CTkLabel(
            self.bubble_frame,
            text="100%",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("#059669", "#34d399"),
            anchor="e"
        )
        self.bubble_5h_pct_lbl.grid(row=2, column=3, padx=(2, 4), pady=(1, 1), sticky="e")

        # Row 3: Middle Separator
        self.bubble_sep = ctk.CTkFrame(self.bubble_frame, height=1, fg_color=("#e2e8f0", "#1e293b"))
        self.bubble_sep.grid(row=3, column=0, columnspan=4, sticky="ew", padx=2, pady=1)

        # Row 4: 7D Section (Purple Theme: 7D badge, Active, All, Quota %)
        self.bubble_7d_badge = ctk.CTkLabel(
            self.bubble_frame,
            text="7D",
            width=22,
            height=16,
            corner_radius=3,
            fg_color=("#f3e8ff", "#2e1065"),
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=("#7c3aed", "#c084fc")
        )
        self.bubble_7d_badge.grid(row=4, column=0, padx=(4, 6), pady=(1, 2), sticky="w")

        self.bubble_7d_act_lbl = ctk.CTkLabel(
            self.bubble_frame,
            text="0",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("#7c3aed", "#c084fc"),
            anchor="w"
        )
        self.bubble_7d_act_lbl.grid(row=4, column=1, padx=(2, 6), pady=(1, 2), sticky="w")

        self.bubble_7d_all_lbl = ctk.CTkLabel(
            self.bubble_frame,
            text="0",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("#9333ea", "#d8b4fe"),
            anchor="w"
        )
        self.bubble_7d_all_lbl.grid(row=4, column=2, padx=(2, 6), pady=(1, 2), sticky="w")

        self.bubble_7d_pct_lbl = ctk.CTkLabel(
            self.bubble_frame,
            text="100%",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("#059669", "#34d399"),
            anchor="e"
        )
        self.bubble_7d_pct_lbl.grid(row=4, column=3, padx=(2, 4), pady=(1, 2), sticky="e")

        # Backward compatibility alias
        self.bubble_icon = self.bubble_5h_act_lbl

        self._bind_bubble_events(self.bubble_frame)
        self._bind_bubble_events(self.bubble_hdr_tf)
        self._bind_bubble_events(self.bubble_hdr_act)
        self._bind_bubble_events(self.bubble_hdr_all)
        self._bind_bubble_events(self.bubble_hdr_quota)
        self._bind_bubble_events(self.bubble_hdr_sep)
        self._bind_bubble_events(self.bubble_5h_badge)
        self._bind_bubble_events(self.bubble_5h_act_lbl)
        self._bind_bubble_events(self.bubble_5h_all_lbl)
        self._bind_bubble_events(self.bubble_5h_pct_lbl)
        self._bind_bubble_events(self.bubble_sep)
        self._bind_bubble_events(self.bubble_7d_badge)
        self._bind_bubble_events(self.bubble_7d_act_lbl)
        self._bind_bubble_events(self.bubble_7d_all_lbl)
        self._bind_bubble_events(self.bubble_7d_pct_lbl)
        self._bind_bubble_events(self.main_frame)

        # ---------------- 2. FULL HUD VIEW (Expanded) ----------------
        # Top Bar
        self.top_bar = ctk.CTkFrame(self.main_frame, fg_color="transparent", height=28)
        self._bind_drag(self.top_bar)
        self.top_bar.bind("<Double-Button-1>", lambda e: self._toggle_minimized())

        # App Title & Icon
        title_lbl = ctk.CTkLabel(
            self.top_bar,
            text="⚡ GEMINI MONITOR",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#1d4ed8", "#60a5fa")
        )
        title_lbl.pack(side="left")
        self._bind_drag(title_lbl)
        title_lbl.bind("<Double-Button-1>", lambda e: self._toggle_minimized())

        # Close Button (✕)
        close_btn = ctk.CTkButton(
            self.top_bar,
            text="✕",
            width=20,
            height=20,
            corner_radius=4,
            fg_color="transparent",
            hover_color=("#fee2e2", "#7f1d1d"),
            text_color=("#64748b", "#94a3b8"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.withdraw
        )
        close_btn.pack(side="right", padx=(2, 0))

        # Minimize Button (🗕)
        self.minimize_btn = ctk.CTkButton(
            self.top_bar,
            text="🗕",
            width=20,
            height=20,
            corner_radius=4,
            fg_color="transparent",
            hover_color=("#e2e8f0", "#1e293b"),
            text_color=("#64748b", "#94a3b8"),
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._toggle_minimized
        )
        self.minimize_btn.pack(side="right", padx=(2, 2))

        # Restore Dashboard Button (⤢)
        restore_btn = ctk.CTkButton(
            self.top_bar,
            text="⤢",
            width=20,
            height=20,
            corner_radius=4,
            fg_color="transparent",
            hover_color=("#e2e8f0", "#1e293b"),
            text_color=("#64748b", "#94a3b8"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._restore_dashboard
        )
        restore_btn.pack(side="right", padx=(2, 2))

        # Pin / Always on top button (📌)
        self.pin_btn = ctk.CTkButton(
            self.top_bar,
            text="📌",
            width=22,
            height=20,
            corner_radius=4,
            fg_color="#3B82F6" if self.is_pinned else ("#e2e8f0", "#283042"),
            hover_color=("#2563eb", "#1d4ed8") if self.is_pinned else ("#cbd5e1", "#374151"),
            text_color="#ffffff" if self.is_pinned else ("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=10),
            command=self._toggle_pin
        )
        self.pin_btn.pack(side="right", padx=(2, 2))

        # 7D Expand Toggle Button (📅 7D)
        self.toggle_7d_btn = ctk.CTkButton(
            self.top_bar,
            text="📅 7D",
            width=46,
            height=20,
            corner_radius=4,
            fg_color="#8B5CF6" if self.show_7d_expanded else ("#e2e8f0", "#283042"),
            hover_color=("#7c3aed", "#6d28d9") if self.show_7d_expanded else ("#cbd5e1", "#374151"),
            text_color="#ffffff" if self.show_7d_expanded else ("#0f172a", "#f8fafc"),
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self._toggle_7d_view
        )
        self.toggle_7d_btn.pack(side="right", padx=(2, 2))

        # Content Frame
        self.content_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self._build_sections()

        # Apply initial view mode (Bubble vs Full)
        self._apply_view_mode()
        self._restore_position()

        # Immediately calculate and populate with live report data matching independent scopes
        self._recalculate_hud_view()

        # Recursively bind right-click context menu across all initial frames and labels
        self._bind_context_menu_recursive(self)

    def _is_child_of_self(self, widget):
        """Checks if a widget belongs to this MiniHUD window."""
        if widget is None:
            return False
        if widget is self or str(widget) == str(self):
            return True
        curr = widget
        while curr:
            if curr is self or str(curr) == str(self):
                return True
            curr = getattr(curr, "master", None)
        return False

    def _on_global_right_click(self, event=None):
        """Intercepts right-clicks and triggers context menu if within bounds."""
        if not self.winfo_exists():
            return
        try:
            w = getattr(event, "widget", None)
            is_match = self._is_child_of_self(w)
            if not is_match and w is not None:
                self_path = str(self)
                w_path = str(w)
                is_match = (w_path == self_path or w_path.startswith(self_path + "."))

            if not is_match:
                mx = getattr(event, "x_root", None) or self.winfo_pointerx()
                my = getattr(event, "y_root", None) or self.winfo_pointery()
                wx = self.winfo_rootx()
                wy = self.winfo_rooty()
                ww = self.winfo_width()
                wh = self.winfo_height()
                if wx <= mx <= wx + ww and wy <= my <= wy + wh:
                    is_match = True

            if is_match:
                self._show_context_menu(event)
        except Exception:
            pass

    def hide_hud(self):
        """Hides/withdraws the Mini-HUD window."""
        self.withdraw()

    def withdraw(self):
        self._hide_tooltip()
        self._save_position()
        if hasattr(self, "_context_menu_win") and self._context_menu_win and self._context_menu_win.winfo_exists():
            try:
                self._context_menu_win.destroy()
            except Exception:
                pass
            self._context_menu_win = None
        super().withdraw()
        if hasattr(self, "on_visibility_change") and self.on_visibility_change:
            try:
                self.on_visibility_change()
            except Exception:
                pass

    def deiconify(self):
        super().deiconify()
        self.apply_opacity()
        self.attributes("-topmost", self.is_pinned)
        self._apply_view_mode()
        self._recalculate_hud_view()
        if hasattr(self, "on_visibility_change") and self.on_visibility_change:
            try:
                self.on_visibility_change()
            except Exception:
                pass

    def _bind_context_menu_recursive(self, widget):
        """Recursively binds right-click context menu events to a widget and all its internal CTk & Tk children."""
        def _bind_single(w):
            for sub in [w, getattr(w, "_canvas", None), getattr(w, "_label", None), getattr(w, "_text_label", None), getattr(w, "_image_label", None)]:
                if sub is not None and hasattr(sub, "bind"):
                    try:
                        sub.bind("<Button-3>", self._show_context_menu)
                        sub.bind("<Button-2>", self._show_context_menu)
                    except Exception:
                        pass

        _bind_single(widget)
        try:
            for child in widget.winfo_children():
                self._bind_context_menu_recursive(child)
        except Exception:
            pass

    def _bind_bubble_events(self, widget):
        """Binds drag, hover, and right-click context menu events to floating bubble components."""
        for sub in [widget, getattr(widget, "_canvas", None), getattr(widget, "_label", None), getattr(widget, "_text_label", None)]:
            if sub is not None and hasattr(sub, "bind"):
                try:
                    sub.bind("<ButtonPress-1>", self._start_drag, add="+")
                    sub.bind("<B1-Motion>", self._do_drag, add="+")
                    sub.bind("<ButtonRelease-1>", self._end_drag, add="+")
                    sub.bind("<Enter>", self._on_bubble_hover_enter, add="+")
                    sub.bind("<Leave>", self._on_bubble_hover_leave, add="+")
                    sub.bind("<Button-3>", self._show_context_menu, add="+")
                    sub.bind("<Button-2>", self._show_context_menu, add="+")
                    sub.bind("<ButtonRelease-3>", self._show_context_menu, add="+")
                except Exception:
                    pass

    def _bind_tooltip_events(self, widget):
        """Recursively binds hover enter and leave events to tooltip window and its children."""
        def _bind_single(w):
            for sub in [w, getattr(w, "_canvas", None), getattr(w, "_label", None), getattr(w, "_text_label", None), getattr(w, "_image_label", None)]:
                if sub is not None and hasattr(sub, "bind"):
                    try:
                        sub.bind("<Enter>", self._on_bubble_hover_enter, add="+")
                        sub.bind("<Leave>", self._on_bubble_hover_leave, add="+")
                    except Exception:
                        pass

        _bind_single(widget)
        try:
            for child in widget.winfo_children():
                self._bind_tooltip_events(child)
        except Exception:
            pass

    def _get_tooltip_text(self) -> str:
        """Generates a comprehensive live stats report for the floating bubble hover tooltip matching the full Mini-Hub."""
        if not self.last_report:
            from core.account_manager import get_active_google_account
            acc_name = get_active_google_account() or "Default Account"
            return f"⚡ GEMINI TOKEN MONITOR\n👤 {acc_name}"
        
        all_rep = self.last_report
        act_rep = getattr(self, "last_session_report", None) or all_rep
        
        # Account info
        from core.account_manager import get_active_google_account
        acc_name = get_active_google_account() or "Default Account"
        
        def _fmt(val: int) -> str:
            if val >= 1000000:
                return f"{val/1000000:.2f}M"
            return f"{val:,}"

        # 5H Data
        used_5h_all = all_rep.get("tokens_5h", 0)
        think_5h_all = all_rep.get("thinking_5h", 0)
        prompt_5h_all = all_rep.get("prompt_5h", 0)
        cand_5h_all = all_rep.get("candidates_5h", 0)

        used_5h_act = act_rep.get("tokens_5h", 0)
        think_5h_act = act_rep.get("thinking_5h", 0)
        prompt_5h_act = act_rep.get("prompt_5h", 0)
        cand_5h_act = act_rep.get("candidates_5h", 0)

        pct_5h_rem = float(all_rep.get("pct_5h_remaining", 0.0))
        reset_5h = all_rep.get("reset_5h_str", "Reset")
        short_reset_5h = reset_5h.split("(")[0].strip() if "(" in reset_5h else reset_5h

        # 7D Data
        used_7d_all = all_rep.get("tokens_7d", 0)
        think_7d_all = all_rep.get("thinking_7d", 0)
        prompt_7d_all = all_rep.get("prompt_7d", 0)
        cand_7d_all = all_rep.get("candidates_7d", 0)

        used_7d_act = act_rep.get("tokens_7d", 0)
        think_7d_act = act_rep.get("thinking_7d", 0)
        prompt_7d_act = act_rep.get("prompt_7d", 0)
        cand_7d_act = act_rep.get("candidates_7d", 0)

        pct_7d_rem = float(all_rep.get("pct_7d_remaining", 0.0))
        reset_7d = all_rep.get("reset_7d_str", "Reset")
        short_reset_7d = reset_7d.split("(")[0].strip() if "(" in reset_7d else reset_7d

        lines = [
            "⚡ GEMINI TOKEN MONITOR",
            f"⏳ 5-HOUR WINDOW ({pct_5h_rem:.1f}% rem • 🔄 {short_reset_5h})",
            f"  ⚡ Active: {used_5h_act:,} tok  (📥 {_fmt(prompt_5h_act)} • 🧠 {_fmt(think_5h_act)} • 📤 {_fmt(cand_5h_act)})",
            f"  ★ All:    {used_5h_all:,} tok  (📥 {_fmt(prompt_5h_all)} • 🧠 {_fmt(think_5h_all)} • 📤 {_fmt(cand_5h_all)})",
            f"📅 7-DAY WINDOW ({pct_7d_rem:.1f}% rem • 🔄 {short_reset_7d})",
            f"  ⚡ Active: {used_7d_act:,} tok  (📥 {_fmt(prompt_7d_act)} • 🧠 {_fmt(think_7d_act)} • 📤 {_fmt(cand_7d_act)})",
            f"  ★ All:    {used_7d_all:,} tok  (📥 {_fmt(prompt_7d_all)} • 🧠 {_fmt(think_7d_all)} • 📤 {_fmt(cand_7d_all)})",
            f"👤 {acc_name}"
        ]
        return "\n".join(lines)

    def _build_tooltip_content(self, container: ctk.CTkFrame):
        """Builds a crisp, left-aligned, structured stats card inside the tooltip container."""
        # 1. Header Row
        hdr_lbl = ctk.CTkLabel(
            container,
            text="⚡ GEMINI TOKEN MONITOR",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#1d4ed8", "#60a5fa"),
            anchor="w",
            justify="left"
        )
        hdr_lbl.pack(fill="x", padx=8, pady=(4, 2), anchor="w")

        from core.account_manager import get_active_google_account
        acc_name = get_active_google_account() or "Default Account"

        if not self.last_report:
            sep = ctk.CTkFrame(container, height=1, fg_color=("#e2e8f0", "#1e293b"))
            sep.pack(fill="x", padx=6, pady=3)
            acc_lbl = ctk.CTkLabel(
                container,
                text=f"👤 {acc_name}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=("#475569", "#cbd5e1"),
                anchor="w",
                justify="left"
            )
            acc_lbl.pack(fill="x", padx=8, pady=(2, 4), anchor="w")
            return

        all_rep = self.last_report
        act_rep = getattr(self, "last_session_report", None) or all_rep

        def _fmt(val: int) -> str:
            if val >= 1000000:
                return f"{val/1000000:.2f}M"
            return f"{val:,}"

        # 5H Data
        used_5h_all = all_rep.get("tokens_5h", 0)
        think_5h_all = all_rep.get("thinking_5h", 0)
        prompt_5h_all = all_rep.get("prompt_5h", 0)
        cand_5h_all = all_rep.get("candidates_5h", 0)

        used_5h_act = act_rep.get("tokens_5h", 0)
        think_5h_act = act_rep.get("thinking_5h", 0)
        prompt_5h_act = act_rep.get("prompt_5h", 0)
        cand_5h_act = act_rep.get("candidates_5h", 0)

        pct_5h_rem = float(all_rep.get("pct_5h_remaining", 0.0))
        reset_5h = all_rep.get("reset_5h_str", "Reset")
        short_reset_5h = reset_5h.split("(")[0].strip() if "(" in reset_5h else reset_5h

        # 7D Data
        used_7d_all = all_rep.get("tokens_7d", 0)
        think_7d_all = all_rep.get("thinking_7d", 0)
        prompt_7d_all = all_rep.get("prompt_7d", 0)
        cand_7d_all = all_rep.get("candidates_7d", 0)

        used_7d_act = act_rep.get("tokens_7d", 0)
        think_7d_act = act_rep.get("thinking_7d", 0)
        prompt_7d_act = act_rep.get("prompt_7d", 0)
        cand_7d_act = act_rep.get("candidates_7d", 0)

        pct_7d_rem = float(all_rep.get("pct_7d_remaining", 0.0))
        reset_7d = all_rep.get("reset_7d_str", "Reset")
        short_reset_7d = reset_7d.split("(")[0].strip() if "(" in reset_7d else reset_7d

        # Divider 1
        sep1 = ctk.CTkFrame(container, height=1, fg_color=("#e2e8f0", "#1e293b"))
        sep1.pack(fill="x", padx=6, pady=3)

        # 5-Hour Section
        is_rt = all_rep.get("is_realtime_quota", False)
        if pct_5h_rem >= 60.0 or (pct_5h_rem == 0.0 and is_rt):
            col_5h_all = ("#15803d", "#10B981")
        elif pct_5h_rem >= 20.0:
            col_5h_all = ("#b45309", "#F59E0B")
        else:
            col_5h_all = ("#b91c1c", "#EF4444")

        h5_hdr = ctk.CTkLabel(
            container,
            text=f"⏳ 5-HOUR WINDOW ({pct_5h_rem:.1f}% rem • 🔄 {short_reset_5h})",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=col_5h_all,
            anchor="w",
            justify="left"
        )
        h5_hdr.pack(fill="x", padx=8, pady=(1, 0), anchor="w")

        h5_act = ctk.CTkLabel(
            container,
            text=f"  ⚡ Active: {used_5h_act:,} tok  (📥 {_fmt(prompt_5h_act)} • 🧠 {_fmt(think_5h_act)} • 📤 {_fmt(cand_5h_act)})",
            font=ctk.CTkFont(size=11),
            text_color=("#1d4ed8", "#60a5fa"),
            anchor="w",
            justify="left"
        )
        h5_act.pack(fill="x", padx=8, pady=(0, 0), anchor="w")

        h5_all = ctk.CTkLabel(
            container,
            text=f"  ★ All:    {used_5h_all:,} tok  (📥 {_fmt(prompt_5h_all)} • 🧠 {_fmt(think_5h_all)} • 📤 {_fmt(cand_5h_all)})",
            font=ctk.CTkFont(size=11),
            text_color=col_5h_all,
            anchor="w",
            justify="left"
        )
        h5_all.pack(fill="x", padx=8, pady=(0, 1), anchor="w")

        # Divider 2
        sep2 = ctk.CTkFrame(container, height=1, fg_color=("#e2e8f0", "#1e293b"))
        sep2.pack(fill="x", padx=6, pady=3)

        # 7-Day Section
        if pct_7d_rem >= 60.0 or (pct_7d_rem == 0.0 and is_rt):
            col_7d_all = ("#15803d", "#10B981")
        elif pct_7d_rem >= 20.0:
            col_7d_all = ("#b45309", "#F59E0B")
        else:
            col_7d_all = ("#b91c1c", "#EF4444")

        d7_hdr = ctk.CTkLabel(
            container,
            text=f"📅 7-DAY WINDOW ({pct_7d_rem:.1f}% rem • 🔄 {short_reset_7d})",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=col_7d_all,
            anchor="w",
            justify="left"
        )
        d7_hdr.pack(fill="x", padx=8, pady=(1, 0), anchor="w")

        d7_act = ctk.CTkLabel(
            container,
            text=f"  ⚡ Active: {used_7d_act:,} tok  (📥 {_fmt(prompt_7d_act)} • 🧠 {_fmt(think_7d_act)} • 📤 {_fmt(cand_7d_act)})",
            font=ctk.CTkFont(size=11),
            text_color=("#7c3aed", "#c084fc"),
            anchor="w",
            justify="left"
        )
        d7_act.pack(fill="x", padx=8, pady=(0, 0), anchor="w")

        d7_all = ctk.CTkLabel(
            container,
            text=f"  ★ All:    {used_7d_all:,} tok  (📥 {_fmt(prompt_7d_all)} • 🧠 {_fmt(think_7d_all)} • 📤 {_fmt(cand_7d_all)})",
            font=ctk.CTkFont(size=11),
            text_color=col_7d_all,
            anchor="w",
            justify="left"
        )
        d7_all.pack(fill="x", padx=8, pady=(0, 1), anchor="w")

        # Divider 3
        sep3 = ctk.CTkFrame(container, height=1, fg_color=("#e2e8f0", "#1e293b"))
        sep3.pack(fill="x", padx=6, pady=3)

        # Footer Row: Active User Email
        acc_lbl = ctk.CTkLabel(
            container,
            text=f"👤 {acc_name}",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#475569", "#cbd5e1"),
            anchor="w",
            justify="left"
        )
        acc_lbl.pack(fill="x", padx=8, pady=(1, 4), anchor="w")

    def _show_tooltip(self):
        """Displays a sleek, left-aligned, structured floating stats tooltip next to the bubble."""
        if not (self.is_minimized and not self.is_hover_expanded):
            return
        if self._is_dragging or self.state() == "withdrawn":
            return
        if self._tooltip_win and self._tooltip_win.winfo_exists():
            return
        try:
            self._tooltip_win = ctk.CTkToplevel(self)
            self._tooltip_win._deactivate_windows_window_header_manipulation = True
            self._tooltip_win.overrideredirect(True)
            self._tooltip_win.attributes("-topmost", True)
            self._tooltip_win.configure(fg_color=("#ffffff", "#131722"))
            
            # Ensure window is hidden from taskbar on Windows
            try:
                import sys, ctypes
                if sys.platform.startswith("win"):
                    hwnd = ctypes.windll.user32.GetParent(self._tooltip_win.winfo_id()) or self._tooltip_win.winfo_id()
                    GWL_EXSTYLE = -20
                    WS_EX_TOOLWINDOW = 0x00000080
                    WS_EX_APPWINDOW = 0x00040000
                    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
                    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            except Exception:
                pass

            # Card container with sleek border and rounded corners
            card = ctk.CTkFrame(
                self._tooltip_win,
                corner_radius=8,
                fg_color=("#ffffff", "#131722"),
                border_width=1,
                border_color=("#cbd5e1", "#334155")
            )
            card.pack(fill="both", expand=True, padx=2, pady=2)

            self._build_tooltip_content(card)
            self._bind_tooltip_events(self._tooltip_win)

            self._tooltip_win.update_idletasks()
            scale = self._get_scale()
            req_w = max(180, int(round((card.winfo_reqwidth() + 4) / scale)))
            req_h = max(10, int(round((card.winfo_reqheight() + 4) / scale)))
            
            phys_tw = int(round(req_w * scale))
            phys_th = int(round(req_h * scale))
            
            bx = self.winfo_x()
            by = self.winfo_y()
            cur_bw = self.winfo_width() if self.winfo_width() > 10 else int(round(160 * scale))
            cur_bh = self.winfo_height() if self.winfo_height() > 10 else int(round(44 * scale))
            
            wl, wt, wr, wb = get_screen_work_area(self)
            
            # Position horizontally: snug to the left of the bubble with 8px gap (or to the right if near left edge)
            if bx - phys_tw - 8 >= wl + 10:
                tx = bx - phys_tw - 8
            else:
                tx = bx + cur_bw + 8
            
            # Position vertically: align bottom with bottom of bubble (sits nicely down beside the bubble)
            ty = (by + cur_bh) - phys_th
            
            # Safely clamp within work area
            cx = max(wl + 10, min(tx, wr - phys_tw - 10))
            cy = max(wt + 10, min(ty, wb - phys_th - 10))
            
            self._tooltip_win.geometry(f"{req_w}x{req_h}+{cx}+{cy}")
        except Exception:
            self._tooltip_win = None

    def _hide_tooltip(self):
        """Hides and cleans up the hover tooltip."""
        if getattr(self, "_tooltip_timer", None):
            try:
                self.after_cancel(self._tooltip_timer)
            except Exception:
                pass
            self._tooltip_timer = None
        if getattr(self, "_tooltip_leave_timer", None):
            try:
                self.after_cancel(self._tooltip_leave_timer)
            except Exception:
                pass
            self._tooltip_leave_timer = None
        if getattr(self, "_tooltip_win", None):
            try:
                if self._tooltip_win.winfo_exists():
                    self._tooltip_win.destroy()
            except Exception:
                pass
            self._tooltip_win = None

    def _toggle_minimized(self):
        """Switches Mini HUD into Floating Bubble mode."""
        self._hide_tooltip()
        if (not self.is_minimized or self.is_hover_expanded) and self.winfo_exists() and not self._hud_pos:
            self._hud_pos = (self.winfo_x(), self.winfo_y())
            geo = f"{'+' if self._hud_pos[0] >= 0 else ''}{self._hud_pos[0]}{'+' if self._hud_pos[1] >= 0 else ''}{self._hud_pos[1]}"
            config.set("mini_hud_geometry", geo, save_now=False)
        self.is_minimized = True
        self.is_hover_expanded = False
        config.set("hud_minimized", True, save_now=False)
        self._apply_view_mode()
        self._recalculate_hud_view()

    def _expand_on_click(self):
        """Expands the floating bubble into the full Mini HUD on click, setting auto-shrink on mouse leave or click outside."""
        self._hide_tooltip()
        if not self._bubble_pos and self.winfo_exists():
            self._bubble_pos = (self.winfo_x(), self.winfo_y())
            geo = f"{'+' if self._bubble_pos[0] >= 0 else ''}{self._bubble_pos[0]}{'+' if self._bubble_pos[1] >= 0 else ''}{self._bubble_pos[1]}"
            config.set("mini_hud_bubble_geometry", geo, save_now=False)
        self.is_hover_expanded = True
        self._apply_view_mode()
        self._recalculate_hud_view()

    def _on_bubble_hover_enter(self, event=None):
        """Shows text-only stats tooltip when hovering over floating bubble without expanding the window."""
        if hasattr(self, "_tooltip_leave_timer") and self._tooltip_leave_timer:
            try:
                self.after_cancel(self._tooltip_leave_timer)
            except Exception:
                pass
            self._tooltip_leave_timer = None

        if self.is_minimized and not self.is_hover_expanded and not self._is_dragging:
            if getattr(self, "_tooltip_win", None) and self._tooltip_win.winfo_exists():
                return
            if not getattr(self, "_tooltip_timer", None):
                self._tooltip_timer = self.after(200, self._show_tooltip)

    def _on_bubble_hover_leave(self, event=None):
        """Debounces tooltip dismissal to avoid destroying and recreating on inner child crossings."""
        if hasattr(self, "_tooltip_leave_timer") and self._tooltip_leave_timer:
            try:
                self.after_cancel(self._tooltip_leave_timer)
            except Exception:
                pass
        self._tooltip_leave_timer = self.after(120, self._check_tooltip_dismiss)

    def _check_tooltip_dismiss(self):
        """Verifies if cursor has truly left the bubble bounding box before dismissing the tooltip."""
        self._tooltip_leave_timer = None
        if not self.winfo_exists() or self.state() == "withdrawn":
            self._hide_tooltip()
            return
        try:
            mx = self.winfo_pointerx()
            my = self.winfo_pointery()
            wx = self.winfo_rootx()
            wy = self.winfo_rooty()
            ww = self.winfo_width()
            wh = self.winfo_height()
            # If mouse is still inside bubble boundary, keep tooltip alive
            if (wx - 4 <= mx <= wx + ww + 4) and (wy - 4 <= my <= wy + wh + 4):
                return

            # If tooltip exists and mouse is hovering over the tooltip card, keep it alive
            if getattr(self, "_tooltip_win", None) and self._tooltip_win.winfo_exists():
                tw_x = self._tooltip_win.winfo_rootx()
                tw_y = self._tooltip_win.winfo_rooty()
                tw_w = self._tooltip_win.winfo_width()
                tw_h = self._tooltip_win.winfo_height()
                if (tw_x - 4 <= mx <= tw_x + tw_w + 4) and (tw_y - 4 <= my <= tw_y + tw_h + 4):
                    return

            self._hide_tooltip()
        except Exception:
            self._hide_tooltip()

    def _on_focus_out_handler(self, event=None):
        """Triggers focus-based collapse check when window loses focus."""
        if not self.is_pinned and not self._is_dragging and self.winfo_exists():
            if hasattr(self, "_focus_collapse_timer") and self._focus_collapse_timer:
                try:
                    self.after_cancel(self._focus_collapse_timer)
                except Exception:
                    pass
            self._focus_collapse_timer = self.after(200, self._check_focus_collapse_to_bubble)

    def _check_focus_collapse_to_bubble(self):
        """Collapses back to floating bubble when focus or click occurs outside the window while unpinned."""
        self._focus_collapse_timer = None
        if not self.winfo_exists() or self.state() == "withdrawn" or self.is_pinned or self._is_dragging:
            return
        try:
            # Check if any child widget in this window has focus
            focused = self.focus_get()
            if focused is not None:
                curr = focused
                while curr:
                    if curr == self:
                        return
                    curr = getattr(curr, "master", None)
            
            # Check if mouse pointer is inside the window bounds
            mx = self.winfo_pointerx()
            my = self.winfo_pointery()
            wx = self.winfo_rootx()
            wy = self.winfo_rooty()
            ww = self.winfo_width()
            wh = self.winfo_height()
            if (wx - 6 <= mx <= wx + ww + 6) and (wy - 6 <= my <= wy + wh + 6):
                return

            # Outside click / focus loss detected -> collapse back to floating bubble
            self._hide_tooltip()
            if (not self.is_minimized or self.is_hover_expanded) and self.winfo_exists() and not self._hud_pos:
                self._hud_pos = (self.winfo_x(), self.winfo_y())
                geo = f"{'+' if self._hud_pos[0] >= 0 else ''}{self._hud_pos[0]}{'+' if self._hud_pos[1] >= 0 else ''}{self._hud_pos[1]}"
                config.set("mini_hud_geometry", geo, save_now=False)
            self.is_minimized = True
            self.is_hover_expanded = False
            config.set("hud_minimized", True, save_now=False)
            self._apply_view_mode()
        except Exception:
            pass

    def _on_expanded_hover_leave(self, event=None):
        """Triggers hover collapse check when mouse leaves expanded Mini HUD."""
        if self.is_hover_expanded and not self.is_pinned and not self._is_dragging:
            if hasattr(self, "_hover_collapse_timer") and self._hover_collapse_timer:
                try:
                    self.after_cancel(self._hover_collapse_timer)
                except Exception:
                    pass
            self._hover_collapse_timer = self.after(250, self._check_hover_collapse)

    def _check_hover_collapse(self):
        """Checks if cursor has left the expanded HUD bounding box to smoothly shrink back into bubble."""
        self._hover_collapse_timer = None
        if not self.winfo_exists() or self.state() == "withdrawn":
            return
        if not self.is_hover_expanded or self.is_pinned or self._is_dragging:
            return
        try:
            mx = self.winfo_pointerx()
            my = self.winfo_pointery()
            wx = self.winfo_rootx()
            wy = self.winfo_rooty()
            ww = self.winfo_width()
            wh = self.winfo_height()

            # If still within bounds with safety margin, do nothing
            if (wx - 10 <= mx <= wx + ww + 10) and (wy - 10 <= my <= wy + wh + 10):
                return

            self._collapse_to_bubble()
        except Exception:
            pass

    def _collapse_to_bubble(self):
        """Collapses the full Mini-Hub window back to the compact floating bubble."""
        self._dismiss_context_menu()
        if hasattr(self, "_hover_collapse_timer") and self._hover_collapse_timer:
            try:
                self.after_cancel(self._hover_collapse_timer)
            except Exception:
                pass
            self._hover_collapse_timer = None
        if hasattr(self, "_focus_collapse_timer") and self._focus_collapse_timer:
            try:
                self.after_cancel(self._focus_collapse_timer)
            except Exception:
                pass
            self._focus_collapse_timer = None
        if (not self.is_minimized or self.is_hover_expanded) and self.winfo_exists() and not self._hud_pos:
            self._hud_pos = (self.winfo_x(), self.winfo_y())
            geo = f"{'+' if self._hud_pos[0] >= 0 else ''}{self._hud_pos[0]}{'+' if self._hud_pos[1] >= 0 else ''}{self._hud_pos[1]}"
            config.set("mini_hud_geometry", geo, save_now=False)
        self.is_minimized = True
        self.is_hover_expanded = False
        config.set("hud_minimized", True, save_now=False)
        self._apply_view_mode()

    def _dismiss_context_menu(self):
        """Dismisses any active context menu window."""
        if hasattr(self, "_context_menu_win") and self._context_menu_win and self._context_menu_win.winfo_exists():
            try:
                self._context_menu_win.destroy()
            except Exception:
                pass
            self._context_menu_win = None

    def _check_focus_and_auto_dismiss(self):
        """Auto-dismiss check when unpinned and lost focus."""
        if self.is_pinned:
            return
        self._check_focus_collapse_to_bubble()

    def _get_scale(self) -> float:
        return get_window_scale(self)

    def _get_bubble_dimensions(self) -> Tuple[int, int]:
        """Calculates dynamic snug width and height for the floating bubble based on rendered content."""
        self.update_idletasks()
        scale = self._get_scale()
        if hasattr(self, "bubble_frame") and self.bubble_frame.winfo_manager() == "pack":
            req_w = self.bubble_frame.winfo_reqwidth()
            req_h = self.bubble_frame.winfo_reqheight()
        else:
            req_w = self.main_frame.winfo_reqwidth()
            req_h = self.main_frame.winfo_reqheight()
        cur_w = max(140, int(round((req_w + 12) / scale)))
        cur_h = max(44, int(round((req_h + 8) / scale)))
        return cur_w, cur_h

    def _apply_view_mode(self):
        """Switches widget layout between Floating Bubble mode (dynamic compact) and Full HUD mode (350xAuto)."""
        try:
            if self.is_minimized and not self.is_hover_expanded:
                # Floating Bubble Mode
                if hasattr(self, "top_bar") and self.top_bar.winfo_manager() == "pack":
                    self.top_bar.pack_forget()
                if hasattr(self, "content_frame") and self.content_frame.winfo_manager() == "pack":
                    self.content_frame.pack_forget()
                if hasattr(self, "bubble_frame") and self.bubble_frame.winfo_manager() != "pack":
                    self.bubble_frame.pack(fill="both", expand=True)

                self.main_frame.configure(corner_radius=10)
                self._recalculate_geometry()
            else:
                # Full HUD Mode (Expanded)
                if hasattr(self, "bubble_frame") and self.bubble_frame.winfo_manager() == "pack":
                    self.bubble_frame.pack_forget()
                if hasattr(self, "top_bar") and self.top_bar.winfo_manager() != "pack":
                    self.top_bar.pack(fill="x", padx=10, pady=(8, 4))
                if hasattr(self, "content_frame") and self.content_frame.winfo_manager() != "pack":
                    self.content_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))

                self.main_frame.configure(corner_radius=14)
                self._recalculate_geometry()
        except Exception:
            pass

    def apply_opacity(self):
        try:
            opacity = float(config.get("mini_hud_opacity") if config.get("mini_hud_opacity") is not None else 1.0)
            self.attributes("-alpha", max(0.2, min(1.0, opacity)))
        except Exception:
            pass

    def _hide_from_taskbar(self):
        """Borderless overrideredirect(True) windows are natively excluded from taskbar on Windows."""
        pass

    def _bind_drag(self, widget):
        for sub in [widget, getattr(widget, "_canvas", None), getattr(widget, "_label", None), getattr(widget, "_text_label", None)]:
            if sub is not None and hasattr(sub, "bind"):
                try:
                    sub.bind("<ButtonPress-1>", self._start_drag, add="+")
                    sub.bind("<B1-Motion>", self._do_drag, add="+")
                    sub.bind("<ButtonRelease-1>", self._end_drag, add="+")
                    sub.bind("<Button-3>", self._show_context_menu, add="+")
                    sub.bind("<Button-2>", self._show_context_menu, add="+")
                    sub.bind("<ButtonRelease-3>", self._show_context_menu, add="+")
                except Exception:
                    pass

    def _start_drag(self, event):
        self._hide_tooltip()
        self._dismiss_context_menu()
        self._press_x = event.x_root
        self._press_y = event.y_root
        self._offset_x = event.x_root - self.winfo_x()
        self._offset_y = event.y_root - self.winfo_y()
        self._is_dragging = False

    def _do_drag(self, event):
        dx = abs(event.x_root - self._press_x)
        dy = abs(event.y_root - self._press_y)
        if dx > 4 or dy > 4:
            self._is_dragging = True
            self._hide_tooltip()
        x = event.x_root - self._offset_x
        y = event.y_root - self._offset_y
        scale = self._get_scale()
        if self.is_minimized and not self.is_hover_expanded:
            cur_w, cur_h = self._get_bubble_dimensions()
            self._bubble_pos = (x, y)
            target_geo = f"{cur_w}x{cur_h}+{x}+{y}"
            self._last_applied_geometry = target_geo
            self.geometry(target_geo)
        else:
            cur_w = 350
            needed_h = max(10, int(round((self.main_frame.winfo_reqheight() + 4) / scale)))
            self._hud_pos = (x, y)
            target_geo = f"{cur_w}x{needed_h}+{x}+{y}"
            self._last_applied_geometry = target_geo
            self.geometry(target_geo)

    def _end_drag(self, event):
        if self._is_dragging:
            self._save_position()
            self._is_dragging = False
        else:
            if self.is_minimized and not self.is_hover_expanded:
                self._expand_on_click()

    def _save_position(self):
        try:
            if not self.winfo_exists():
                return
            bx, by = self.winfo_x(), self.winfo_y()
            if self.is_minimized and not self.is_hover_expanded:
                self._bubble_pos = (bx, by)
                geo = f"{'+' if bx >= 0 else ''}{bx}{'+' if by >= 0 else ''}{by}"
                config.set("mini_hud_bubble_geometry", geo, save_now=False)
            else:
                self._hud_pos = (bx, by)
                geo = f"{'+' if bx >= 0 else ''}{bx}{'+' if by >= 0 else ''}{by}"
                config.set("mini_hud_geometry", geo, save_now=False)
        except Exception:
            pass

    def _restore_position(self):
        self._recalculate_geometry()

    def _restore_dashboard(self):
        if self.on_restore_callback:
            self.on_restore_callback()

    def _set_opacity(self, value: float):
        """Sets and persists the Mini-HUD window opacity."""
        try:
            config.set("mini_hud_opacity", float(value), save_now=True)
            self.apply_opacity()
        except Exception:
            pass

    def _show_context_menu(self, event=None):
        """Displays a modern CustomTkinter popup context menu with quick actions for the Mini-HUD / Bubble."""
        self._hide_tooltip()
        import time
        now = time.time()
        if now - getattr(self, "_last_context_menu_time", 0.0) < 0.25:
            return
        self._last_context_menu_time = now

        try:
            # Dismiss any currently open context menu
            if hasattr(self, "_context_menu_win") and self._context_menu_win and self._context_menu_win.winfo_exists():
                try:
                    self._context_menu_win.destroy()
                except Exception:
                    pass
                self._context_menu_win = None

            if event is not None and hasattr(event, "x_root") and event.x_root:
                px = event.x_root
                py = event.y_root
            else:
                px = self.winfo_pointerx()
                py = self.winfo_pointery()

            self._context_menu_win = MiniHUDContextMenu(self, px, py)
        except Exception:
            pass

    def _toggle_pin(self):
        self.is_pinned = not self.is_pinned
        self.attributes("-topmost", self.is_pinned)
        config.set("hud_always_on_top", self.is_pinned, save_now=True)
        self.pin_btn.configure(
            fg_color="#3B82F6" if self.is_pinned else ("#e2e8f0", "#283042"),
            hover_color=("#2563eb", "#1d4ed8") if self.is_pinned else ("#cbd5e1", "#374151"),
            text_color="#ffffff" if self.is_pinned else ("#0f172a", "#f8fafc")
        )

    def _toggle_7d_view(self):
        self.show_7d_expanded = not self.show_7d_expanded
        config.set("hud_show_7d_expanded", self.show_7d_expanded, save_now=True)
        self.toggle_7d_btn.configure(
            fg_color="#8B5CF6" if self.show_7d_expanded else ("#e2e8f0", "#283042"),
            hover_color=("#7c3aed", "#6d28d9") if self.show_7d_expanded else ("#cbd5e1", "#374151"),
            text_color="#ffffff" if self.show_7d_expanded else ("#0f172a", "#f8fafc")
        )
        self._build_sections()
        self._recalculate_hud_view()

    def _recalculate_hud_view(self):
        """Recalculates 5H and 7D window data for both Active Session and All Sessions for the selected account."""
        try:
            from core.account_manager import get_active_google_account
            from core.ledger import ledger
            active_email = get_active_google_account() or "Default"
            active_sid = None
            if hasattr(self.master, "watcher") and self.master.watcher.latest_sessions:
                active_sid = self.master.watcher.latest_sessions[0].get("session_id")
            
            # Resolve target account from master dashboard selection
            target_acc = "all"
            if hasattr(self.master, "is_all_mode") and self.master.is_all_mode:
                target_acc = "all"
            elif getattr(self.master, "is_tracking_active_account", False):
                target_acc = active_email
            elif hasattr(self.master, "selected_account_filter") and self.master.selected_account_filter:
                target_acc = self.master.selected_account_filter
            else:
                target_acc = active_email

            # 1. Report for All Sessions
            hud_report_all = ledger.get_filtered_report(
                account_email=target_acc,
                active_only=False,
                active_only_5h=False,
                active_only_7d=False,
                active_session_id=active_sid
            )

            # 2. Report for Active Session
            hud_report_active = ledger.get_filtered_report(
                account_email=target_acc,
                active_only=True,
                active_only_5h=True,
                active_only_7d=True,
                active_session_id=active_sid
            )

            self.update_data(report=hud_report_all, session_report=hud_report_active)
        except Exception:
            pass

    def _clamp_to_screen(self, x: int, y: int, width: int, height: int) -> Tuple[int, int]:
        """Provides safety bounds while allowing windows to be freely positioned near or past screen edges."""
        try:
            scale = self._get_scale()
            phys_w = int(round(width * scale))
            phys_h = int(round(height * scale))
            wl, wt, wr, wb = get_screen_work_area(self)
            # Allow dragging partially off-screen while keeping at least 24px grab margin visible
            min_x = wl - phys_w + 24
            max_x = wr - 24
            min_y = wt - phys_h + 24
            max_y = wb - 24
            return max(min_x, min(x, max_x)), max(min_y, min(y, max_y))
        except Exception:
            return x, y

    def _recalculate_geometry(self, pos_str: Optional[str] = None):
        """Calculates exact required height to eliminate any bottom gap and positions the HUD safely on screen."""
        self.update_idletasks()
        scale = self._get_scale()
        if self.is_minimized and not self.is_hover_expanded:
            cur_w, needed_h = self._get_bubble_dimensions()
        else:
            cur_w = 350
            needed_h = max(10, int(round((self.main_frame.winfo_reqheight() + 4) / scale)))

        try:
            target_x = None
            target_y = None
            if pos_str:
                import re
                m = re.search(r"([+-]?\d+)([+-]\d+)$", str(pos_str))
                if m:
                    target_x = int(m.group(1))
                    target_y = int(m.group(2))
            elif self.is_minimized and not self.is_hover_expanded:
                if self._bubble_pos:
                    target_x, target_y = self._bubble_pos
                else:
                    saved_b = config.get("mini_hud_bubble_geometry") or ""
                    if saved_b:
                        import re
                        m = re.search(r"([+-]?\d+)([+-]\d+)$", str(saved_b))
                        if m:
                            target_x = int(m.group(1))
                            target_y = int(m.group(2))
            else:
                if self._hud_pos:
                    target_x, target_y = self._hud_pos
                else:
                    saved_h = config.get("mini_hud_geometry") or ""
                    if saved_h:
                        import re
                        m = re.search(r"([+-]?\d+)([+-]\d+)$", str(saved_h))
                        if m:
                            target_x = int(m.group(1))
                            target_y = int(m.group(2))

            if target_x is not None and target_y is not None:
                cx, cy = self._clamp_to_screen(target_x, target_y, cur_w, needed_h)
                if self.is_minimized and not self.is_hover_expanded:
                    self._bubble_pos = (cx, cy)
                else:
                    self._hud_pos = (cx, cy)
                target_geo = f"{cur_w}x{needed_h}+{cx}+{cy}"
                if getattr(self, "_last_applied_geometry", None) != target_geo:
                    self._last_applied_geometry = target_geo
                    self.geometry(target_geo)
            else:
                self._place_default(needed_h)
        except Exception:
            self._place_default(needed_h)

    def _place_default(self, needed_h: Optional[int] = None):
        self.update_idletasks()
        scale = self._get_scale()
        if self.is_minimized and not self.is_hover_expanded:
            bw, bh = self._get_bubble_dimensions()
            cur_w = bw
            if needed_h is None:
                needed_h = bh
        else:
            cur_w = 350
            if needed_h is None:
                needed_h = max(10, int(round((self.main_frame.winfo_reqheight() + 4) / scale)))
        
        phys_w = int(round(cur_w * scale))
        phys_h = int(round(needed_h * scale))
        wl, wt, wr, wb = get_screen_work_area(self)
        # Flush snug corner placement without artificial gaps (4px inset from outer border and taskbar)
        x = max(wl, wr - phys_w - 4)
        y = max(wt, wb - phys_h - 4)
        if self.is_minimized and not self.is_hover_expanded:
            self._bubble_pos = (x, y)
        else:
            self._hud_pos = (x, y)
        target_geo = f"{cur_w}x{needed_h}+{x}+{y}"
        if getattr(self, "_last_applied_geometry", None) != target_geo:
            self._last_applied_geometry = target_geo
            self.geometry(target_geo)

    def _build_sections(self):
        for child in self.content_frame.winfo_children():
            child.destroy()

        # ---------------- 1. 5-HOUR SECTION (Primary) ----------------
        self.card_5h = ctk.CTkFrame(
            self.content_frame,
            corner_radius=8,
            fg_color=("#f8fafc", "#1a202c"),
            border_width=1,
            border_color=("#e2e8f0", "#2d3748")
        )
        self.card_5h.pack(fill="x", pady=(2, 4))
        self._bind_drag(self.card_5h)

        # 5h Header
        h5_row = ctk.CTkFrame(self.card_5h, fg_color="transparent")
        h5_row.pack(fill="x", padx=8, pady=(6, 2))
        self._bind_drag(h5_row)

        self.h5_title = ctk.CTkLabel(
            h5_row,
            text="⏳ 5-Hour Burn",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#0f172a", "#f8fafc")
        )
        self.h5_title.pack(side="left")
        self._bind_drag(self.h5_title)

        self.h5_badge = ctk.CTkLabel(
            h5_row,
            text="0% used",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#15803d",
            corner_radius=5,
            fg_color=("#dcfce7", "#162520"),
            padx=6,
            pady=1
        )
        self.h5_badge.pack(side="right")

        self.reset_5h_lbl = ctk.CTkLabel(
            h5_row,
            text="🔄 in 0h 00m",
            font=ctk.CTkFont(size=11),
            text_color=("#475569", "#94a3b8")
        )
        self.reset_5h_lbl.pack(side="right", padx=(0, 6))
        self._bind_drag(self.reset_5h_lbl)

        # 5h Line 1: Active Session Stats
        self.h5_active_lbl = ctk.CTkLabel(
            self.card_5h,
            text="⚡ Active: 0 tok",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#1d4ed8", "#60a5fa")
        )
        self.h5_active_lbl.pack(anchor="w", padx=8, pady=(1, 0))
        self._bind_drag(self.h5_active_lbl)

        # 5h Line 1 Breakdown
        self.h5_active_breakdown_lbl = ctk.CTkLabel(
            self.card_5h,
            text="📥 0 • 🧠 0 • 📤 0",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#3b82f6", "#93c5fd")
        )
        self.h5_active_breakdown_lbl.pack(anchor="w", padx=26, pady=(0, 2))
        self._bind_drag(self.h5_active_breakdown_lbl)

        # 5h Line 2: All Sessions Stats
        self.h5_all_lbl = ctk.CTkLabel(
            self.card_5h,
            text="★ All:    0 tok",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#475569", "#94a3b8")
        )
        self.h5_all_lbl.pack(anchor="w", padx=8, pady=(1, 0))
        self._bind_drag(self.h5_all_lbl)

        # 5h Line 2 Breakdown
        self.h5_all_breakdown_lbl = ctk.CTkLabel(
            self.card_5h,
            text="📥 0 • 🧠 0 • 📤 0",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#475569", "#94a3b8")
        )
        self.h5_all_breakdown_lbl.pack(anchor="w", padx=26, pady=(0, 4))
        self._bind_drag(self.h5_all_breakdown_lbl)

        # 5h Progress Bar
        self.prog_5h = ctk.CTkProgressBar(
            self.card_5h,
            height=5,
            corner_radius=3,
            progress_color="#10b981",
            fg_color=("#e2e8f0", "#283042")
        )
        self.prog_5h.pack(fill="x", padx=8, pady=(0, 6))
        self.prog_5h.set(0.0)

        # ---------------- 2. 7-DAY SECTION (Toggleable) ----------------
        if self.show_7d_expanded:
            self.card_7d = ctk.CTkFrame(
                self.content_frame,
                corner_radius=8,
                fg_color=("#f8fafc", "#1a202c"),
                border_width=1,
                border_color=("#e2e8f0", "#2d3748")
            )
            self.card_7d.pack(fill="x", pady=(2, 4))
            self._bind_drag(self.card_7d)

            # 7d Header
            h7_row = ctk.CTkFrame(self.card_7d, fg_color="transparent")
            h7_row.pack(fill="x", padx=8, pady=(6, 2))
            self._bind_drag(h7_row)

            self.h7_title = ctk.CTkLabel(
                h7_row,
                text="📅 7-Day Weekly",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=("#0f172a", "#f8fafc")
            )
            self.h7_title.pack(side="left")
            self._bind_drag(self.h7_title)

            self.h7_badge = ctk.CTkLabel(
                h7_row,
                text="0% used",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#15803d",
                corner_radius=5,
                fg_color=("#dcfce7", "#162520"),
                padx=6,
                pady=1
            )
            self.h7_badge.pack(side="right")

            self.reset_7d_lbl = ctk.CTkLabel(
                h7_row,
                text="🔄 in 0d 00h",
                font=ctk.CTkFont(size=11),
                text_color=("#475569", "#94a3b8")
            )
            self.reset_7d_lbl.pack(side="right", padx=(0, 6))
            self._bind_drag(self.reset_7d_lbl)

            # 7d Line 1: Active Session Stats
            self.h7_active_lbl = ctk.CTkLabel(
                self.card_7d,
                text="⚡ Active: 0 tok",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=("#7c3aed", "#c084fc")
            )
            self.h7_active_lbl.pack(anchor="w", padx=8, pady=(1, 0))
            self._bind_drag(self.h7_active_lbl)

            # 7d Line 1 Breakdown
            self.h7_active_breakdown_lbl = ctk.CTkLabel(
                self.card_7d,
                text="📥 0 • 🧠 0 • 📤 0",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=("#9333ea", "#d8b4fe")
            )
            self.h7_active_breakdown_lbl.pack(anchor="w", padx=26, pady=(0, 2))
            self._bind_drag(self.h7_active_breakdown_lbl)

            # 7d Line 2: All Sessions Stats
            self.h7_all_lbl = ctk.CTkLabel(
                self.card_7d,
                text="★ All:    0 tok",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=("#475569", "#94a3b8")
            )
            self.h7_all_lbl.pack(anchor="w", padx=8, pady=(1, 0))
            self._bind_drag(self.h7_all_lbl)

            # 7d Line 2 Breakdown
            self.h7_all_breakdown_lbl = ctk.CTkLabel(
                self.card_7d,
                text="📥 0 • 🧠 0 • 📤 0",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=("#475569", "#94a3b8")
            )
            self.h7_all_breakdown_lbl.pack(anchor="w", padx=26, pady=(0, 4))
            self._bind_drag(self.h7_all_breakdown_lbl)

            # 7d Progress Bar
            self.prog_7d = ctk.CTkProgressBar(
                self.card_7d,
                height=5,
                corner_radius=3,
                progress_color="#10B981",
                fg_color=("#e2e8f0", "#283042")
            )
            self.prog_7d.pack(fill="x", padx=8, pady=(0, 6))
            self.prog_7d.set(0.0)

        # ---------------- 3. ACCOUNT SELECTOR ROW (Bottom) ----------------
        if config.get("hud_show_session", True):
            self.active_row = ctk.CTkFrame(self.content_frame, fg_color="transparent")
            self.active_row.pack(fill="x", padx=4, pady=(2, 0))
            self._bind_drag(self.active_row)

            self.account_lbl = ctk.CTkLabel(
                self.active_row,
                text="👤 Account:",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=("#475569", "#94a3b8")
            )
            self.account_lbl.pack(side="left", padx=(4, 6))
            self._bind_drag(self.account_lbl)

            self.account_menu = ctk.CTkOptionMenu(
                self.active_row,
                values=["All"],
                command=self._on_hud_account_selected,
                height=22,
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color=("#dbeafe", "#1e3a5f"),
                text_color=("#1d4ed8", "#93c5fd"),
                button_color=("#bfdbfe", "#2563eb"),
                button_hover_color=("#93c5fd", "#1d4ed8"),
                corner_radius=5
            )
            self.account_menu.pack(side="left", fill="x", expand=True, padx=(0, 4))
            self._update_account_dropdown()

        # Recursively bind right-click context menu across all content cards and child widgets
        self._bind_context_menu_recursive(self.content_frame)

        # Update geometry with exact snug height (zero bottom gap)
        self._recalculate_geometry()

    def update_data(self, report: Dict[str, Any], session_report: Optional[Dict[str, Any]] = None):
        if not report:
            return

        self.last_report = report
        self.last_session_report = session_report
        self.apply_opacity()

        all_rep = report
        act_rep = session_report if session_report is not None else report

        show_manual = bool(config.get("show_manual_limits"))
        limit_5h = max(1, int(config.get("limit_5h") or 1000000))
        limit_7d = max(1, int(config.get("limit_7d") or 4000000))

        def _fmt(val: int) -> str:
            if val >= 1000000:
                return f"{val/1000000:.2f}M"
            return f"{val:,}"

        def _fmt_bubble(val: int) -> str:
            if val >= 1000000:
                return f"{val/1000000:.2f}M"
            return f"{val:,}"

        # 1. Update 5h Section
        if hasattr(self, "card_5h"):
            used_5h_all = all_rep.get("tokens_5h", 0)
            think_5h_all = all_rep.get("thinking_5h", 0)
            prompt_5h_all = all_rep.get("prompt_5h", 0)
            cand_5h_all = all_rep.get("candidates_5h", 0)

            used_5h_act = act_rep.get("tokens_5h", 0)
            think_5h_act = act_rep.get("thinking_5h", 0)
            prompt_5h_act = act_rep.get("prompt_5h", 0)
            cand_5h_act = act_rep.get("candidates_5h", 0)

            pct_5h_rem = float(all_rep.get("pct_5h_remaining", 0.0))
            reset_5h = all_rep.get("reset_5h_str", "Reset")
            is_rt = all_rep.get("is_realtime_quota", False)

            if hasattr(self, "h5_active_lbl"):
                self.h5_active_lbl.configure(text=f"⚡ Active: {used_5h_act:,} tok")
            if hasattr(self, "h5_active_breakdown_lbl"):
                self.h5_active_breakdown_lbl.configure(text=f"📥 {_fmt(prompt_5h_act)} • 🧠 {_fmt(think_5h_act)} • 📤 {_fmt(cand_5h_act)}")
                
            if hasattr(self, "h5_all_lbl"):
                self.h5_all_lbl.configure(text=f"★ All:    {used_5h_all:,} tok")
            if hasattr(self, "h5_all_breakdown_lbl"):
                self.h5_all_breakdown_lbl.configure(text=f"📥 {_fmt(prompt_5h_all)} • 🧠 {_fmt(think_5h_all)} • 📤 {_fmt(cand_5h_all)}")

            short_reset_5h = reset_5h.split("(")[0].strip() if "(" in reset_5h else reset_5h
            if show_manual and pct_5h_rem > 0:
                self.reset_5h_lbl.configure(text=f"🔄 {short_reset_5h} ({pct_5h_rem:.1f}% rem)")
            else:
                self.reset_5h_lbl.configure(text=f"🔄 {short_reset_5h}")

            if show_manual:
                pct_5h = (used_5h_all / limit_5h) * 100
                ratio_5h = min(1.0, max(0.0, used_5h_all / limit_5h))
                if pct_5h < 60.0:
                    bar_col, b_bg, b_txt = "#10B981", ("#dcfce7", "#162520"), ("#15803d", "#10B981")
                elif pct_5h < 85.0:
                    bar_col, b_bg, b_txt = "#F59E0B", ("#fef3c7", "#2d2315"), ("#b45309", "#F59E0B")
                else:
                    bar_col, b_bg, b_txt = "#EF4444", ("#fee2e2", "#2d1515"), ("#b91c1c", "#EF4444")
                self.h5_badge.configure(text=f"{pct_5h:.1f}% used", fg_color=b_bg, text_color=b_txt)
                self.prog_5h.configure(progress_color=bar_col)
                self.prog_5h.set(ratio_5h)
            else:
                ratio_5h = min(1.0, max(0.0, pct_5h_rem / 100.0))
                if pct_5h_rem >= 60.0 or pct_5h_rem == 0.0:
                    bar_col, b_bg, b_txt = "#10B981", ("#dcfce7", "#162520"), ("#15803d", "#10B981")
                elif pct_5h_rem >= 20.0:
                    bar_col, b_bg, b_txt = "#F59E0B", ("#fef3c7", "#2d2315"), ("#b45309", "#F59E0B")
                else:
                    bar_col, b_bg, b_txt = "#EF4444", ("#fee2e2", "#2d1515"), ("#b91c1c", "#EF4444")
                badge_text = f"{pct_5h_rem:.1f}% rem" if pct_5h_rem > 0 else ("100% rem" if is_rt else "Reset")
                self.h5_badge.configure(text=badge_text, fg_color=b_bg, text_color=b_txt)
                self.prog_5h.configure(progress_color=bar_col)
                self.prog_5h.set(ratio_5h)

            if hasattr(self, "h5_all_lbl"):
                self.h5_all_lbl.configure(text_color=b_txt)

        # 2. Update 7d Section (if expanded)
        if self.show_7d_expanded and hasattr(self, "card_7d"):
            used_7d_all = all_rep.get("tokens_7d", 0)
            think_7d_all = all_rep.get("thinking_7d", 0)
            prompt_7d_all = all_rep.get("prompt_7d", 0)
            cand_7d_all = all_rep.get("candidates_7d", 0)

            used_7d_act = act_rep.get("tokens_7d", 0)
            think_7d_act = act_rep.get("thinking_7d", 0)
            prompt_7d_act = act_rep.get("prompt_7d", 0)
            cand_7d_act = act_rep.get("candidates_7d", 0)

            pct_7d_rem = float(all_rep.get("pct_7d_remaining", 0.0))
            reset_7d = all_rep.get("reset_7d_str", "Reset")

            if hasattr(self, "h7_active_lbl"):
                self.h7_active_lbl.configure(text=f"⚡ Active: {used_7d_act:,} tok")
            if hasattr(self, "h7_active_breakdown_lbl"):
                self.h7_active_breakdown_lbl.configure(text=f"📥 {_fmt(prompt_7d_act)} • 🧠 {_fmt(think_7d_act)} • 📤 {_fmt(cand_7d_act)}")
                
            if hasattr(self, "h7_all_lbl"):
                self.h7_all_lbl.configure(text=f"★ All:    {used_7d_all:,} tok")
            if hasattr(self, "h7_all_breakdown_lbl"):
                self.h7_all_breakdown_lbl.configure(text=f"📥 {_fmt(prompt_7d_all)} • 🧠 {_fmt(think_7d_all)} • 📤 {_fmt(cand_7d_all)}")

            short_reset_7d = reset_7d.split("(")[0].strip() if "(" in reset_7d else reset_7d
            if show_manual and pct_7d_rem > 0:
                self.reset_7d_lbl.configure(text=f"🔄 {short_reset_7d} ({pct_7d_rem:.1f}% rem)")
            else:
                self.reset_7d_lbl.configure(text=f"🔄 {short_reset_7d}")

            if show_manual:
                pct_7d = (used_7d_all / limit_7d) * 100
                ratio_7d = min(1.0, max(0.0, used_7d_all / limit_7d))
                if pct_7d < 60.0:
                    bar_col, b_bg, b_txt = "#10B981", ("#dcfce7", "#162520"), ("#15803d", "#10B981")
                elif pct_7d < 85.0:
                    bar_col, b_bg, b_txt = "#F59E0B", ("#fef3c7", "#2d2315"), ("#b45309", "#F59E0B")
                else:
                    bar_col, b_bg, b_txt = "#EF4444", ("#fee2e2", "#2d1515"), ("#b91c1c", "#EF4444")
                self.h7_badge.configure(text=f"{pct_7d:.1f}% used", fg_color=b_bg, text_color=b_txt)
                self.prog_7d.configure(progress_color=bar_col)
                self.prog_7d.set(ratio_7d)
            else:
                ratio_7d = min(1.0, max(0.0, pct_7d_rem / 100.0))
                if pct_7d_rem >= 60.0 or pct_7d_rem == 0.0:
                    bar_col, b_bg, b_txt = "#10B981", ("#dcfce7", "#162520"), ("#15803d", "#10B981")
                elif pct_7d_rem >= 20.0:
                    bar_col, b_bg, b_txt = "#F59E0B", ("#fef3c7", "#2d2315"), ("#b45309", "#F59E0B")
                else:
                    bar_col, b_bg, b_txt = "#EF4444", ("#fee2e2", "#2d1515"), ("#b91c1c", "#EF4444")
                badge_text_7d = f"{pct_7d_rem:.1f}% rem" if pct_7d_rem > 0 else ("100% rem" if is_rt else "Reset")
                self.h7_badge.configure(text=badge_text_7d, fg_color=b_bg, text_color=b_txt)
                self.prog_7d.configure(progress_color=bar_col)
                self.prog_7d.set(ratio_7d)

            if hasattr(self, "h7_all_lbl"):
                self.h7_all_lbl.configure(text_color=b_txt)

        # 3. Update Floating Bubble Token Numbers & Remaining Quota %
        if hasattr(self, "bubble_5h_act_lbl"):
            used_5h_all_b = all_rep.get("tokens_5h", 0)
            used_5h_act_b = act_rep.get("tokens_5h", 0)
            used_7d_all_b = all_rep.get("tokens_7d", 0)
            used_7d_act_b = act_rep.get("tokens_7d", 0)
            pct_5h_rem = float(all_rep.get("pct_5h_remaining", 0.0))
            pct_7d_rem = float(all_rep.get("pct_7d_remaining", 0.0))
            is_rt = all_rep.get("is_realtime_quota", False)

            p5_txt = f"{pct_5h_rem:.0f}%" if pct_5h_rem > 0 else ("100%" if is_rt else "0%")
            if pct_5h_rem >= 60.0 or (pct_5h_rem == 0.0 and is_rt):
                c5 = ("#059669", "#34d399")
            elif pct_5h_rem >= 20.0:
                c5 = ("#d97706", "#fbbf24")
            else:
                c5 = ("#dc2626", "#f87171")

            self.bubble_5h_act_lbl.configure(text=f"{_fmt_bubble(used_5h_act_b)}", text_color=("#1d4ed8", "#60a5fa"))
            self.bubble_5h_all_lbl.configure(text=f"{_fmt_bubble(used_5h_all_b)}", text_color=c5)
            if hasattr(self, "bubble_5h_pct_lbl"):
                self.bubble_5h_pct_lbl.configure(text=p5_txt, text_color=c5)

            p7_txt = f"{pct_7d_rem:.0f}%" if pct_7d_rem > 0 else ("100%" if is_rt else "0%")
            if pct_7d_rem >= 60.0 or (pct_7d_rem == 0.0 and is_rt):
                c7 = ("#059669", "#34d399")
            elif pct_7d_rem >= 20.0:
                c7 = ("#d97706", "#fbbf24")
            else:
                c7 = ("#dc2626", "#f87171")

            self.bubble_7d_act_lbl.configure(text=f"{_fmt_bubble(used_7d_act_b)}", text_color=("#7c3aed", "#c084fc"))
            self.bubble_7d_all_lbl.configure(text=f"{_fmt_bubble(used_7d_all_b)}", text_color=c7)
            if hasattr(self, "bubble_7d_pct_lbl"):
                self.bubble_7d_pct_lbl.configure(text=p7_txt, text_color=c7)

        # 4. Update Interactive Account Dropdown Selector
        self._update_account_dropdown()

    def _on_hud_account_selected(self, selected_label: str):
        """Synchronizes account selection from Mini HUD with master dashboard and ledger."""
        if hasattr(self.master, "_on_main_account_selected"):
            self.master._on_main_account_selected(selected_label)
        else:
            self._recalculate_hud_view()

    def _update_account_dropdown(self):
        """Updates the interactive account dropdown menu options and selected value in Mini HUD."""
        if not hasattr(self, "account_menu"):
            return
        from core.account_manager import get_active_google_account, get_all_known_accounts_list
        active_email = get_active_google_account()
        known_accounts = get_all_known_accounts_list()

        all_label = "All"
        user_clean = active_email.split('@')[0] if active_email else "User"
        active_label = f"👤 {user_clean}"

        self.account_map = {all_label: "all"}
        menu_values = [all_label]

        if active_email and active_email not in ("Default", "Local", "Default / Local Account"):
            menu_values.append(active_label)
            self.account_map[active_label] = active_email

        for acc in known_accounts:
            if acc != active_email and acc not in ("Default", "Local", "Default / Local Account"):
                acc_clean = acc.split('@')[0] if '@' in acc else acc
                lbl = f"👤 {acc_clean}"
                if lbl in self.account_map:
                    lbl = f"👤 {acc}"
                if lbl not in menu_values:
                    menu_values.append(lbl)
                    self.account_map[lbl] = acc

        if getattr(self, "_last_hud_account_menu_values", None) != menu_values:
            self._last_hud_account_menu_values = list(menu_values)
            self.account_menu.configure(values=menu_values)

        selected_filter = getattr(self.master, "selected_account_filter", None) if self.master else config.get("selected_account")
        is_all = getattr(self.master, "is_all_mode", False) if self.master else (selected_filter == "all")
        is_tracking = getattr(self.master, "is_tracking_active_account", False) if self.master else (selected_filter in ("active", "active user", "👤 active user"))

        if is_all or selected_filter in ("all", "all accounts", "", None):
            target_label = all_label
        elif is_tracking and active_email:
            target_label = active_label
        else:
            target_label = None
            for lbl, acc in self.account_map.items():
                if acc.lower() == str(selected_filter).lower():
                    target_label = lbl
                    break
            if not target_label:
                acc_clean = str(selected_filter).split('@')[0] if '@' in str(selected_filter) else str(selected_filter)
                target_label = next((m for m in menu_values if acc_clean.lower() in m.lower()), all_label)

        if self.account_menu.get() != target_label:
            self.account_menu.set(target_label)

    def destroy(self):
        """Cancels all active background timers and cleanly tears down tooltip and context menu windows."""
        self._hide_tooltip()
        self._dismiss_context_menu()
        for timer_attr in ("_hover_collapse_timer", "_focus_collapse_timer", "_tooltip_timer", "_tooltip_leave_timer"):
            tid = getattr(self, timer_attr, None)
            if tid:
                try:
                    self.after_cancel(tid)
                except Exception:
                    pass
                setattr(self, timer_attr, None)
        super().destroy()
