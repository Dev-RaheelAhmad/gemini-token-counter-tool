import customtkinter as ctk
import tkinter as tk


class SegmentedRatioBar(ctk.CTkFrame):
    """A visual multi-segment horizontal bar displaying the ratio of Input : Thinking : Output tokens in Light/Dark modes."""

    def __init__(
        self,
        master,
        color_prompt: str = "#3B82F6",
        color_thinking: str = "#8B5CF6",
        color_candidates: str = "#10B981",
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
        self.color_prompt = color_prompt
        self.color_thinking = color_thinking
        self.color_candidates = color_candidates

        # Header
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=14, pady=(10, 4))

        self.title_label = ctk.CTkLabel(
            self.header_frame,
            text="📊 Token Proportion Breakdown",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#0f172a", "#e2e8f0")
        )
        self.title_label.pack(side="left")

        # Canvas for drawing the segmented bar
        self.canvas_height = 14
        self.canvas = tk.Canvas(
            self,
            height=self.canvas_height,
            bg="#f1f5f9" if ctk.get_appearance_mode().lower() == "light" else "#2d3748",
            highlightthickness=0,
            bd=0
        )
        self.canvas.pack(fill="x", padx=14, pady=(4, 8))
        self.canvas.bind("<Configure>", lambda e: self._redraw())

        # Legend Row
        self.legend_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.legend_frame.pack(fill="x", padx=14, pady=(0, 10))

        # Prompt Legend
        self.prompt_legend = self._create_legend_item(self.legend_frame, "● Prompt (Input)", self.color_prompt)
        self.prompt_legend.pack(side="left", padx=(0, 16))

        # Thinking Legend
        self.thinking_legend = self._create_legend_item(self.legend_frame, "● Thinking (Planning)", self.color_thinking)
        self.thinking_legend.pack(side="left", padx=(0, 16))

        # Output Legend
        self.output_legend = self._create_legend_item(self.legend_frame, "● Output (Model)", self.color_candidates)
        self.output_legend.pack(side="left")

        self.r_prompt = 0.33
        self.r_thinking = 0.33
        self.r_candidates = 0.34

    def _create_legend_item(self, parent, text: str, color: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent,
            text=f"{text}: 0%",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=color
        )

    def set_ratios(self, prompt_pct: float, thinking_pct: float, candidates_pct: float):
        total = prompt_pct + thinking_pct + candidates_pct
        if total > 0:
            self.r_prompt = prompt_pct / 100.0
            self.r_thinking = thinking_pct / 100.0
            self.r_candidates = candidates_pct / 100.0
        else:
            self.r_prompt = 0.0
            self.r_thinking = 0.0
            self.r_candidates = 0.0

        self.prompt_legend.configure(text=f"● Prompt: {prompt_pct:.1f}%")
        self.thinking_legend.configure(text=f"● Thinking: {thinking_pct:.1f}%")
        self.output_legend.configure(text=f"● Output: {candidates_pct:.1f}%")
        self._redraw()

    def _redraw(self):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas_height
        if w <= 1:
            return

        is_light = ctk.get_appearance_mode().lower() == "light"
        bg_color = "#e2e8f0" if is_light else "#283042"
        self.canvas.configure(bg=bg_color)

        p_w = int(w * self.r_prompt)
        th_w = int(w * self.r_thinking)
        c_w = w - (p_w + th_w)

        x0 = 0
        if p_w > 0:
            self.canvas.create_rectangle(x0, 0, x0 + p_w, h, fill=self.color_prompt, outline="")
            x0 += p_w

        if th_w > 0:
            self.canvas.create_rectangle(x0, 0, x0 + th_w, h, fill=self.color_thinking, outline="")
            x0 += th_w

        if c_w > 0:
            self.canvas.create_rectangle(x0, 0, w, h, fill=self.color_candidates, outline="")
