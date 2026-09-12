"""
Target Space Practice Ground
An interactive demonstration app featuring both the exact AI/IDE Confirmation Modal
with the blue 'Submit' button and dynamic targets for testing the BluePulse Auto-Clicker.
"""

import sys
import random
import time
import tkinter as tk
import customtkinter as ctk

class TargetDemoApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("🎯 Target Practice & Agent Submit Modal Simulator")
        self.geometry("740x620")
        self.configure(fg_color="#0b0f19")

        self.submits_handled = 0
        self.current_step = 1
        self.total_steps = 5
        self.is_executing = True

        self._build_ui()

    def _build_ui(self):
        # Header banner
        header = ctk.CTkFrame(self, fg_color="#131c2e", corner_radius=12)
        header.pack(fill="x", padx=20, pady=(16, 12))

        title = ctk.CTkLabel(
            header,
            text="🎯 AGENT MODAL & BLUE BUTTON SIMULATOR",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color="#38bdf8",
        )
        title.pack(anchor="w", padx=16, pady=(10, 2))

        subtitle = ctk.CTkLabel(
            header,
            text="Simulates the exact agent confirmation modal from your screenshot. Launch the Auto-Clicker, click START, and watch it auto-submit each step!",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#94a3b8",
        )
        subtitle.pack(anchor="w", padx=16, pady=(0, 10))

        # Stats bar
        stats_frame = ctk.CTkFrame(self, fg_color="#131c2e", corner_radius=12)
        stats_frame.pack(fill="x", padx=20, pady=(0, 12))

        self.lbl_score = ctk.CTkLabel(
            stats_frame,
            text="SUBMITS HANDLED: 0 / 5",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color="#34d399",
        )
        self.lbl_score.pack(side="left", padx=16, pady=10)

        self.lbl_execution_status = ctk.CTkLabel(
            stats_frame,
            text="Status: Awaiting Submit...",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fbbf24",
        )
        self.lbl_execution_status.pack(side="left", padx=16, pady=10)

        btn_restart = ctk.CTkButton(
            stats_frame,
            text="Restart Simulation",
            width=120,
            height=28,
            fg_color="#334155",
            hover_color="#475569",
            command=self._restart_simulation,
        )
        btn_restart.pack(side="right", padx=16, pady=10)

        # Simulated Agent Dialog Container (styled just like the IDE dialog)
        self.modal_box = ctk.CTkFrame(
            self,
            fg_color="#18181b",
            corner_radius=12,
            border_width=1,
            border_color="#27272a",
        )
        self.modal_box.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        self._render_modal_content()

    def _render_modal_content(self):
        # Clear children
        for child in self.modal_box.winfo_children():
            child.destroy()

        if not self.is_executing:
            # Execution completed screen
            complete_frame = ctk.CTkFrame(self.modal_box, fg_color="transparent")
            complete_frame.place(relx=0.5, rely=0.5, anchor="center")

            lbl_done = ctk.CTkLabel(
                complete_frame,
                text="🎉 EXECUTION COMPLETED!",
                font=ctk.CTkFont(size=22, weight="bold"),
                text_color="#34d399",
            )
            lbl_done.pack(pady=10)

            lbl_detail = ctk.CTkLabel(
                complete_frame,
                text=f"All {self.total_steps} tool commands were automatically submitted and completed.",
                font=ctk.CTkFont(size=13),
                text_color="#94a3b8",
            )
            lbl_detail.pack(pady=4)
            return

        # Header for the command prompt
        lbl_step = ctk.CTkLabel(
            self.modal_box,
            text=f"Command Confirmation {self.current_step} of {self.total_steps}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#a1a1aa",
        )
        lbl_step.pack(anchor="w", padx=20, pady=(16, 8))

        # Radio / Option boxes (mimicking the screenshot)
        commands = [
            "1  Yes, allow this time",
            f"2  Yes, and always allow 'node -e \"const browser = await chromium.launch... (Step {self.current_step})\"'",
            "3  Yes, and always allow 'git status' and related tools",
            "4  No (tell the agent what to do instead)",
        ]

        for i, cmd in enumerate(commands):
            is_active = (i == 0)
            opt_frame = ctk.CTkFrame(
                self.modal_box,
                fg_color="#27272a" if is_active else "#1f1f23",
                corner_radius=6,
                border_width=1 if is_active else 0,
                border_color="#3f3f46",
            )
            opt_frame.pack(fill="x", padx=20, pady=3)

            lbl_cmd = ctk.CTkLabel(
                opt_frame,
                text=cmd,
                font=ctk.CTkFont(family="Consolas" if i == 1 else "Segoe UI", size=11),
                text_color="#f4f4f5" if is_active else "#71717a",
            )
            lbl_cmd.pack(anchor="w", padx=12, pady=7)

        # Bottom actions: Skip and the Blue Submit Button!
        actions_bar = ctk.CTkFrame(self.modal_box, fg_color="transparent")
        actions_bar.pack(fill="x", side="bottom", padx=20, pady=16)

        # The Blue Submit Button (matching the user's uploaded image)
        self.btn_submit = ctk.CTkButton(
            actions_bar,
            text="Submit ↵",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color="#0078d4",
            hover_color="#106ebe",
            text_color="#ffffff",
            width=88,
            height=34,
            corner_radius=6,
            command=self._on_submit_click,
        )
        self.btn_submit.pack(side="right", padx=(10, 0))

        lbl_skip = ctk.CTkLabel(
            actions_bar,
            text="Skip",
            font=ctk.CTkFont(size=12),
            text_color="#71717a",
        )
        lbl_skip.pack(side="right", padx=10)

    def _on_submit_click(self):
        """When blue submit button is clicked!"""
        self.submits_handled += 1
        self.lbl_score.configure(text=f"SUBMITS HANDLED: {self.submits_handled} / {self.total_steps}")
        self.lbl_execution_status.configure(text=f"Status: Step {self.current_step} Submitted! Running...", text_color="#34d399")

        # Disable submit temporarily to simulate command running
        self.btn_submit.configure(state="disabled", text="Running...", fg_color="#334155")

        if self.current_step < self.total_steps:
            self.current_step += 1
            # Next prompt appears after 1.2 seconds
            self.after(1200, self._next_prompt)
        else:
            # Execution completed
            self.is_executing = False
            self.after(800, self._render_modal_content)
            self.lbl_execution_status.configure(text="Status: All Steps Completed! ✅", text_color="#34d399")

    def _next_prompt(self):
        self.lbl_execution_status.configure(text=f"Status: Awaiting Step {self.current_step} Submit...", text_color="#fbbf24")
        self._render_modal_content()

    def _restart_simulation(self):
        self.current_step = 1
        self.submits_handled = 0
        self.is_executing = True
        self.lbl_score.configure(text="SUBMITS HANDLED: 0 / 5")
        self.lbl_execution_status.configure(text="Status: Awaiting Submit...", text_color="#fbbf24")
        self._render_modal_content()


if __name__ == "__main__":
    app = TargetDemoApp()
    app.mainloop()
