import tkinter as tk
import customtkinter as ctk
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Callable, Any

from core.analytics import bucket_records_by_time, calculate_analytics_summary


class UsageChart(ctk.CTkFrame):
    """
    An interactive vector canvas chart displaying token consumption over time
    (Rolling 5H, Hourly 24H, Daily 7D, Daily 30D, Monthly 12M, Yearly, or Session Timeline).
    Features stacked bar visualization, theme awareness, smooth resizing, and hover tooltips.
    """

    def __init__(
        self,
        master,
        on_expand_callback: Optional[Callable[[], None]] = None,
        on_account_changed: Optional[Callable[[str], None]] = None,
        on_timeframe_changed: Optional[Callable[[str], None]] = None,
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
        self.on_expand_callback = on_expand_callback
        self.on_account_changed = on_account_changed
        self.on_timeframe_changed = on_timeframe_changed

        # State (Default to 5H rolling window & Current Active User for blazing fast performance)
        self.timeframe: str = "5h"
        self.records: List[Tuple[Optional[datetime], int, int, int]] = []
        self.buckets: List[Dict[str, Any]] = []
        self.summary: Dict[str, Any] = {}
        self.hovered_bucket_idx: Optional[int] = None
        self.chart_type: str = "stacked"  # "stacked" or "grouped"
        self.selected_account: str = "active"

        # Colors
        self.color_prompt = "#3B82F6"      # Blue
        self.color_thinking = "#8B5CF6"    # Purple
        self.color_candidates = "#10B981"  # Emerald Green
        self.color_grid = ("#e2e8f0", "#2a3040")
        self.color_text = ("#64748b", "#94a3b8")

        # 1. Header Toolbar Frame
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=14, pady=(10, 4))

        # Left Header (Title & Summary Badge)
        left_hdr = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        left_hdr.pack(side="left")

        self.title_label = ctk.CTkLabel(
            left_hdr,
            text="📊 Usage Graph & Timeline",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#0f172a", "#f8fafc")
        )
        self.title_label.pack(side="left", padx=(0, 8))

        self.total_badge = ctk.CTkLabel(
            left_hdr,
            text="0 tokens",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#1d4ed8", "#93c5fd"),
            corner_radius=6,
            fg_color=("#dbeafe", "#1e3a5f"),
            padx=8,
            pady=2
        )
        self.total_badge.pack(side="left", padx=(0, 8))

        # Right Header (Timeframe Buttons & Action)
        right_hdr = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        right_hdr.pack(side="right")

        self.timeframe_seg = ctk.CTkSegmentedButton(
            right_hdr,
            values=["5H", "24H", "7D", "30D", "Month", "Year", "Session"],
            command=self._on_timeframe_changed,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            selected_color="#3B82F6",
            selected_hover_color="#2563EB"
        )
        self.timeframe_seg.set("5H")
        self.timeframe_seg.pack(side="left", padx=(0, 6))

        if self.on_expand_callback:
            self.expand_btn = ctk.CTkButton(
                right_hdr,
                text="⛶ Details",
                width=65,
                height=26,
                corner_radius=6,
                fg_color=("#e2e8f0", "#283042"),
                hover_color=("#cbd5e1", "#3B82F6"),
                text_color=("#0f172a", "#f8fafc"),
                font=ctk.CTkFont(size=11, weight="bold"),
                command=self.on_expand_callback
            )
            self.expand_btn.pack(side="left")

        # 2. Main Canvas Container (Height 160 for clear X-axis hour and date labels)
        self.canvas_height = 160
        self.canvas = tk.Canvas(
            self,
            height=self.canvas_height,
            bg="#ffffff" if ctk.get_appearance_mode().lower() == "light" else "#1e222d",
            highlightthickness=0,
            bd=0
        )
        self.canvas.pack(fill="x", expand=True, padx=14, pady=(4, 6))

        # Canvas Event bindings
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<Leave>", self._on_canvas_leave)

        # 3. Legend & Info Footer Frame
        self.legend_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.legend_frame.pack(fill="x", padx=14, pady=(0, 8))

        self.prompt_leg = self._create_legend_item(self.legend_frame, "● Prompt (In)", self.color_prompt)
        self.prompt_leg.pack(side="left", padx=(0, 12))

        self.think_leg = self._create_legend_item(self.legend_frame, "● Thinking", self.color_thinking)
        self.think_leg.pack(side="left", padx=(0, 12))

        self.cand_leg = self._create_legend_item(self.legend_frame, "■ Output", self.color_candidates)
        self.cand_leg.pack(side="left", padx=(0, 12))

        self.active_leg = self._create_legend_item(self.legend_frame, "● Active Session", "#38bdf8")
        self.active_leg.pack(side="left", padx=(0, 12))

        self.peak_lbl = ctk.CTkLabel(
            self.legend_frame,
            text="⚡ Peak: Idle",
            font=ctk.CTkFont(size=11),
            text_color=("#475569", "#94a3b8")
        )
        self.peak_lbl.pack(side="right")

        # Internal geometry cache for hit-testing: list of (x0, x1, bucket_dict)
        self._bar_hitboxes: List[Tuple[float, float, Dict[str, Any]]] = []

    def _create_legend_item(self, parent, text: str, color: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent,
            text=text,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=color
        )

    def _on_timeframe_changed(self, value: str):
        val_map = {
            "5H": "5h",
            "24H": "24h",
            "7D": "7d",
            "30D": "30d",
            "Month": "month",
            "Year": "year",
            "Session": "session",
        }
        self.timeframe = val_map.get(value, "5h")
        self._recompute_buckets()
        self._redraw()
        if self.on_timeframe_changed:
            self.on_timeframe_changed(self.timeframe)

    def set_accounts_list(self, accounts: List[str], current_account: Optional[str] = None, is_session_mode: bool = False):
        """Compatibility no-op method since account filtering is elevated to master toolbar."""
        pass

    def set_dual_records(self, active_records, all_records, timeframe=None):
        self.active_records = list(active_records) if active_records else []
        self.records = list(all_records) if all_records else []
        if timeframe:
            self.timeframe = timeframe
            seg_map = {
                "5h": "5H",
                "24h": "24H",
                "7d": "7D",
                "30d": "30D",
                "month": "Month",
                "year": "Year",
                "session": "Session"
            }
            if self.timeframe in seg_map:
                self.timeframe_seg.set(seg_map[self.timeframe])

        self._recompute_buckets()
        self._redraw()

    def set_records(self, records: List[Tuple[Optional[datetime], int, int, int]], timeframe: Optional[str] = None, active_records: Optional[List[Tuple[Optional[datetime], int, int, int]]] = None):
        """Updates the underlying records and refreshes the chart."""
        if active_records is not None:
            self.active_records = list(active_records)
        elif not hasattr(self, 'active_records'):
            self.active_records = []

        if self.records == records and (timeframe is None or timeframe == self.timeframe):
            return

        self.records = list(records) if records else []
        if timeframe:
            self.timeframe = timeframe
            seg_map = {
                "5h": "5H",
                "24h": "24H",
                "7d": "7D",
                "30d": "30D",
                "month": "Month",
                "year": "Year",
                "session": "Session"
            }
            if self.timeframe in seg_map:
                self.timeframe_seg.set(seg_map[self.timeframe])

        self._recompute_buckets()
        self._redraw()

    def _recompute_buckets(self):
        self.buckets = bucket_records_by_time(self.records, timeframe=self.timeframe)
        self.summary = calculate_analytics_summary(self.buckets)
        if hasattr(self, 'active_records'):
            self.active_buckets = bucket_records_by_time(self.active_records, timeframe=self.timeframe)
        else:
            self.active_buckets = []

        tot = self.summary.get("total_tokens", 0)
        p_pct = self.summary.get("prompt_pct", 0.0)
        th_pct = self.summary.get("thinking_pct", 0.0)
        c_pct = self.summary.get("candidates_pct", 0.0)

        # Update badge
        if tot >= 1000000:
            tot_str = f"{tot/1000000:.2f}M tokens"
        elif tot >= 1000:
            tot_str = f"{tot/1000:.1f}K tokens"
        else:
            tot_str = f"{tot:,} tokens"
        self.total_badge.configure(text=f"{tot_str}")

        # Update legend percentages
        self.prompt_leg.configure(text=f"● Prompt: {p_pct:.1f}%")
        self.think_leg.configure(text=f"● Thinking: {th_pct:.1f}%")
        self.cand_leg.configure(text=f"● Output: {c_pct:.1f}%")

        peak_lbl = self.summary.get("peak_label", "Idle")
        peak_tok = self.summary.get("peak_tokens", 0)
        if peak_tok > 0:
            if peak_tok >= 1000000:
                p_str = f"{peak_tok/1000000:.1f}M"
            elif peak_tok >= 1000:
                p_str = f"{peak_tok/1000:.0f}K"
            else:
                p_str = str(peak_tok)
            self.peak_lbl.configure(text=f"⚡ Peak: {peak_lbl} ({p_str} tok)")
        else:
            self.peak_lbl.configure(text="⚡ Peak: Idle")

    def _on_canvas_motion(self, event):
        x, y = event.x, event.y
        new_hover = None
        for idx, (x0, x1, _) in enumerate(self._bar_hitboxes):
            if x0 <= x <= x1:
                new_hover = idx
                break

        if new_hover != self.hovered_bucket_idx:
            self.hovered_bucket_idx = new_hover
            self._redraw(mouse_x=x, mouse_y=y)

    def _on_canvas_leave(self, event):
        if self.hovered_bucket_idx is not None:
            self.hovered_bucket_idx = None
            self._redraw()

    def _redraw(self, mouse_x: Optional[int] = None, mouse_y: Optional[int] = None):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas_height
        if w <= 10 or h <= 10:
            return

        is_dark = ctk.get_appearance_mode().lower() == "dark"
        bg_col = "#1e222d" if is_dark else "#ffffff"
        grid_col = "#2a3040" if is_dark else "#f1f5f9"
        line_col = "#334155" if is_dark else "#cbd5e1"
        text_col = "#94a3b8" if is_dark else "#64748b"

        self.canvas.configure(bg=bg_col)
        self._bar_hitboxes.clear()

        # Layout margins with extra bottom room for hours and dates
        margin_left = 50
        margin_right = 16
        margin_top = 14
        margin_bottom = 32

        plot_w = max(10, w - (margin_left + margin_right))
        plot_h = max(10, h - (margin_top + margin_bottom))

        if not self.buckets:
            self.canvas.create_text(
                w / 2, h / 2,
                text="No usage records for this timeframe",
                fill=text_col,
                font=("Helvetica", 11)
            )
            return

        # Calculate max Y value with headroom
        max_val = max((b.get("total", 0) for b in self.buckets), default=0)
        if max_val <= 0:
            max_val = 1000

        # Round max_val up to clean number
        def _round_up(val: float) -> float:
            if val <= 1000:
                return 1000
            elif val <= 10000:
                return ((val // 2000) + 1) * 2000
            elif val <= 100000:
                return ((val // 20000) + 1) * 20000
            elif val <= 1000000:
                return ((val // 200000) + 1) * 200000
            else:
                return ((val // 1000000) + 1) * 1000000

        y_max = _round_up(max_val * 1.15)

        # Draw Gridlines and Y-axis labels (3 levels)
        for i in range(3):
            ratio = i / 2.0
            y_val = int(y_max * (1.0 - ratio))
            y_pos = margin_top + (ratio * plot_h)

            # Gridline
            self.canvas.create_line(
                margin_left, y_pos,
                margin_left + plot_w, y_pos,
                fill=grid_col, width=1, dash=(2, 4)
            )

            # Label
            if y_val >= 1000000:
                lbl_str = f"{y_val/1000000:.1f}M"
            elif y_val >= 1000:
                lbl_str = f"{y_val/1000:.0f}K"
            else:
                lbl_str = str(y_val)

            self.canvas.create_text(
                margin_left - 8, y_pos,
                text=lbl_str,
                fill=text_col,
                anchor="e",
                font=("Helvetica", 9)
            )

        # Baseline axis line
        base_y = margin_top + plot_h
        self.canvas.create_line(margin_left, base_y, margin_left + plot_w, base_y, fill=line_col, width=1)

        # Draw Bars
        num_buckets = len(self.buckets)
        slot_w = plot_w / num_buckets
        bar_w = max(4.0, min(slot_w * 0.70, 38.0))

        hovered_box_info = None

        for idx, b in enumerate(self.buckets):
            center_x = margin_left + (idx + 0.5) * slot_w
            x0 = center_x - (bar_w / 2)
            x1 = center_x + (bar_w / 2)

            self._bar_hitboxes.append((center_x - slot_w / 2, center_x + slot_w / 2, b))

            p = b.get("prompt", 0)
            th = b.get("thinking", 0)
            c = b.get("candidates", 0)
            tot = p + th + c

            is_hovered = (self.hovered_bucket_idx == idx)

            if tot > 0:
                # Calculate heights
                tot_h = (tot / y_max) * plot_h
                p_h = (p / y_max) * plot_h
                th_h = (th / y_max) * plot_h
                c_h = (c / y_max) * plot_h

                # Top to bottom stack
                # Prompt (bottom), Thinking (middle), Candidates (top)
                cur_y = base_y

                # Prompt segment
                if p_h > 0:
                    y_p_top = cur_y - p_h
                    self.canvas.create_rectangle(
                        x0, y_p_top, x1, cur_y,
                        fill=self.color_prompt, outline=""
                    )
                    cur_y = y_p_top

                # Thinking segment
                if th_h > 0:
                    y_th_top = cur_y - th_h
                    self.canvas.create_rectangle(
                        x0, y_th_top, x1, cur_y,
                        fill=self.color_thinking, outline=""
                    )
                    cur_y = y_th_top

                # Candidates segment
                if c_h > 0:
                    y_c_top = cur_y - c_h
                    self.canvas.create_rectangle(
                        x0, y_c_top, x1, cur_y,
                        fill=self.color_candidates, outline=""
                    )
                    cur_y = y_c_top

                # Highlight border if hovered
                if is_hovered:
                    self.canvas.create_rectangle(
                        x0 - 2, base_y - tot_h - 2, x1 + 2, base_y,
                        outline="#ffffff" if is_dark else "#0f172a", width=2
                    )
                    hovered_box_info = (center_x, base_y - tot_h, b)
            else:
                # Empty marker dot / pill
                self.canvas.create_rectangle(
                    x0, base_y - 2, x1, base_y,
                    fill=grid_col, outline=""
                )
                if is_hovered:
                    hovered_box_info = (center_x, base_y, b)

            # X-axis label (show all labels for 5H, 7D, Month)
            if num_buckets <= 14:
                show_label = True
            elif num_buckets <= 24:
                show_label = (idx % 2 == 0) or (idx == num_buckets - 1)
            else:
                show_label = (idx % 3 == 0) or (idx == num_buckets - 1)

            if show_label:
                lbl = b.get("label", "")
                self.canvas.create_text(
                    center_x, base_y + 14,
                    text=lbl,
                    fill="#38bdf8" if is_hovered else text_col,
                    font=("Helvetica", 9, "bold" if is_hovered else "normal")
                )

        # Draw Active Session Overlay Line
        if hasattr(self, 'active_buckets') and self.active_buckets:
            pts = []
            for idx, b in enumerate(self.active_buckets):
                tot = b.get("prompt", 0) + b.get("thinking", 0) + b.get("candidates", 0)
                center_x = margin_left + (idx + 0.5) * slot_w
                cur_y = base_y - (tot / max(y_max, 1)) * plot_h
                pts.extend([center_x, cur_y])
                if tot > 0:
                    self.canvas.create_oval(center_x-4, cur_y-4, center_x+4, cur_y+4, fill="#38bdf8", outline="#ffffff" if is_dark else "#0f172a", width=1.5)
                else:
                    self.canvas.create_oval(center_x-2, cur_y-2, center_x+2, cur_y+2, fill="#38bdf8", outline="")
            if len(pts) >= 4:
                self.canvas.create_line(pts, fill="#38bdf8", width=2.5, smooth=True)

        # Draw Tooltip Overlay if hovered
        if hovered_box_info:
            bx, by, b_data = hovered_box_info
            self._draw_tooltip(bx, by, b_data, w, h, is_dark)

    def _draw_tooltip(self, bx: float, by: float, b_data: Dict[str, Any], canvas_w: int, canvas_h: int, is_dark: bool):
        act_tok = 0
        if hasattr(self, 'active_buckets') and self.active_buckets and self.hovered_bucket_idx is not None and self.hovered_bucket_idx < len(self.active_buckets):
            act_b = self.active_buckets[self.hovered_bucket_idx]
            act_tok = act_b.get("prompt", 0) + act_b.get("thinking", 0) + act_b.get("candidates", 0)

        tt_w = 190
        tt_h = 88 if act_tok > 0 else 74

        # Calculate position to stay inside canvas bounds
        tx = bx - (tt_w / 2)
        ty = by - tt_h - 10

        if tx < 8:
            tx = 8
        elif tx + tt_w > canvas_w - 8:
            tx = canvas_w - tt_w - 8

        if ty < 6:
            ty = by + 14

        bg_box = "#090d16" if is_dark else "#1e293b"
        border_box = "#3b82f6"
        txt_main = "#ffffff"
        txt_sub = "#cbd5e1"

        # Background rounded rect
        self.canvas.create_rectangle(
            tx, ty, tx + tt_w, ty + tt_h,
            fill=bg_box, outline=border_box, width=1.5
        )

        title_str = b_data.get("full_label") or b_data.get("key", "")
        if len(title_str) > 26:
            title_str = title_str[:24] + "..."

        tot = b_data.get("total", 0)
        p = b_data.get("prompt", 0)
        th = b_data.get("thinking", 0)
        c = b_data.get("candidates", 0)

        # Line 1: Header / Date
        self.canvas.create_text(
            tx + 8, ty + 12,
            text=f"📅 {title_str}",
            fill=txt_main, anchor="w", font=("Helvetica", 9, "bold")
        )

        # Line 2: Total Tokens
        self.canvas.create_text(
            tx + 8, ty + 28,
            text=f"★ Total: {tot:,} tokens",
            fill="#F59E0B", anchor="w", font=("Helvetica", 9, "bold")
        )

        # Line 3: Prompt & Thinking breakdown
        self.canvas.create_text(
            tx + 8, ty + 44,
            text=f"📥 In: {p:,}   🧠 Think: {th:,}",
            fill=txt_sub, anchor="w", font=("Helvetica", 8)
        )

        # Line 4: Output breakdown
        self.canvas.create_text(
            tx + 8, ty + 58,
            text=f"📤 Out: {c:,} tokens",
            fill=txt_sub, anchor="w", font=("Helvetica", 8)
        )

        # Line 5: Active Session (if present)
        if act_tok > 0:
            self.canvas.create_text(
                tx + 8, ty + 74,
                text=f"⚡ Active: {act_tok:,} tokens",
                fill="#38bdf8", anchor="w", font=("Helvetica", 8, "bold")
            )
