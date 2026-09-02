import customtkinter as ctk
from typing import Optional


class StatCard(ctk.CTkFrame):
    """A polished metrics card displaying a token metric with icon, count, and active breakdown in Light/Dark themes."""

    def __init__(
        self,
        master,
        title: str,
        icon: str,
        accent_color: str,
        subtitle: str = "",
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
        self.accent_color = accent_color

        # Top Accent Strip
        self.accent_strip = ctk.CTkFrame(
            self,
            height=4,
            corner_radius=2,
            fg_color=accent_color
        )
        self.accent_strip.pack(fill="x", padx=8, pady=(4, 6))

        # Header Frame (Icon + Title + Badge)
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=14, pady=(2, 2))

        self.icon_label = ctk.CTkLabel(
            self.header_frame,
            text=icon,
            font=ctk.CTkFont(size=18)
        )
        self.icon_label.pack(side="left", padx=(0, 6))

        self.title_label = ctk.CTkLabel(
            self.header_frame,
            text=title,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#475569", "#94a3b8")
        )
        self.title_label.pack(side="left")

        # Optional Header Badge
        self.badge_label = ctk.CTkLabel(
            self.header_frame,
            text="",
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=("#e2e8f0", "#2d3748"),
            text_color=("#475569", "#94a3b8"),
            corner_radius=4,
            padx=6,
            pady=2
        )
        self.badge_label.pack(side="right")

        # Primary Metric Line (Large 20pt Total for selected scope)
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.pack(fill="x", padx=14, pady=(4, 0))

        self.main_value_label = ctk.CTkLabel(
            self.main_frame,
            text="0",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=("#0f172a", "#f8fafc")
        )
        self.main_value_label.pack(side="left")

        self.main_desc_label = ctk.CTkLabel(
            self.main_frame,
            text=" tokens",
            font=ctk.CTkFont(size=11),
            text_color=("#475569", "#94a3b8")
        )
        self.main_desc_label.pack(side="left", padx=(6, 0), pady=(4, 0))

        # Sub-Breakdown Row (Active vs All)
        self.sub_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.sub_frame.pack(fill="x", padx=14, pady=(2, 6))

        self.lbl_sub_active = ctk.CTkLabel(
            self.sub_frame,
            text="⚡ Active: 0",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#1d4ed8", "#38bdf8")
        )
        self.lbl_sub_active.pack(side="left", padx=(0, 4))

        self.lbl_sub_dot = ctk.CTkLabel(
            self.sub_frame,
            text="•",
            font=ctk.CTkFont(size=11),
            text_color=("#94a3b8", "#475569")
        )
        self.lbl_sub_dot.pack(side="left", padx=(0, 4))

        self.lbl_sub_all = ctk.CTkLabel(
            self.sub_frame,
            text="★ All: 0",
            font=ctk.CTkFont(size=11),
            text_color=("#64748b", "#cbd5e1")
        )
        self.lbl_sub_all.pack(side="left")

        # Compatibility aliases for legacy callers/tests
        self.active_value_label = self.lbl_sub_active
        self.all_value_label = self.main_value_label
        self.active_desc_label = self.lbl_sub_active
        self.all_desc_label = self.lbl_sub_all

    def update_values(self, active_count: int, all_count: int, custom_badge: Optional[str] = None):
        self.main_value_label.configure(text=f"{all_count:,}")
        self.lbl_sub_active.configure(text=f"⚡ Active: {active_count:,}")
        self.lbl_sub_all.configure(text=f"★ All: {all_count:,}")

        if custom_badge is not None:
            self.badge_label.configure(text=custom_badge)
        else:
            pct = (active_count / all_count * 100) if all_count > 0 else 0
            self.badge_label.configure(text=f"{pct:.1f}% active")

    def update_value(self, count: int, custom_badge: Optional[str] = None):
        self.update_values(active_count=count, all_count=count, custom_badge=custom_badge)
