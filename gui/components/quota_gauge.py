import customtkinter as ctk
from typing import Optional
from core.config import config


class QuotaGauge(ctk.CTkFrame):
    """
    A quota and rate-limit gauge displaying token burn counts, window-scoped breakdowns,
    colorful status badges (with flipped remaining logic), and recovery countdowns.
    """

    def __init__(
        self,
        master,
        title: str,
        icon: str,
        default_limit: int = 1000000,
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
        self.limit = default_limit

        # Top Content Frame
        self.top_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.top_frame.pack(fill="x", padx=14, pady=(12, 4))

        # Title with Icon
        self.title_label = ctk.CTkLabel(
            self.top_frame,
            text=f"{icon}  {title}",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#0f172a", "#e2e8f0")
        )
        self.title_label.pack(side="left")

        # Colorful Percentage Badge
        self.pct_badge = ctk.CTkLabel(
            self.top_frame,
            text="0.0%",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#15803d",
            corner_radius=6,
            fg_color=("#dcfce7", "#162520"),
            padx=8,
            pady=3
        )
        self.pct_badge.pack(side="right")

        # Numbers row (Active Total on Left, All Total on Right)
        self.numbers_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.numbers_frame.pack(fill="x", padx=14, pady=(2, 4))

        # Left side: Active tokens burned
        self.num_active_frame = ctk.CTkFrame(self.numbers_frame, fg_color="transparent")
        self.num_active_frame.pack(side="left")

        self.lbl_big_active_icon = ctk.CTkLabel(
            self.num_active_frame,
            text="⚡",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=("#1d4ed8", "#38bdf8")
        )
        self.lbl_big_active_icon.pack(side="left", padx=(0, 4))

        self.lbl_big_active_val = ctk.CTkLabel(
            self.num_active_frame,
            text="0",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=("#0f172a", "#ffffff")
        )
        self.lbl_big_active_val.pack(side="left")

        self.lbl_big_active_txt = ctk.CTkLabel(
            self.num_active_frame,
            text=" active burned",
            font=ctk.CTkFont(size=11),
            text_color=("#475569", "#94a3b8")
        )
        self.lbl_big_active_txt.pack(side="left", padx=(3, 0))

        # Right side: All tokens burned
        self.num_all_frame = ctk.CTkFrame(self.numbers_frame, fg_color="transparent")
        self.num_all_frame.pack(side="right")

        self.lbl_big_all_icon = ctk.CTkLabel(
            self.num_all_frame,
            text="★",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=("#7c3aed", "#a78bfa")
        )
        self.lbl_big_all_icon.pack(side="left", padx=(0, 4))

        self.lbl_big_all_val = ctk.CTkLabel(
            self.num_all_frame,
            text="0",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=("#0f172a", "#ffffff")
        )
        self.lbl_big_all_val.pack(side="left")

        self.lbl_big_all_txt = ctk.CTkLabel(
            self.num_all_frame,
            text=" all burned",
            font=ctk.CTkFont(size=11),
            text_color=("#475569", "#94a3b8")
        )
        self.lbl_big_all_txt.pack(side="left", padx=(3, 0))

        # Window Breakdown Sub-Row (Active Session line + All Sessions line)
        self.breakdown_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.breakdown_frame.pack(fill="x", padx=14, pady=(0, 6))

        # Row 1: Active Session Breakdown (⚡ Active: 📥 In: X • 🧠 Think: Y • 📤 Out: Z)
        self.row_active = ctk.CTkFrame(self.breakdown_frame, fg_color="transparent")
        self.row_active.pack(fill="x", pady=(0, 2))

        self.lbl_act_tag = ctk.CTkLabel(
            self.row_active,
            text="⚡ Active:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#1d4ed8", "#38bdf8"),
            width=64,
            anchor="w"
        )
        self.lbl_act_tag.pack(side="left")

        self.lbl_act_p = ctk.CTkLabel(self.row_active, text="📥 In: 0", font=ctk.CTkFont(size=12), text_color=("#2563eb", "#60a5fa"))
        self.lbl_act_p.pack(side="left", padx=(0, 5))

        self.lbl_act_dot1 = ctk.CTkLabel(self.row_active, text="•", font=ctk.CTkFont(size=12), text_color=("#94a3b8", "#475569"))
        self.lbl_act_dot1.pack(side="left", padx=(0, 5))

        self.lbl_act_t = ctk.CTkLabel(self.row_active, text="🧠 Think: 0", font=ctk.CTkFont(size=12), text_color=("#7c3aed", "#a78bfa"))
        self.lbl_act_t.pack(side="left", padx=(0, 5))

        self.lbl_act_dot2 = ctk.CTkLabel(self.row_active, text="•", font=ctk.CTkFont(size=12), text_color=("#94a3b8", "#475569"))
        self.lbl_act_dot2.pack(side="left", padx=(0, 5))

        self.lbl_act_o = ctk.CTkLabel(self.row_active, text="📤 Out: 0", font=ctk.CTkFont(size=12), text_color=("#059669", "#34d399"))
        self.lbl_act_o.pack(side="left", padx=(0, 5))

        # Row 2: All Sessions Breakdown (★ All:    📥 In: X • 🧠 Think: Y • 📤 Out: Z)
        self.row_all = ctk.CTkFrame(self.breakdown_frame, fg_color="transparent")
        self.row_all.pack(fill="x", pady=(0, 2))

        self.lbl_all_tag = ctk.CTkLabel(
            self.row_all,
            text="★ All:   ",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#1d4ed8", "#38bdf8"),
            width=64,
            anchor="w"
        )
        self.lbl_all_tag.pack(side="left")

        self.lbl_all_p = ctk.CTkLabel(self.row_all, text="📥 In: 0", font=ctk.CTkFont(size=12), text_color=("#2563eb", "#60a5fa"))
        self.lbl_all_p.pack(side="left", padx=(0, 5))

        self.lbl_all_dot1 = ctk.CTkLabel(self.row_all, text="•", font=ctk.CTkFont(size=12), text_color=("#94a3b8", "#475569"))
        self.lbl_all_dot1.pack(side="left", padx=(0, 5))

        self.lbl_all_t = ctk.CTkLabel(self.row_all, text="🧠 Think: 0", font=ctk.CTkFont(size=12), text_color=("#7c3aed", "#a78bfa"))
        self.lbl_all_t.pack(side="left", padx=(0, 5))

        self.lbl_all_dot2 = ctk.CTkLabel(self.row_all, text="•", font=ctk.CTkFont(size=12), text_color=("#94a3b8", "#475569"))
        self.lbl_all_dot2.pack(side="left", padx=(0, 5))

        self.lbl_all_o = ctk.CTkLabel(self.row_all, text="📤 Out: 0", font=ctk.CTkFont(size=12), text_color=("#059669", "#34d399"))
        self.lbl_all_o.pack(side="left", padx=(0, 5))

        # Progress Bar
        self.progress_bar = ctk.CTkProgressBar(
            self,
            height=9,
            corner_radius=5,
            progress_color="#10B981",
            fg_color=("#e2e8f0", "#2d3748")
        )
        self.progress_bar.pack(fill="x", padx=14, pady=(2, 10))
        self.progress_bar.set(0.0)

        # Recovery Info Box
        self.recovery_frame = ctk.CTkFrame(
            self,
            corner_radius=8,
            fg_color=("#f8fafc", "#161b26"),
            border_width=1,
            border_color=("#e2e8f0", "#232936")
        )
        self.recovery_frame.pack(fill="x", padx=14, pady=(0, 12))

        self.recovery_label = ctk.CTkLabel(
            self.recovery_frame,
            text="🔄 Reset Status: No recent usage",
            font=ctk.CTkFont(size=11),
            text_color=("#334155", "#94a3b8"),
            anchor="w"
        )
        self.recovery_label.pack(fill="x", padx=10, pady=6)

    def set_title(self, new_title: str):
        self.title_label.configure(text=new_title)

    def set_limit(self, new_limit: int):
        self.limit = max(1, new_limit)

    def update_data(
        self,
        used_tokens: int,
        reset_str: str,
        pct_remaining: float = 0.0,
        custom_limit: Optional[int] = None,
        active_thinking_toks: int = 0,
        active_prompt_toks: int = 0,
        active_candidates_toks: int = 0,
        all_thinking_toks: int = 0,
        all_prompt_toks: int = 0,
        all_candidates_toks: int = 0,
        active_total_toks: int = 0,
        all_total_toks: int = 0,
        thinking_toks: int = 0,
        prompt_toks: int = 0,
        candidates_toks: int = 0,
        **kwargs
    ):
        if custom_limit is not None:
            self.set_limit(custom_limit)

        if all_thinking_toks == 0 and thinking_toks > 0:
            all_thinking_toks = thinking_toks
        if all_prompt_toks == 0 and prompt_toks > 0:
            all_prompt_toks = prompt_toks
        if all_candidates_toks == 0 and candidates_toks > 0:
            all_candidates_toks = candidates_toks
        if all_total_toks == 0 and used_tokens > 0:
            all_total_toks = used_tokens

        show_manual = bool(config.get("show_manual_limits"))

        def _fmt(val: int) -> str:
            return f"{val:,}"

        # Update top prominent big numbers
        self.lbl_big_active_val.configure(text=f"{active_total_toks:,}")
        self.lbl_big_all_val.configure(text=f"{all_total_toks:,}")

        # Update breakdown rows (without trailing totals)
        self.lbl_act_p.configure(text=f"📥 In: {_fmt(active_prompt_toks)}")
        self.lbl_act_t.configure(text=f"🧠 Think: {_fmt(active_thinking_toks)}")
        self.lbl_act_o.configure(text=f"📤 Out: {_fmt(active_candidates_toks)}")

        self.lbl_all_p.configure(text=f"📥 In: {_fmt(all_prompt_toks)}")
        self.lbl_all_t.configure(text=f"🧠 Think: {_fmt(all_thinking_toks)}")
        self.lbl_all_o.configure(text=f"📤 Out: {_fmt(all_candidates_toks)}")

        if show_manual:
            pct_limit = (all_total_toks / self.limit) * 100
            self.lbl_big_all_txt.configure(text=f" all burned ({pct_limit:.0f}% of {_fmt(self.limit)})")
            self.lbl_big_active_txt.configure(text=" active burned")
            ratio = min(1.0, max(0.0, all_total_toks / self.limit))

            # Color by quota severity (<60% green, 60-85% amber, >85% red)
            if pct_limit < 60.0:
                bar_color = "#10B981"
                badge_bg = ("#dcfce7", "#162520")
                badge_txt = ("#15803d", "#10B981")
            elif pct_limit < 85.0:
                bar_color = "#F59E0B"
                badge_bg = ("#fef3c7", "#2d2315")
                badge_txt = ("#b45309", "#F59E0B")
            else:
                bar_color = "#EF4444"
                badge_bg = ("#fee2e2", "#2d1515")
                badge_txt = ("#b91c1c", "#EF4444")

            self.pct_badge.configure(
                text=f"{pct_limit:.1f}% limit used",
                fg_color=badge_bg,
                text_color=badge_txt
            )
            self.progress_bar.configure(progress_color=bar_color)
            self.progress_bar.set(ratio)
        else:
            self.lbl_big_all_txt.configure(text=" all burned")
            self.lbl_big_active_txt.configure(text=" active burned")
            ratio = min(1.0, max(0.0, pct_remaining / 100.0))

            # Flipped color logic for remaining percentage:
            # >60% remaining = 🟢 Green (Safe capacity)
            # 20%-60% remaining = 🟠 Amber (Active recovery)
            # <20% remaining = 🔴 Red (Near reset boundary)
            if pct_remaining >= 60.0 or pct_remaining == 0.0:
                bar_color = "#10B981"
                badge_bg = ("#dcfce7", "#162520")
                badge_txt = ("#15803d", "#10B981")
            elif pct_remaining >= 20.0:
                bar_color = "#F59E0B"
                badge_bg = ("#fef3c7", "#2d2315")
                badge_txt = ("#b45309", "#F59E0B")
            else:
                bar_color = "#EF4444"
                badge_bg = ("#fee2e2", "#2d1515")
                badge_txt = ("#b91c1c", "#EF4444")

            if pct_remaining > 0:
                self.pct_badge.configure(
                    text=f"{pct_remaining:.1f}% remaining",
                    fg_color=badge_bg,
                    text_color=badge_txt
                )
            else:
                self.pct_badge.configure(
                    text="Fully Recovered",
                    fg_color=("#dcfce7", "#162520"),
                    text_color=("#15803d", "#10B981")
                )

            self.progress_bar.configure(progress_color=bar_color)
            self.progress_bar.set(ratio)

        self.recovery_label.configure(text=f"🔄 Reset Status: {reset_str}")
