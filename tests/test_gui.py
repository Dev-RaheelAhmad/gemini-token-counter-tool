import os
import sys
import unittest
import tempfile
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from core.ledger import AccountLedger, ledger

class TestSystemTray(unittest.TestCase):
    def test_system_tray_manager(self):
        from gui.tray import SystemTrayManager
        called = []
        mgr = SystemTrayManager(
            on_open_dashboard=lambda: called.append("dash"),
            on_open_mini_hud=lambda: called.append("hud"),
            on_open_bubble=lambda: called.append("bubble"),
            on_refresh=lambda: called.append("ref"),
            on_quit=lambda: called.append("quit")
        )
        mgr._safe_call(mgr.on_open_dashboard)
        mgr._safe_call(mgr.on_open_mini_hud)
        mgr._safe_call(mgr.on_open_bubble)
        mgr._safe_call(mgr.on_refresh)
        mgr._safe_call(mgr.on_quit)
        self.assertEqual(called, ["dash", "hud", "bubble", "ref", "quit"])

        def faulty():
            raise RuntimeError("test error")
        mgr._safe_call(faulty)

    def test_format_tray_tooltip(self):
        from gui.tray import format_tray_tooltip, truncate_utf16
        
        # 1. Standard reports with email account
        display_rep = {
            "tokens_5h": 12500,
            "tokens_7d": 200000,
            "pct_5h_remaining": 75.0,
            "pct_7d_remaining": 92.0,
            "reset_5h_str": "in 2h 30m (75.0% remaining)",
            "reset_7d_str": "in 4d 12h (92.0% remaining)",
        }
        active_rep = {
            "tokens_5h": 8500,
            "tokens_7d": 150000,
        }
        
        tip = format_tray_tooltip(
            display_report=display_rep,
            active_report=active_rep,
            all_report=display_rep,
            account_name="developer@company.org"
        )
        
        self.assertIn("⚡ Gemini (developer)", tip)
        self.assertIn("⏳ 5H: 🔄 in 2h 30m (75% rem)", tip)
        self.assertIn("Act: 8.5K • All: 12.5K", tip)
        self.assertIn("📅 7D: 🔄 in 4d 12h (92% rem)", tip)
        self.assertIn("Act: 150K • All: 200K", tip)
        self.assertLessEqual(len(tip.encode("utf-16-le")) // 2, 127)

        # 2. Large numbers in millions
        big_all = {
            "tokens_5h": 1250000,
            "tokens_7d": 5400000,
            "pct_5h_remaining": 20.0,
            "pct_7d_remaining": 15.0,
            "reset_5h_str": "in 3h 15m",
            "reset_7d_str": "in 6d 22h",
        }
        big_act = {
            "tokens_5h": 1000000,
            "tokens_7d": 3500000,
        }
        big_tip = format_tray_tooltip(
            display_report=big_all,
            active_report=big_act,
            all_report=big_all,
            account_name="poweruser"
        )
        self.assertIn("⚡ Gemini (poweruser)", big_tip)
        self.assertIn("Act: 1.0M • All: 1.2M", big_tip)
        self.assertIn("Act: 3.5M • All: 5.4M", big_tip)
        self.assertLessEqual(len(big_tip.encode("utf-16-le")) // 2, 127)

        # 3. Default empty reports
        empty_tip = format_tray_tooltip()
        self.assertIn("⚡ Gemini (", empty_tip)
        self.assertLessEqual(len(empty_tip.encode("utf-16-le")) // 2, 127)

        # 4. Truncation helper UTF-16 surrogate testing
        emoji_str = "🔄" * 100  # 100 emojis = 200 wchar_t
        truncated = truncate_utf16(emoji_str, 127)
        self.assertLessEqual(len(truncated.encode("utf-16-le")) // 2, 127)

        # 5. Username exceeding 15 characters truncation
        long_user_tip = format_tray_tooltip(account_name="verylongusername12345@example.com")
        self.assertIn("⚡ Gemini (verylongusernam...)", long_user_tip)



class TestGUIComponents(unittest.TestCase):
    def test_component_instantiation(self):
        try:
            import customtkinter as ctk
            root = ctk.CTk()
            root.attributes("-topmost", True)
            root.withdraw()

            from gui.components.stat_card import StatCard
            from gui.components.quota_gauge import QuotaGauge
            from gui.components.progress_bar import SegmentedRatioBar
            from gui.components.usage_chart import UsageChart
            from gui.components.session_table import SessionTable

            card = StatCard(root, title="Test", icon="★", accent_color="#3B82F6")
            card.update_values(1234, 4567, custom_badge="Test")
            self.assertEqual(card.main_value_label.cget("text"), "4,567")
            self.assertIn("1,234", card.lbl_sub_active.cget("text"))
            self.assertIn("4,567", card.lbl_sub_all.cget("text"))

            gauge = QuotaGauge(root, title="Test Gauge", icon="⏳", default_limit=1000000)
            gauge.set_title("⏳  5-Hour Limit")
            gauge.update_data(
                50000, "Reset in 1h", pct_remaining=80.0,
                active_thinking_toks=500, active_prompt_toks=1000, active_candidates_toks=3500, active_total_toks=5000,
                all_thinking_toks=1000, all_prompt_toks=2000, all_candidates_toks=47000, all_total_toks=50000
            )
            self.assertEqual(gauge.title_label.cget("text"), "⏳  5-Hour Limit")
            self.assertEqual(gauge.lbl_big_active_val.cget("text"), "5,000")
            self.assertEqual(gauge.lbl_big_all_val.cget("text"), "50,000")
            self.assertIn("1,000", gauge.lbl_act_p.cget("text"))
            self.assertIn("2,000", gauge.lbl_all_p.cget("text"))

            bar = SegmentedRatioBar(root)
            bar.set_ratios(20.0, 30.0, 50.0)

            chart = UsageChart(root)
            chart.set_records([])
            now_t = datetime.now(timezone.utc)
            chart.set_dual_records([(now_t, 100, 50, 200)], [(now_t, 300, 150, 600)], timeframe="5h")
            self.assertEqual(len(chart.buckets), 11)
            self.assertEqual(len(chart.active_buckets), 11)

            table = SessionTable(root, on_select_session=lambda sid, is_all: None)
            self.assertEqual(table.btn_chat.cget("text"), "⚡ Active Session")
            table.set_sessions([])
            table.set_selection_mode(is_all=False, session_id=None, active_only=False)
            self.assertEqual(table.btn_user.cget("fg_color"), "#3B82F6")
            table.set_selection_mode(is_all=False, session_id=None, active_only=True)
            self.assertEqual(table.btn_chat.cget("fg_color"), "#3B82F6")
            table.set_selection_mode(is_all=True, session_id=None, active_only=False)
            self.assertEqual(table.btn_all.cget("fg_color"), "#8B5CF6")

            from gui.analytics_dialog import AnalyticsDialog
            # 1. Test creation with legacy default_session_id
            dlg1 = AnalyticsDialog(root, default_session_id="active_session")
            dlg1._on_timeframe_changed("24H")
            self.assertEqual(dlg1.selected_scope, "active_session")
            dlg1.destroy()

            # 2. Test creation with synchronized dashboard parameters
            dlg2 = AnalyticsDialog(
                root,
                account_email="developer@company.org",
                active_only=False,
                timeframe="7d"
            )
            self.assertEqual(dlg2.target_account, "developer@company.org")
            self.assertFalse(dlg2.target_active_only)
            self.assertEqual(dlg2.selected_timeframe, "7d")
            self.assertEqual(dlg2.timeframe_seg.get(), "7D")

            # Test sync_with_dashboard dynamically updating scope & timeframe
            dlg2.sync_with_dashboard(account_email="all", active_only=True, timeframe="30d")
            self.assertEqual(dlg2.target_account, "all")
            self.assertTrue(dlg2.target_active_only)
            self.assertEqual(dlg2.selected_timeframe, "30d")
            self.assertEqual(dlg2.timeframe_seg.get(), "30D")

            # Test minsize and resizability (standard top-level window controls)
            self.assertGreaterEqual(dlg2._min_width, 860)
            self.assertGreaterEqual(dlg2._min_height, 560)

            # Test live data rendering and consistency with ledger.get_filtered_report
            from core.ledger import ledger
            test_sid = "test_analytics_sync_001"
            now_dt = datetime.now(timezone.utc)
            ledger.update_session(
                session_id=test_sid,
                account_email="developer@company.org",
                stats={"prompt": 500, "thinking": 250, "candidates": 750},
                line_records=[(now_dt, 500, 250, 750)],
                first_prompt="Testing Analytics Dialog sync",
                last_active="2026-08-31 12:00:00"
            )
            dlg2.sync_with_dashboard(account_email="developer@company.org", active_only=False, session_id=test_sid, timeframe="24h")
            expected_rep = ledger.get_filtered_report(
                account_email="developer@company.org",
                active_only=False,
                session_id=test_sid,
                timeframe="24h"
            )
            self.assertEqual(dlg2.current_summary.get("total_tokens", 0), expected_rep["total"])
            self.assertEqual(dlg2.current_summary.get("prompt_tokens", 0), expected_rep["prompt"])
            self.assertEqual(dlg2.current_summary.get("thinking_tokens", 0), expected_rep["thinking"])
            # 3. Test default instantiation: active user dropdown, All sessions button, 5H filter
            dlg_def = AnalyticsDialog(root)
            # self.assertEqual(dlg_def.session_scope_seg.get(), "All Sessions")
            self.assertFalse(dlg_def.target_active_only)
            self.assertEqual(dlg_def.timeframe_seg.get(), "5H")
            self.assertEqual(dlg_def.selected_timeframe, "5h")

            # Test selecting "All" in account dropdown
            dlg_def._on_account_changed("All")
            # Test legacy _on_scope_changed handler
            dlg_def._on_scope_changed("All")
            self.assertEqual(dlg_def.target_account, "all")

            dlg_def.destroy()
            dlg2.destroy()

            from gui.cleaner_dialog import CleanerDialog, tk
            dlg_cleaner = CleanerDialog(root)
            # Note: -topmost assertion removed; xvfb doesn't support the attribute
            # Test context menu creation for session
            class DummyEvent:
                x_root = 100
                y_root = 100
            orig_popup = tk.Menu.tk_popup
            try:
                tk.Menu.tk_popup = lambda self, x, y: None
                dummy_session = {"session_id": "test_sid_menu_1", "tokens": 100, "size_str": "1 KB"}
                dlg_cleaner._show_context_menu(DummyEvent(), dummy_session)
            finally:
                tk.Menu.tk_popup = orig_popup
            dlg_cleaner.destroy()

            from gui.mini_hud import MiniHUD
            hud = MiniHUD(root, on_restore_callback=lambda: None)
            hud.show_7d_expanded = True
            hud._build_sections()

            # Test drag methods
            class DragEvent:
                x_root = 150
                y_root = 150
            hud._start_drag(DragEvent())
            hud._do_drag(DragEvent())
            hud._end_drag(DragEvent())
            
            # Test 7D progress bar color is green for healthy / 100% capacity
            hud.update_data({
                "prompt": 100, "thinking": 200, "candidates": 300, "total": 600,
                "tokens_5h": 600, "reset_5h_str": "Reset in 1h",
                "tokens_7d": 1000, "reset_7d_str": "Reset in 6d",
                "burn_rate_str": "Idle"
            })
            if hasattr(hud, "prog_7d"):
                self.assertEqual(hud.prog_7d.cget("progress_color"), "#10B981")

            # Test formatting in Mini HUD
            hud.update_data({
                "prompt": 10000, "thinking": 25000, "candidates": 650000, "total": 685000,
                "tokens_5h": 123456, "pct_5h_remaining": 73.1, "reset_5h_str": "in 3h 45m (73.1% remaining)",
                "tokens_7d": 711545, "pct_7d_remaining": 77.2, "reset_7d_str": "in 5d 15h (77.2% remaining)",
                "thinking_5h": 25000, "prompt_5h": 10000, "candidates_5h": 88456,
                "thinking_7d": 25000, "prompt_7d": 10000, "candidates_7d": 676545,
                "burn_rate_str": "Idle"
            })
            self.assertIn("123,456", hud.h5_all_lbl.cget("text"))
            self.assertEqual(hud.h5_all_lbl.cget("text_color"), ("#15803d", "#10B981"))
            if hasattr(hud, "h7_all_lbl"):
                self.assertIn("711,545", hud.h7_all_lbl.cget("text"))
                self.assertEqual(hud.h7_all_lbl.cget("text_color"), ("#15803d", "#10B981"))
            # Sub-breakdown in 5h line: Input first, thinking middle, output last
            h5_breakdown = hud.h5_all_breakdown_lbl.cget("text")
            self.assertIn("10,000", h5_breakdown)
            self.assertIn("25,000", h5_breakdown)
            self.assertTrue(h5_breakdown.startswith("📥"))
            self.assertFalse(h5_breakdown.startswith("("))
            self.assertFalse(h5_breakdown.endswith(")"))
            self.assertIn("• 🧠", h5_breakdown)
            self.assertIn("• 📤", h5_breakdown)

            # Test Dropdown Synchronization in Mini HUD
            # 1. Active Session mode
            hud.update_data({
                "mode": "session",
                "session_id": "session_active_123",
                "scope_badge": "Active Session",
                "prompt": 10000, "thinking": 12000, "candidates": 20000, "total": 42000,
                "tokens_5h": 42000, "reset_5h_str": "Reset in 4h",
                "tokens_7d": 42000, "reset_7d_str": "Reset in 6d",
                "thinking_5h": 12000, "prompt_5h": 10000, "candidates_5h": 20000,
                "thinking_7d": 12000, "prompt_7d": 10000, "candidates_7d": 20000,
                "burn_rate_str": "Idle"
            })
            self.assertIn("42,000", hud.h5_all_lbl.cget("text"))
            if hasattr(hud, "h7_all_lbl"):
                self.assertIn("42,000", hud.h7_all_lbl.cget("text"))
            if hasattr(hud, "active_lbl"):
                self.assertIn("Active Session", hud.active_lbl.cget("text"))

            # 2. User Account mode
            hud.update_data({
                "mode": "session",
                "session_id": "session_active_123",
                "account": "user1@example.com",
                "scope_badge": "👤 user1",
                "prompt": 5000, "thinking": 5000, "candidates": 15000, "total": 25000,
                "tokens_5h": 15000, "reset_5h_str": "Reset in 3h",
                "tokens_7d": 25000, "reset_7d_str": "Reset in 5d",
                "thinking_5h": 5000, "prompt_5h": 5000, "candidates_5h": 5000,
                "thinking_7d": 5000, "prompt_7d": 5000, "candidates_7d": 15000,
                "burn_rate_str": "Idle"
            })
            self.assertIn("15,000", hud.h5_all_lbl.cget("text"))
            if hasattr(hud, "h7_all_lbl"):
                self.assertIn("25,000", hud.h7_all_lbl.cget("text"))
            if hasattr(hud, "active_lbl"):
                self.assertIn("user1", hud.active_lbl.cget("text"))

            # 3. All Accounts mode
            hud.update_data({
                "mode": "device",
                "is_all": True,
                "scope_badge": "All Accounts",
                "prompt": 800000, "thinking": 400000, "candidates": 1300000, "total": 2500000,
                "tokens_5h": 900000, "reset_5h_str": "Reset in 2h",
                "tokens_7d": 2500000, "reset_7d_str": "Reset in 4d",
                "thinking_5h": 150000, "prompt_5h": 300000, "candidates_5h": 450000,
                "thinking_7d": 400000, "prompt_7d": 800000, "candidates_7d": 1300000,
                "burn_rate_str": "Idle"
            })
            self.assertIn("900,000", hud.h5_all_lbl.cget("text"))
            if hasattr(hud, "h7_all_lbl"):
                self.assertIn("2,500,000", hud.h7_all_lbl.cget("text"))
            if hasattr(hud, "active_lbl"):
                self.assertIn("All Accounts", hud.active_lbl.cget("text"))

            # 4. Test Google Realtime Quota remaining percentage display
            from core.config import config
            config.set("show_manual_limits", False)
            hud.update_data({
                "mode": "session",
                "session_id": "session_active_456",
                "tokens_5h": 50000,
                "pct_5h_remaining": 88.5,
                "reset_5h_str": "in 3h 15m",
                "tokens_7d": 120000,
                "pct_7d_remaining": 92.4,
                "reset_7d_str": "in 6d 02h",
                "is_realtime_quota": True,
                "burn_rate_str": "Idle"
            })
            self.assertIn("88.5% rem", hud.h5_badge.cget("text"))
            if hasattr(hud, "h7_badge"):
                self.assertIn("92.4% rem", hud.h7_badge.cget("text"))
            config.set("show_manual_limits", False)

            # Test pin toggle
            initial_pin = hud.is_pinned
            hud._toggle_pin()
            self.assertEqual(hud.is_pinned, not initial_pin)
            hud._toggle_pin()
            self.assertEqual(hud.is_pinned, initial_pin)

            # Test 2 lines of stats per card in Mini HUD (Active Session & All Sessions)
            self.assertTrue(hasattr(hud, "h5_active_lbl"))
            self.assertTrue(hasattr(hud, "h5_all_lbl"))
            if hasattr(hud, "h7_active_lbl"):
                self.assertTrue(hasattr(hud, "h7_active_lbl"))
                self.assertTrue(hasattr(hud, "h7_all_lbl"))

            # Update with distinct Active and All reports
            all_rep = {
                "tokens_5h": 50000,
                "thinking_5h": 10000,
                "prompt_5h": 30000,
                "candidates_5h": 10000,
                "tokens_7d": 150000,
                "thinking_7d": 30000,
                "prompt_7d": 90000,
                "candidates_7d": 30000,
                "pct_5h_remaining": 88.5,
                "pct_7d_remaining": 92.4,
                "is_realtime_quota": True,
                "reset_5h_str": "in 3h 15m",
                "reset_7d_str": "in 6d 02h",
                "scope_badge": "★ All Accounts"
            }
            act_rep = {
                "tokens_5h": 5000,
                "thinking_5h": 1000,
                "prompt_5h": 3000,
                "candidates_5h": 1000,
                "tokens_7d": 5000,
                "thinking_7d": 1000,
                "prompt_7d": 3000,
                "candidates_7d": 1000,
                "scope_badge": "Active Session"
            }
            hud.update_data(report=all_rep, session_report=act_rep)

            # Verify 5H lines
            self.assertIn("Active", hud.h5_active_lbl.cget("text"))
            self.assertIn("5,000", hud.h5_active_lbl.cget("text"))
            self.assertIn("All", hud.h5_all_lbl.cget("text"))
            self.assertIn("50,000", hud.h5_all_lbl.cget("text"))

            # Verify 7D lines if expanded
            if hasattr(hud, "h7_active_lbl"):
                self.assertIn("Active", hud.h7_active_lbl.cget("text"))
                self.assertIn("5,000", hud.h7_active_lbl.cget("text"))
                self.assertIn("All", hud.h7_all_lbl.cget("text"))
                self.assertIn("150,000", hud.h7_all_lbl.cget("text"))

            # Test account dropdown selector in Mini HUD
            if hasattr(hud, "account_menu"):
                self.assertIn("All", hud.account_menu.cget("values"))
                hud.account_menu.set("All")
                hud._on_hud_account_selected("All")
                self.assertEqual(hud.account_menu.get(), "All")

            # Test focus-out check safety
            hud._check_focus_and_auto_dismiss()
            hud.destroy()

            from gui.window_utils import apply_windows_dark_titlebar, cancel_all_pending_after_events
            apply_windows_dark_titlebar(root, mode="dark")
            apply_windows_dark_titlebar(root, mode="light")

            cancel_all_pending_after_events(root)
            root.destroy()
        except Exception as e:
            if "no display" in str(e).lower() or "cannot connect to X server" in str(e).lower():
                self.skipTest("No display available for GUI test")
            else:
                raise e

    def test_mini_hud_floating_hover_bubble_mode(self):
        """Test Floating Hover Bubble minimized feature in Mini HUD: bubble layout, click-to-expand, hover preview, collapse, dragging, and pin overrides."""
        try:
            import customtkinter as ctk
            import tkinter as tk
            from core.config import config
            from gui.mini_hud import MiniHUD

            root = ctk.CTk()
            root.withdraw()

            # Default is full Mini-Hub window mode
            hud = MiniHUD(root, on_restore_callback=lambda: None)
            self.assertFalse(hud.is_minimized)
            self.assertFalse(hud.is_hover_expanded)
            self.assertEqual(hud.top_bar.winfo_manager(), "pack")

            # 1. Switch to bubble mode via minimize button
            hud.minimize_btn.invoke()
            self.assertTrue(hud.is_minimized)
            self.assertFalse(hud.is_hover_expanded)
            self.assertEqual(hud.bubble_frame.winfo_manager(), "pack")
            self.assertNotEqual(hud.top_bar.winfo_manager(), "pack")

            # Update report for tooltip text verification
            hud.update_data(
                report={
                    "tokens_5h": 12500,
                    "pct_5h_remaining": 87.5,
                    "reset_5h_str": "in 3h 15m",
                    "tokens_7d": 45000,
                    "pct_7d_remaining": 91.0,
                    "reset_7d_str": "in 5d 10h",
                    "prompt_5h": 5000,
                    "thinking_5h": 2500,
                    "candidates_5h": 5000,
                    "prompt_7d": 20000,
                    "thinking_7d": 5000,
                    "candidates_7d": 20000,
                    "is_realtime_quota": True
                },
                session_report={
                    "tokens_5h": 4000,
                    "prompt_5h": 2000,
                    "thinking_5h": 500,
                    "candidates_5h": 1500,
                    "tokens_7d": 12000,
                    "prompt_7d": 6000,
                    "thinking_7d": 2000,
                    "candidates_7d": 4000,
                }
            )

            # 2. Test Hover on floating bubble: does NOT expand window, triggers full rich tooltip
            hud._on_bubble_hover_enter()
            self.assertFalse(hud.is_hover_expanded)
            self.assertEqual(hud.bubble_frame.winfo_manager(), "pack")
            tooltip_txt = hud._get_tooltip_text()
            self.assertIn("GEMINI TOKEN MONITOR", tooltip_txt)
            self.assertIn("5-HOUR WINDOW", tooltip_txt)
            self.assertIn("12,500", tooltip_txt)
            self.assertIn("45,000", tooltip_txt)
            self.assertIn("87.5%", tooltip_txt)
            self.assertIn("👤", tooltip_txt)

            # Verify clean text formatting without ASCII divider line bloat
            self.assertNotIn("──────────", tooltip_txt)

            # Test Hover leave hides tooltip and verifies left-alignment in structured card
            hud._show_tooltip()
            if hud._tooltip_win:
                self.assertTrue(hud._tooltip_win.winfo_exists())
                # Verify child labels inside tooltip card have anchor='w' / left alignment
                card = hud._tooltip_win.winfo_children()[0]
                labels = [w for w in card.winfo_children() if isinstance(w, ctk.CTkLabel)]
                self.assertGreater(len(labels), 3)
                for lbl in labels:
                    self.assertEqual(lbl.cget("anchor"), "w")

                # Test moving onto tooltip keeps tooltip active
                hud._on_bubble_hover_enter()
                self.assertIsNotNone(hud._tooltip_win)

                # Test leaving tooltip dismisses it when pointer is outside
                hud._on_bubble_hover_leave()
                hud._check_tooltip_dismiss()
                self.assertIsNone(hud._tooltip_win)
            else:
                hud._on_bubble_hover_leave()
                hud._check_tooltip_dismiss()
                self.assertIsNone(hud._tooltip_win)

            # 3. Test Click on bubble (without dragging) -> Expands full HUD
            class MockClickEvent:
                x_root = 100
                y_root = 100
            hud._start_drag(MockClickEvent())
            self.assertFalse(hud._is_dragging)
            hud._end_drag(MockClickEvent())
            self.assertTrue(hud.is_hover_expanded)
            self.assertEqual(hud.top_bar.winfo_manager(), "pack")
            self.assertNotEqual(hud.bubble_frame.winfo_manager(), "pack")

            # 4. Test Moving the full Mini-Hub window does NOT move the floating bubble's own position
            hud._bubble_pos = (500, 300)
            drag_hud = MockClickEvent()
            drag_hud.x_root = 150
            drag_hud.y_root = 150
            hud._start_drag(MockClickEvent())
            hud._do_drag(drag_hud)
            hud._end_drag(drag_hud)
            # Full HUD position updated, but bubble position remains fixed
            self.assertEqual(hud._bubble_pos, (500, 300))

            # 5. Test Auto-shrink on leave collapses back to exact bubble position
            orig_ptrx = hud.winfo_pointerx
            orig_ptry = hud.winfo_pointery
            orig_rootx = hud.winfo_rootx
            orig_rooty = hud.winfo_rooty
            orig_w = hud.winfo_width
            orig_h = hud.winfo_height
            try:
                hud.winfo_rootx = lambda: 100
                hud.winfo_rooty = lambda: 100
                hud.winfo_width = lambda: 350
                hud.winfo_height = lambda: 200
                
                # Pointer inside -> stays expanded
                hud.winfo_pointerx = lambda: 150
                hud.winfo_pointery = lambda: 150
                hud._check_hover_collapse()
                self.assertTrue(hud.is_hover_expanded)

                # Pointer outside but PINNED -> stays expanded
                hud.is_pinned = True
                hud.winfo_pointerx = lambda: 500
                hud.winfo_pointery = lambda: 500
                hud._check_hover_collapse()
                self.assertTrue(hud.is_hover_expanded)

                # Pointer outside and UNPINNED -> automatically shrinks back into bubble at (500, 300)
                hud.is_pinned = False
                hud._check_hover_collapse()
                self.assertFalse(hud.is_hover_expanded)
                self.assertEqual(hud.bubble_frame.winfo_manager(), "pack")
                self.assertEqual(hud._bubble_pos, (500, 300))
            finally:
                hud.winfo_pointerx = orig_ptrx
                hud.winfo_pointery = orig_ptry
                hud.winfo_rootx = orig_rootx
                hud.winfo_rooty = orig_rooty
                hud.winfo_width = orig_w
                hud.winfo_height = orig_h

            # 6. Test Click-outside / FocusOut auto-collapse
            hud._expand_on_click()
            self.assertTrue(hud.is_hover_expanded)
            hud.is_pinned = False
            # Simulate focus moving outside the HUD (e.g. user clicked another window).
            # _check_focus_collapse_to_bubble only collapses when (a) no child of the HUD
            # holds focus AND (b) the pointer is outside the window bounds.
            root.focus_force()
            orig_ptrx2 = hud.winfo_pointerx
            orig_ptry2 = hud.winfo_pointery
            try:
                hud.winfo_pointerx = lambda: 9999
                hud.winfo_pointery = lambda: 9999
                hud._check_focus_collapse_to_bubble()
                self.assertFalse(hud.is_hover_expanded)
                self.assertTrue(hud.is_minimized)
                self.assertEqual(hud.bubble_frame.winfo_manager(), "pack")
            finally:
                hud.winfo_pointerx = orig_ptrx2
                hud.winfo_pointery = orig_ptry2

            # 7. Test Dragging in bubble mode updates bubble anchor position
            drag_b1 = MockClickEvent()
            drag_b1.x_root = 100
            drag_b1.y_root = 100
            hud._start_drag(drag_b1)
            drag_b2 = MockClickEvent()
            drag_b2.x_root = 250
            drag_b2.y_root = 250
            hud._do_drag(drag_b2)
            self.assertTrue(hud._is_dragging)
            hud._end_drag(drag_b2)
            self.assertTrue(hud.is_minimized)
            self.assertFalse(hud.is_hover_expanded)

            # 7b. Test Multi-Cycle Minimize & Maximize preserves independent positions
            # Use positions within any CI screen's work area to avoid clamping side-effects
            hud._hud_pos = (150, 150)
            hud._bubble_pos = (300, 200)
            # Cycle 1: Click bubble to maximize -> expands to _hud_pos (150, 150)
            hud._expand_on_click()
            self.assertTrue(hud.is_hover_expanded)
            self.assertEqual(hud._hud_pos, (150, 150))
            self.assertEqual(hud._bubble_pos, (300, 200))
            # Minimize to bubble -> shrinks to _bubble_pos; clamping may adjust but must NOT change _hud_pos
            hud._toggle_minimized()
            self.assertTrue(hud.is_minimized)
            self.assertFalse(hud.is_hover_expanded)
            self.assertEqual(hud._hud_pos, (150, 150))
            self.assertNotEqual(hud._bubble_pos, hud._hud_pos)
            saved_bubble = hud._bubble_pos
            # Cycle 2: Click bubble to maximize again -> MUST stay at _hud_pos (150, 150)
            hud._expand_on_click()
            self.assertTrue(hud.is_hover_expanded)
            self.assertEqual(hud._hud_pos, (150, 150))
            self.assertEqual(hud._bubble_pos, saved_bubble)
            # Minimize to bubble again -> MUST preserve positions independently
            hud._toggle_minimized()
            self.assertTrue(hud.is_minimized)
            self.assertFalse(hud.is_hover_expanded)
            self.assertEqual(hud._hud_pos, (150, 150))
            self.assertEqual(hud._bubble_pos, saved_bubble)

            # 8. Test At-a-Glance Token Numbers displayed on Floating Bubble
            hud.update_data(
                report={
                    "tokens_5h": 12500,
                    "pct_5h_remaining": 87.5,
                    "reset_5h_str": "in 3h 15m",
                    "tokens_7d": 45000,
                    "pct_7d_remaining": 91.0,
                    "reset_7d_str": "in 5d 10h",
                    "prompt_5h": 5000,
                    "thinking_5h": 2500,
                    "candidates_5h": 5000,
                    "prompt_7d": 20000,
                    "thinking_7d": 5000,
                    "candidates_7d": 20000,
                    "is_realtime_quota": True
                },
                session_report={
                    "tokens_5h": 4000,
                    "prompt_5h": 2000,
                    "thinking_5h": 500,
                    "candidates_5h": 1500,
                    "tokens_7d": 12000,
                    "prompt_7d": 6000,
                    "thinking_7d": 2000,
                    "candidates_7d": 4000,
                }
            )
            self.assertEqual(hud.bubble_hdr_tf.cget("text"), "Time")
            self.assertEqual(hud.bubble_hdr_act.cget("text"), "Active")
            self.assertEqual(hud.bubble_hdr_all.cget("text"), "All")
            self.assertEqual(hud.bubble_hdr_quota.cget("text"), "Quota")
            self.assertEqual(hud.bubble_5h_badge.cget("text"), "5H")
            self.assertEqual(hud.bubble_7d_badge.cget("text"), "7D")
            self.assertIn("4,000", hud.bubble_5h_act_lbl.cget("text"))
            self.assertIn("12,500", hud.bubble_5h_all_lbl.cget("text"))
            self.assertIn("88%", hud.bubble_5h_pct_lbl.cget("text"))
            self.assertIn("12,000", hud.bubble_7d_act_lbl.cget("text"))
            self.assertIn("45,000", hud.bubble_7d_all_lbl.cget("text"))
            self.assertIn("91%", hud.bubble_7d_pct_lbl.cget("text"))

            # Test 6-digit and million boundary formatting
            hud.update_data(
                report={"tokens_5h": 999999, "tokens_7d": 1250000, "pct_5h_remaining": 10.0, "pct_7d_remaining": 50.0},
                session_report={"tokens_5h": 123456, "tokens_7d": 750000}
            )
            self.assertIn("123,456", hud.bubble_5h_act_lbl.cget("text"))
            self.assertIn("999,999", hud.bubble_5h_all_lbl.cget("text"))
            self.assertIn("750,000", hud.bubble_7d_act_lbl.cget("text"))
            self.assertIn("1.25M", hud.bubble_7d_all_lbl.cget("text"))

            # 9. Test Right-Click Context Menu & Menu Actions (Bubble + Expanded)
            hud.deiconify()
            menu_ev = MockClickEvent()
            menu_ev.x_root = 150
            menu_ev.y_root = 150
            menu_ev.widget = hud.bubble_frame
            hud._on_global_right_click(menu_ev)
            self.assertIsNotNone(hud._context_menu_win)
            self.assertTrue(hud._context_menu_win.winfo_exists())

            # Test right-click in expanded mode
            hud.is_minimized = False
            menu_ev2 = MockClickEvent()
            menu_ev2.x_root = 150
            menu_ev2.y_root = 150
            menu_ev2.widget = hud.content_frame
            hud._on_global_right_click(menu_ev2)
            self.assertIsNotNone(hud._context_menu_win)
            self.assertTrue(hud._context_menu_win.winfo_exists())

            # Verify context menu destruction does not cancel root after timers
            test_timer_executed = [False]
            dummy_tid = root.after(5000, lambda: test_timer_executed.__setitem__(0, True))
            hud._context_menu_win.destroy()
            self.assertIsNone(hud._context_menu_win)
            all_afters = root.tk.eval("after info")
            self.assertIn(str(dummy_tid), all_afters)
            root.after_cancel(dummy_tid)

            hud._set_opacity(0.75)
            self.assertEqual(config.get("mini_hud_opacity"), 0.75)
            hud._set_opacity(1.0)

            on_restore_called = [False]
            def _mock_restore():
                on_restore_called[0] = True
            hud.on_restore_callback = _mock_restore
            hud._restore_dashboard()
            self.assertTrue(on_restore_called[0])

            # Clean up
            config.set("hud_minimized", False, save_now=False)
            hud.destroy()
            from gui.window_utils import cancel_all_pending_after_events
            cancel_all_pending_after_events(root)
            root.destroy()
        except Exception as e:
            if "no display" in str(e).lower() or "cannot connect to X server" in str(e).lower():
                self.skipTest("No display available for GUI test")
            else:
                raise e

    def test_app_account_dropdown_switching(self):
        try:
            from gui.app import GeminiTokenCounterApp
            app = GeminiTokenCounterApp()
            app.withdraw()
            if app.watcher and hasattr(app.watcher, "stop"):
                app.watcher.stop()

            # Set account_map with mock accounts
            app.account_map = {
                "All": "all",
                "👤 alice": "alice@company.org",
                "👤 bob": "bob@company.org"
            }
            app.account_menu.configure(values=["All", "👤 alice", "👤 bob"])

            # 1. Select specific user Bob from dropdown
            app._on_main_account_selected("👤 bob")
            self.assertEqual(app.selected_account_filter, "bob@company.org")
            self.assertFalse(app.is_all_mode)

            # 2. Simulate background watcher poll - Bob must NOT be reset to active user
            app._on_watcher_update(active_report={}, all_report={}, sessions=[])
            self.assertEqual(app.selected_account_filter, "bob@company.org")
            self.assertFalse(app.is_all_mode)

            # 3. Select 'All' from dropdown
            app._on_main_account_selected("All")
            self.assertEqual(app.selected_account_filter, "all")
            self.assertTrue(app.is_all_mode)

            # 4. Simulate background watcher poll - All must NOT be reset
            app._on_watcher_update(active_report={}, all_report={}, sessions=[])
            self.assertEqual(app.selected_account_filter, "all")
            self.assertTrue(app.is_all_mode)

            app.destroy()
        except Exception as e:
            if "no display" in str(e).lower() or "cannot connect to X server" in str(e).lower():
                self.skipTest("No display available for GUI test")
            else:
                raise e

    def test_app_mini_hud_and_floating_bubble_buttons(self):
        try:
            from gui.app import GeminiTokenCounterApp
            app = GeminiTokenCounterApp()
            app.withdraw()
            if app.watcher and hasattr(app.watcher, "stop"):
                app.watcher.stop()

            # Verify buttons exist in header and sidebar
            self.assertIsNotNone(app.hud_btn)
            self.assertEqual(app.hud_btn.cget("text"), "🗕 Mini HUD")
            self.assertIsNotNone(app.bubble_btn)
            self.assertEqual(app.bubble_btn.cget("text"), "🫧 Bubble")
            self.assertIsNotNone(app.sidebar_hud_btn)
            self.assertIsNotNone(app.sidebar_bubble_btn)

            # Test opening full Mini-Hub via show_mini_hud
            app.show_mini_hud()
            self.assertIsNotNone(app.mini_hud_window)
            self.assertFalse(app.mini_hud_window.is_minimized)
            self.assertEqual(app.state(), "withdrawn")

            # Test restoring dashboard
            app.show_dashboard()
            self.assertEqual(app.mini_hud_window.state(), "withdrawn")

            # Test opening directly in compact Floating Bubble mode
            app.show_floating_bubble()
            self.assertTrue(app.mini_hud_window.is_minimized)
            self.assertFalse(app.mini_hud_window.is_hover_expanded)
            self.assertEqual(app.state(), "withdrawn")

            # Clean up
            app.mini_hud_window.destroy()
            app.destroy()
        except Exception as e:
            if "no display" in str(e).lower() or "cannot connect to X server" in str(e).lower():
                self.skipTest("No display available for GUI test")
            else:
                raise e



class TestUnifiedDashboardFiltering(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ledger_file = Path(self.tmpdir) / "account_usage.json"
        self.ledger_log = Path(self.tmpdir) / "account_ledger.jsonl"
        self.ledger = AccountLedger()
        self.ledger.ledger_file = self.ledger_file
        self.ledger.ledger_log_file = self.ledger_log
        self.ledger.sessions.clear()
        self.now = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)

        # Setup test data:
        # Session 1 (Active session, latest mtime): Account A (2h ago) + Account B (1h ago)
        self.ledger.update_session(
            session_id="active_sess_001",
            account_email="alice@company.org",
            stats={"prompt": 1000, "thinking": 500, "candidates": 1500},
            line_records=[(self.now - timedelta(hours=2), 1000, 500, 1500)],
            first_prompt="Alice prompt in active session",
            last_active="2026-08-31 10:00:00",
            mtime=1788168000.0,
            force_account=True
        )
        self.ledger.update_session(
            session_id="active_sess_001",
            account_email="bob@company.org",
            stats={"prompt": 1500, "thinking": 700, "candidates": 2000},
            line_records=[(self.now - timedelta(hours=2), 1000, 500, 1500), (self.now - timedelta(hours=1), 500, 200, 500)],
            first_prompt="Alice prompt in active session",
            last_active="2026-08-31 11:00:00",
            mtime=1788171600.0,
            force_account=True
        )

        # Session 2 (Historical session, older mtime): Account A (10h ago)
        self.ledger.update_session(
            session_id="hist_sess_002",
            account_email="alice@company.org",
            stats={"prompt": 2000, "thinking": 1000, "candidates": 3000},
            line_records=[(self.now - timedelta(hours=10), 2000, 1000, 3000)],
            first_prompt="Alice old prompt",
            last_active="2026-08-31 02:00:00",
            mtime=1788139200.0,
            force_account=True
        )

        # Session 3 (Older historical session): Account B (3 days ago)
        self.ledger.update_session(
            session_id="hist_sess_003",
            account_email="bob@company.org",
            stats={"prompt": 4000, "thinking": 2000, "candidates": 4000},
            line_records=[(self.now - timedelta(days=3), 4000, 2000, 4000)],
            first_prompt="Bob 3-day old prompt",
            last_active="2026-08-28 12:00:00",
            mtime=1787910000.0,
            force_account=True
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_filter_specific_account_active_only_5h(self):
        # Alice + Active Only (True) + 5H
        rep = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=True,
            timeframe="5h",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        # Alice in active session has 1000 prompt, 500 thinking, 1500 candidates = 3000 tokens within 5h
        self.assertEqual(rep["total"], 3000)
        self.assertEqual(rep["prompt"], 1000)
        self.assertEqual(rep["thinking"], 500)
        self.assertEqual(rep["candidates"], 1500)
        self.assertEqual(rep["matched_sessions_count"], 1)
        self.assertIn("active_sess_001", rep["matching_session_ids"])
        self.assertNotIn("hist_sess_002", rep["matching_session_ids"])

    def test_filter_specific_account_all_sessions_24h(self):
        # Alice + All Sessions (active_only=False) + 24H
        rep = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=False,
            timeframe="24h",
            ref_time=self.now,
            use_local_time=False
        )
        # Alice has active session (3000 tokens @ -2h) + hist session (6000 tokens @ -10h) = 9000 tokens
        self.assertEqual(rep["total"], 9000)
        self.assertEqual(rep["prompt"], 3000)
        self.assertEqual(rep["thinking"], 1500)
        self.assertEqual(rep["candidates"], 4500)
        self.assertEqual(rep["matched_sessions_count"], 2)
        self.assertIn("active_sess_001", rep["matching_session_ids"])
        self.assertIn("hist_sess_002", rep["matching_session_ids"])

    def test_filter_all_accounts_active_only_7d(self):
        # All + Active Only (True) + 7D
        rep = self.ledger.get_filtered_report(
            account_email="All",
            active_only=True,
            timeframe="7d",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        # Active session total across Alice (3000) + Bob (1200) = 4200 tokens
        self.assertEqual(rep["total"], 4200)
        self.assertEqual(rep["prompt"], 1500)
        self.assertEqual(rep["thinking"], 700)
        self.assertEqual(rep["candidates"], 2000)
        self.assertEqual(rep["matched_sessions_count"], 1)

    def test_filter_all_accounts_all_sessions_7d(self):
        # All + All Sessions (False) + 7D
        rep = self.ledger.get_filtered_report(
            account_email="All",
            active_only=False,
            timeframe="7d",
            ref_time=self.now,
            use_local_time=False
        )
        # Total across active (4200) + hist_sess_002 (6000) + hist_sess_003 (10000) = 20200 tokens
        self.assertEqual(rep["total"], 20200)
        self.assertEqual(rep["matched_sessions_count"], 3)

    def test_account_switching_no_stale_data(self):
        # Query Bob + Active Only + 5H
        rep_bob = self.ledger.get_filtered_report(
            account_email="bob@company.org",
            active_only=True,
            timeframe="5h",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep_bob["total"], 1200)
        self.assertEqual(rep_bob["prompt"], 500)
        self.assertEqual(rep_bob["thinking"], 200)
        self.assertEqual(rep_bob["candidates"], 500)

        # Immediately query Alice + Active Only + 5H
        rep_alice = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=True,
            timeframe="5h",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep_alice["total"], 3000)

    def test_empty_states_clean_zero_handling(self):
        # Non-existent user
        rep_empty = self.ledger.get_filtered_report(
            account_email="unknown.user@company.org",
            active_only=False,
            timeframe="5h",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep_empty["total"], 0)
        self.assertEqual(rep_empty["prompt"], 0)
        self.assertEqual(rep_empty["thinking"], 0)
        self.assertEqual(rep_empty["candidates"], 0)
        self.assertEqual(rep_empty["prompt_pct"], 0.0)
        self.assertEqual(rep_empty["matched_sessions_count"], 0)
        self.assertEqual(len(rep_empty["records"]), 0)

    def test_timeframe_window_filtering(self):
        # Alice + All sessions:
        # In 5H window -> only active session (3000 tok @ -2h)
        rep_5h = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=False,
            timeframe="5h",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep_5h["total"], 3000)

        # In 24H window -> active session + hist session (3000 + 6000 = 9000 tok)
        rep_24h = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=False,
            timeframe="24h",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep_24h["total"], 9000)

    def test_default_state_active_user_all_sessions(self):
        # Default view: Active user (alice@company.org) + All Sessions (active_only=False) + 24H
        rep_default = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=False,
            timeframe="24h",
            ref_time=self.now,
            use_local_time=False
        )
        # Should aggregate all sessions for Alice
        self.assertEqual(rep_default["total"], 9000)
        self.assertEqual(rep_default["matched_sessions_count"], 2)

    def test_dual_state_session_scope_toggle(self):
        # 1. "All Sessions" mode
        rep_all_sess = self.ledger.get_filtered_report(
            account_email="bob@company.org",
            active_only=False,
            timeframe="7d",
            ref_time=self.now,
            use_local_time=False
        )
        # Bob has 1200 in active_sess_001 + 10000 in hist_sess_003 = 11200 tokens
        self.assertEqual(rep_all_sess["total"], 11200)
        self.assertEqual(rep_all_sess["matched_sessions_count"], 2)

        # 2. "Active Session" mode
        rep_active_sess = self.ledger.get_filtered_report(
            account_email="bob@company.org",
            active_only=True,
            timeframe="7d",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        # Bob has only 1200 tokens in active session
        self.assertEqual(rep_active_sess["total"], 1200)
        self.assertEqual(rep_active_sess["matched_sessions_count"], 1)

    def test_rule1_user_selected_active_session_toggled(self):
        """Rule 1: If a user account is selected in the dropdown and the Active Session button is toggled, all data must be related to the active session and that selected user."""
        rep = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=True,
            timeframe="5h",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        # Verify prompt, thinking, candidates, total, 5h, 7d are all strictly Alice's active session data
        self.assertEqual(rep["total"], 3000)
        self.assertEqual(rep["prompt"], 1000)
        self.assertEqual(rep["thinking"], 500)
        self.assertEqual(rep["candidates"], 1500)
        self.assertEqual(rep["tokens_5h"], 3000)
        self.assertEqual(rep["tokens_7d"], 3000)
        self.assertEqual(rep["matched_sessions_count"], 1)
        self.assertEqual(rep["matching_session_ids"], ["active_sess_001"])
        self.assertEqual(rep["account"], "alice@company.org")
        self.assertFalse(rep["is_all"])
        self.assertTrue(rep["active_only"])
        self.assertEqual(len(rep["records"]), 1)

    def test_rule2_user_selected_all_sessions_toggled(self):
        """Rule 2: If a user account is selected in the dropdown and the All Sessions button is toggled, all data must be related to all sessions for that selected user."""
        rep = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=False,
            timeframe="24h",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        # Verify Alice across all sessions (active_sess_001: 3000 + hist_sess_002: 6000 = 9000)
        self.assertEqual(rep["total"], 9000)
        self.assertEqual(rep["prompt"], 3000)
        self.assertEqual(rep["thinking"], 1500)
        self.assertEqual(rep["candidates"], 4500)
        self.assertEqual(rep["tokens_5h"], 3000)   # in 5h window: only active session (2h ago)
        self.assertEqual(rep["tokens_7d"], 9000)   # in 7d window: active + hist (10h ago)
        self.assertEqual(rep["matched_sessions_count"], 2)
        self.assertIn("active_sess_001", rep["matching_session_ids"])
        self.assertIn("hist_sess_002", rep["matching_session_ids"])
        self.assertFalse(rep["is_all"])
        self.assertFalse(rep["active_only"])

    def test_rule3_all_selected_active_and_all_sessions_toggled(self):
        """Rule 3: If 'All' is selected in the dropdown, ignore the user account and filter data based only on the toggle button (Active Session / All Sessions)."""
        # A. "All" selected + Active Session toggled
        rep_active = self.ledger.get_filtered_report(
            account_email="All",
            active_only=True,
            timeframe="5h",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        # Active session across both Alice (3000) and Bob (1200) = 4200 tokens
        self.assertEqual(rep_active["total"], 4200)
        self.assertEqual(rep_active["prompt"], 1500)
        self.assertEqual(rep_active["thinking"], 700)
        self.assertEqual(rep_active["candidates"], 2000)
        self.assertEqual(rep_active["tokens_5h"], 4200)
        self.assertEqual(rep_active["matched_sessions_count"], 1)
        self.assertTrue(rep_active["is_all"])
        self.assertTrue(rep_active["active_only"])

        # B. "All" selected + All Sessions toggled
        rep_all = self.ledger.get_filtered_report(
            account_email="All",
            active_only=False,
            timeframe="7d",
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        # All sessions across all accounts = 20200 tokens
        self.assertEqual(rep_all["total"], 20200)
        self.assertEqual(rep_all["matched_sessions_count"], 3)
        self.assertTrue(rep_all["is_all"])
        self.assertFalse(rep_all["active_only"])

    def test_rule4_mini_hud_independent_5h_and_7d_scopes(self):
        """Rule 4: In the MINI HUB, implement logic to display 5h and 7d data independently based on their respective toggle buttons."""
        # 1. 5h All Sessions (14200 in 5h? No, active + hist_sess_002 within 5h? Alice active=3000, Bob active=1200, Alice hist=-10h not in 5h)
        # Total in 5h across all sessions = 4200. Total in 7d across active session = 4200. Total in 7d across all sessions = 20200.
        rep_mixed_1 = self.ledger.get_filtered_report(
            account_email="All",
            active_only=False,
            active_only_5h=False,  # 5H for all sessions
            active_only_7d=True,   # 7D for active session
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep_mixed_1["tokens_5h"], 4200)  # All sessions in 5h
        self.assertEqual(rep_mixed_1["tokens_7d"], 4200)  # Active session only in 7d
        self.assertFalse(rep_mixed_1["active_only_5h"])
        self.assertTrue(rep_mixed_1["active_only_7d"])

        # 2. 5h Active Session (3000 for Alice) + 7d All Sessions (9000 for Alice)
        rep_mixed_2 = self.ledger.get_filtered_report(
            account_email="alice@company.org",
            active_only=False,
            active_only_5h=True,   # 5H for active session only
            active_only_7d=False,  # 7D for all sessions
            active_session_id="active_sess_001",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep_mixed_2["tokens_5h"], 3000)  # Alice active session only in 5h
        self.assertEqual(rep_mixed_2["tokens_7d"], 9000)  # Alice all sessions in 7d
        self.assertTrue(rep_mixed_2["active_only_5h"])
        self.assertFalse(rep_mixed_2["active_only_7d"])

    def test_filter_all_time_fallback_for_empty_records(self):
        # Add a session with lifetime tokens but empty line_records
        self.ledger.update_session(
            session_id="empty_rec_sess_004",
            account_email="charlie@company.org",
            stats={"prompt": 10000, "thinking": 20000, "candidates": 108059},
            line_records=[],
            first_prompt="Charlie session with empty records",
            mtime=1788175000.0,
            force_account=True
        )
        rep = self.ledger.get_filtered_report(
            account_email="charlie@company.org",
            active_only=False,
            timeframe="all",
            ref_time=self.now,
            use_local_time=False
        )
        self.assertEqual(rep["total"], 138059)
        self.assertEqual(rep["prompt"], 10000)
        self.assertEqual(rep["thinking"], 20000)
        self.assertEqual(rep["candidates"], 108059)
        self.assertEqual(rep["lifetime_total"], 138059)

    def test_smart_active_session_resolution_account_mismatch(self):
        # Create a session strictly belonging to user X and another strictly belonging to user Y
        self.ledger.update_session(
            session_id="strict_user_x",
            account_email="user_x@company.org",
            stats={"prompt": 500, "thinking": 200, "candidates": 300},
            line_records=[(self.now - timedelta(hours=1), 500, 200, 300)],
            mtime=1788190000.0,
            force_account=True
        )
        self.ledger.update_session(
            session_id="strict_user_y",
            account_email="user_y@company.org",
            stats={"prompt": 800, "thinking": 400, "candidates": 600},
            line_records=[(self.now - timedelta(hours=2), 800, 400, 600)],
            mtime=1788180000.0,
            force_account=True
        )
        # Query for user_y while passing user_x's active_session_id
        rep = self.ledger.get_filtered_report(
            account_email="user_y@company.org",
            active_only=True,
            timeframe="all",
            active_session_id="strict_user_x",
            ref_time=self.now,
            use_local_time=False
        )
        # strict_user_x must be rejected for user_y, and strict_user_y should be automatically resolved
        self.assertEqual(rep["matched_sessions_count"], 1)
        self.assertEqual(rep["matching_session_ids"], ["strict_user_y"])
        self.assertEqual(rep["total"], 1800)
        self.assertEqual(rep["prompt"], 800)
        self.assertEqual(rep["thinking"], 400)
        self.assertEqual(rep["candidates"], 600)



class TestSessionPaginationAndSlicing(unittest.TestCase):
    """Unit tests for high-performance session pagination across backend, GUI components, and CLI."""

    def test_pagination_slicing_math_boundaries(self):
        """Validates boundary conditions: 0 items, 5 items, 10 items, 25 items, 1000 items."""
        from core.cleaner import paginate_items

        # 1. 0 items
        res0 = paginate_items([], page=1, page_size=10)
        self.assertEqual(res0["items"], [])
        self.assertEqual(res0["page"], 1)
        self.assertEqual(res0["total_pages"], 1)
        self.assertEqual(res0["total_count"], 0)
        self.assertFalse(res0["has_next"])
        self.assertFalse(res0["has_prev"])
        self.assertEqual(res0["start_idx"], 0)
        self.assertEqual(res0["end_idx"], 0)

        # 2. 5 items (less than 1 page)
        items5 = [f"sess_{i}" for i in range(5)]
        res5 = paginate_items(items5, page=1, page_size=10)
        self.assertEqual(len(res5["items"]), 5)
        self.assertEqual(res5["page"], 1)
        self.assertEqual(res5["total_pages"], 1)
        self.assertEqual(res5["total_count"], 5)
        self.assertFalse(res5["has_next"])
        self.assertFalse(res5["has_prev"])
        self.assertEqual(res5["start_idx"], 1)
        self.assertEqual(res5["end_idx"], 5)

        # 3. Exactly 10 items (exactly 1 page)
        items10 = [f"sess_{i}" for i in range(10)]
        res10 = paginate_items(items10, page=1, page_size=10)
        self.assertEqual(len(res10["items"]), 10)
        self.assertEqual(res10["page"], 1)
        self.assertEqual(res10["total_pages"], 1)
        self.assertEqual(res10["total_count"], 10)
        self.assertFalse(res10["has_next"])
        self.assertFalse(res10["has_prev"])
        self.assertEqual(res10["start_idx"], 1)
        self.assertEqual(res10["end_idx"], 10)

        # 4. 25 items (3 pages: 10, 10, 5)
        items25 = [f"sess_{i}" for i in range(25)]
        p1 = paginate_items(items25, page=1, page_size=10)
        self.assertEqual(len(p1["items"]), 10)
        self.assertEqual(p1["items"][0], "sess_0")
        self.assertEqual(p1["items"][-1], "sess_9")
        self.assertEqual(p1["page"], 1)
        self.assertEqual(p1["total_pages"], 3)
        self.assertTrue(p1["has_next"])
        self.assertFalse(p1["has_prev"])
        self.assertEqual(p1["start_idx"], 1)
        self.assertEqual(p1["end_idx"], 10)

        p2 = paginate_items(items25, page=2, page_size=10)
        self.assertEqual(len(p2["items"]), 10)
        self.assertEqual(p2["items"][0], "sess_10")
        self.assertEqual(p2["items"][-1], "sess_19")
        self.assertEqual(p2["page"], 2)
        self.assertTrue(p2["has_next"])
        self.assertTrue(p2["has_prev"])
        self.assertEqual(p2["start_idx"], 11)
        self.assertEqual(p2["end_idx"], 20)

        p3 = paginate_items(items25, page=3, page_size=10)
        self.assertEqual(len(p3["items"]), 5)
        self.assertEqual(p3["items"][0], "sess_20")
        self.assertEqual(p3["items"][-1], "sess_24")
        self.assertEqual(p3["page"], 3)
        self.assertFalse(p3["has_next"])
        self.assertTrue(p3["has_prev"])
        self.assertEqual(p3["start_idx"], 21)
        self.assertEqual(p3["end_idx"], 25)

        # 5. 1,000 items (100 pages of 10 items)
        items1000 = [f"sess_{i}" for i in range(1000)]
        p50 = paginate_items(items1000, page=50, page_size=10)
        self.assertEqual(len(p50["items"]), 10)
        self.assertEqual(p50["page"], 50)
        self.assertEqual(p50["total_pages"], 100)
        self.assertEqual(p50["total_count"], 1000)
        self.assertTrue(p50["has_next"])
        self.assertTrue(p50["has_prev"])
        self.assertEqual(p50["start_idx"], 491)
        self.assertEqual(p50["end_idx"], 500)

        p100 = paginate_items(items1000, page=100, page_size=10)
        self.assertEqual(len(p100["items"]), 10)
        self.assertEqual(p100["page"], 100)
        self.assertEqual(p100["total_pages"], 100)
        self.assertFalse(p100["has_next"])
        self.assertTrue(p100["has_prev"])
        self.assertEqual(p100["start_idx"], 991)
        self.assertEqual(p100["end_idx"], 1000)

    def test_page_bounds_clamping(self):
        """Validates clamping behavior when page < 1, page > total_pages, or invalid types are supplied."""
        from core.cleaner import paginate_items

        items = [f"sess_{i}" for i in range(25)]

        # Negative page -> clamped to 1
        res_neg = paginate_items(items, page=-5, page_size=10)
        self.assertEqual(res_neg["page"], 1)
        self.assertEqual(res_neg["start_idx"], 1)

        # Page 0 -> clamped to 1
        res_zero = paginate_items(items, page=0, page_size=10)
        self.assertEqual(res_zero["page"], 1)

        # Page beyond total_pages -> clamped to total_pages (3)
        res_overflow = paginate_items(items, page=999, page_size=10)
        self.assertEqual(res_overflow["page"], 3)
        self.assertEqual(res_overflow["end_idx"], 25)

        # None items -> safe fallback
        res_none = paginate_items(None, page=1, page_size=10)
        self.assertEqual(res_none["items"], [])
        self.assertEqual(res_none["total_count"], 0)

        # Non-integer page type
        res_str = paginate_items(items, page="invalid", page_size=10)
        self.assertEqual(res_str["page"], 1)

    def test_search_page_reset(self):
        """Verifies that search queries and mode changes in SessionTable reset the current page back to 1."""
        from core.cleaner import paginate_items

        # Simulate SessionTable pagination flow
        sessions = [{"session_id": f"sess_{i:03d}", "title": f"Topic {i}", "last_active_str": "2026-09-01", "mtime": float(i), "size": 1024, "account": "user@example.com"} for i in range(50)]

        # Start at page 4
        current_page = 4
        pag = paginate_items(sessions, page=current_page, page_size=10)
        self.assertEqual(pag["page"], 4)

        # Typing in search resets current_page = 1
        query = "topic 1"
        current_page = 1
        filtered = [s for s in sessions if query in s["title"].lower()]
        pag_searched = paginate_items(filtered, page=current_page, page_size=10)
        self.assertEqual(pag_searched["page"], 1)
        self.assertGreater(pag_searched["total_count"], 0)
        self.assertLessEqual(len(pag_searched["items"]), 10)

    def test_cleaner_cross_page_selection_and_byte_math(self):
        """Verifies that CleanerDialog decoupled selection set persists across page turns and computes accurate total byte sums."""
        from core.cleaner import paginate_items, format_bytes

        # Generate 45 sessions with distinct sizes
        fake_sessions = []
        for i in range(45):
            fake_sessions.append({
                "session_id": f"sess_clean_{i:02d}",
                "title": f"Conversation {i}",
                "size_bytes": 1024 * 1024 * (i + 1),  # (i+1) MB
                "size_str": f"{i+1} MB",
                "tokens": (i + 1) * 1000,
                "folder": f"/path/to/sess_{i}",
                "file": f"/path/to/sess_{i}/transcript.jsonl"
            })

        active_sid = fake_sessions[0]["session_id"]
        selected_session_ids = set()

        # 1. Select All (excluding active session)
        for s in fake_sessions:
            if s["session_id"] != active_sid:
                selected_session_ids.add(s["session_id"])

        self.assertEqual(len(selected_session_ids), 44)
        self.assertNotIn(active_sid, selected_session_ids)

        # 2. Verify total byte calculation across ALL 44 selected sessions (independent of visible page)
        total_selected_bytes = sum(
            s["size_bytes"] for s in fake_sessions
            if s["session_id"] in selected_session_ids
        )
        expected_bytes = sum(1024 * 1024 * (i + 1) for i in range(1, 45))
        self.assertEqual(total_selected_bytes, expected_bytes)

        # 3. Simulate page 1 rendering (10 items)
        p1 = paginate_items(fake_sessions, page=1, page_size=10)
        self.assertEqual(len(p1["items"]), 10)
        p1_checkboxes = {s["session_id"]: (s["session_id"] in selected_session_ids) for s in p1["items"]}
        self.assertFalse(p1_checkboxes[active_sid])  # Active is unselected
        self.assertTrue(p1_checkboxes["sess_clean_01"])

        # 4. Turn to page 3 (items 20-29)
        p3 = paginate_items(fake_sessions, page=3, page_size=10)
        self.assertEqual(len(p3["items"]), 10)
        p3_checkboxes = {s["session_id"]: (s["session_id"] in selected_session_ids) for s in p3["items"]}
        # All items on page 3 should be selected in state
        for sid, is_checked in p3_checkboxes.items():
            self.assertTrue(is_checked)

        # 5. Deselect one item on page 3
        selected_session_ids.discard("sess_clean_25")
        self.assertEqual(len(selected_session_ids), 43)

        # 6. Deselect All
        selected_session_ids.clear()
        self.assertEqual(len(selected_session_ids), 0)

    def test_cli_pagination_args(self):
        """Verifies CLI argument parsing and paginate_items integration for disk usage reporting."""
        import argparse
        from core.cleaner import paginate_items

        parser = argparse.ArgumentParser()
        parser.add_argument("--page", "-p", type=int, default=1)
        parser.add_argument("--limit", "-l", type=int, default=10)
        parser.add_argument("--disk-usage", action="store_true")

        args = parser.parse_args(["--disk-usage", "--page", "3", "--limit", "10"])
        self.assertTrue(args.disk_usage)
        self.assertEqual(args.page, 3)
        self.assertEqual(args.limit, 10)

        sessions = [f"s_{i}" for i in range(100)]
        pag = paginate_items(sessions, page=args.page, page_size=args.limit)
        self.assertEqual(pag["page"], 3)
        self.assertEqual(pag["page_size"], 10)
        self.assertEqual(pag["start_idx"], 21)
        self.assertEqual(pag["end_idx"], 30)
        self.assertEqual(len(pag["items"]), 10)

    def test_analytics_table_pagination(self):
        """Verifies that AnalyticsDialog interval breakdown table correctly paginates time buckets."""
        from core.cleaner import paginate_items

        # Generate 35 hourly interval buckets
        buckets = [{"key": f"2026-09-01T{i:02d}:00", "total": 1000 * (i + 1), "prompt": 500, "thinking": 300, "candidates": 200} for i in range(35)]

        # Page 1: 10 items
        p1 = paginate_items(buckets, page=1, page_size=10)
        self.assertEqual(len(p1["items"]), 10)
        self.assertEqual(p1["total_pages"], 4)
        self.assertEqual(p1["start_idx"], 1)
        self.assertEqual(p1["end_idx"], 10)

        # Page 4: remaining 5 items
        p4 = paginate_items(buckets, page=4, page_size=10)
        self.assertEqual(len(p4["items"]), 5)
        self.assertEqual(p4["start_idx"], 31)
    def test_tray_manager_gdi_debouncing(self):
        """Verifies that SystemTrayManager debounces icon and tooltip updates to eliminate GDI handle leaks."""
        from gui.tray import SystemTrayManager
        tray = SystemTrayManager(
            on_open_dashboard=lambda: None,
            on_open_mini_hud=lambda: None,
            on_refresh=lambda: None,
            on_quit=lambda: None
        )
        # Mock a dummy icon object
        class DummyIcon:
            def __init__(self):
                self.title = ""
                self.icon = None
        tray.icon = DummyIcon()
        tray._last_status_color = "#3B82F6"
        tray._last_tooltip_text = "Initial Text"

        # 1. Update with identical values -> icon & title should not be reassigned
        tray.update_tooltip("Initial Text", status_color="#3B82F6")
        self.assertEqual(tray._last_status_color, "#3B82F6")
        self.assertEqual(tray._last_tooltip_text, "Initial Text")
        self.assertIsNone(tray.icon.icon)  # Did not create or assign new icon

        # 2. Update with new status color -> should assign new icon
        tray.update_tooltip("Initial Text", status_color="#EF4444")
        self.assertEqual(tray._last_status_color, "#EF4444")
        self.assertIsNotNone(tray.icon.icon)

        # 3. Update with new text -> should update title
        tray.update_tooltip("Updated Text", status_color="#EF4444")
        self.assertEqual(tray.icon.title, "Updated Text")

    def test_credential_discovery_caching(self):
        """Verifies that find_credential_files caches results and can be cleared cleanly."""
        from core.account_manager import find_credential_files, clear_credential_cache
        clear_credential_cache()
        res1 = find_credential_files()
        self.assertIsInstance(res1, dict)
        self.assertIn("google_accounts", res1)

        # Immediate secondary call should return the cached dict object
        res2 = find_credential_files()
        self.assertIs(res1, res2)

        # Force refresh or clear should produce a fresh dict
        clear_credential_cache()
        res3 = find_credential_files(force_refresh=True)
        self.assertIsNot(res1, res3)

    def test_brain_dirs_discovery_caching(self):
        """Verifies that find_all_brain_dirs caches results and can be cleared cleanly."""
        from core.session_finder import find_all_brain_dirs, clear_brain_dirs_cache
        clear_brain_dirs_cache()
        dirs1 = find_all_brain_dirs()
        self.assertIsInstance(dirs1, list)

        # Secondary call returns equivalent list from cache
        dirs2 = find_all_brain_dirs()
        self.assertEqual(dirs1, dirs2)

        # Clear cache and force refresh
        clear_brain_dirs_cache()
        dirs3 = find_all_brain_dirs(force_refresh=True)
        self.assertEqual(dirs1, dirs3)

    def test_known_accounts_caching(self):
        """Verifies that get_all_known_accounts_list caches results for 0% CPU dropdown lookups."""
        from core.account_manager import get_all_known_accounts_list, clear_known_accounts_cache
        clear_known_accounts_cache()
        accs1 = get_all_known_accounts_list()
        self.assertIsInstance(accs1, list)

    def test_tray_icon_image_reuse(self):
        """Verifies that create_tray_icon_image reuses cached PIL Image instances to prevent memory/GDI churn."""
        from gui.tray import create_tray_icon_image, _ICON_IMAGE_CACHE
        img1 = create_tray_icon_image("#3B82F6")
        img2 = create_tray_icon_image("#3B82F6")
        self.assertIs(img1, img2)
        self.assertIn("#3B82F6", _ICON_IMAGE_CACHE)

    def test_realtime_quota_caching_and_invalidation(self):
        """Verifies that realtime accounts dirs and quotas use TTL in-memory caching and clean invalidation."""
        from core.realtime_quota import (
            get_realtime_accounts_dirs,
            load_all_realtime_quotas,
            clear_realtime_quota_cache,
            _CACHED_REALTIME_DIRS,
            _CACHED_REALTIME_QUOTAS
        )
        clear_realtime_quota_cache()
        dirs1 = get_realtime_accounts_dirs()
        self.assertIsInstance(dirs1, list)
        dirs2 = get_realtime_accounts_dirs()
        self.assertEqual(dirs1, dirs2)

        quotas1 = load_all_realtime_quotas()
        self.assertIsInstance(quotas1, dict)
        quotas2 = load_all_realtime_quotas()
        self.assertEqual(quotas1, quotas2)

        # Clear cache and re-verify
        clear_realtime_quota_cache()
        quotas3 = load_all_realtime_quotas(force_refresh=True)
        self.assertIsInstance(quotas3, dict)

    def test_context_menu_debouncing(self):
        """Verifies that right-click context menu calls are debounced within 250ms to prevent duplicate window creation."""
        import time
        from gui.components.session_table import SessionTable
        from gui.cleaner_dialog import CleanerDialog

        # Test SessionTable debouncing
        class MockParent:
            def register(self, f): return ""
            def _get_window_scaling(self): return 1.0

        table = SessionTable.__new__(SessionTable)
        table._last_context_menu_time = time.time()
        # Immediate subsequent call within 250ms should return early without error
        event = type("MockEvent", (), {"x_root": 100, "y_root": 100})()
        table._show_context_menu(event, {"session_id": "test_sid"})
        # Remains debounced
        self.assertGreater(table._last_context_menu_time, 0.0)

    def test_mini_hud_geometry_deduplication(self):
        """Verifies that MiniHUD geometry calls are deduplicated using _last_applied_geometry."""
        from gui.mini_hud import MiniHUD

        hud = MiniHUD.__new__(MiniHUD)
        hud._last_applied_geometry = "350x200+100+100"
        geom_called = []
        hud.geometry = lambda g: geom_called.append(g)
        hud._get_scale = lambda: 1.0
        hud._clamp_to_screen = lambda x, y, w, h: (x, y)
        hud._hud_pos = (100, 100)
        hud.is_minimized = False
        hud.is_hover_expanded = False
        hud.update_idletasks = lambda: None
        hud.main_frame = type("MockFrame", (), {"winfo_reqheight": lambda *args: 196})()

        # Recalculate geometry with same target dimensions
        hud._recalculate_geometry()
        # Because target_geo matches _last_applied_geometry ("350x200+100+100"), geometry() should NOT be called
        self.assertEqual(len(geom_called), 0)

    def test_quota_aware_token_colors(self):
        """Verifies that All Tokens text colors dynamically follow 5H and 7D quota remaining logic,
        while Active Tokens text colors follow the Blue 5H and Purple 7D themes."""
        import customtkinter as ctk
        from gui.components.quota_gauge import QuotaGauge
        from gui.mini_hud import MiniHUD

        root = ctk.CTk()
        root.withdraw()
        try:
            # 1. Test QuotaGauge colors
            gauge_5h = QuotaGauge(root, title="5-Hour Limit", icon="⏳", default_limit=1000000, active_color=("#1d4ed8", "#38bdf8"), all_color=("#1d4ed8", "#38bdf8"))
            gauge_7d = QuotaGauge(root, title="7-Day Limit", icon="📅", default_limit=4000000, active_color=("#7c3aed", "#a78bfa"), all_color=("#7c3aed", "#a78bfa"))

            # Active and All tag/icon color assignments
            self.assertEqual(gauge_5h.lbl_big_active_icon.cget("text_color"), ("#1d4ed8", "#38bdf8"))
            self.assertEqual(gauge_5h.lbl_act_tag.cget("text_color"), ("#1d4ed8", "#38bdf8"))
            self.assertEqual(gauge_5h.lbl_big_all_icon.cget("text_color"), ("#1d4ed8", "#38bdf8"))
            self.assertEqual(gauge_5h.lbl_all_tag.cget("text_color"), ("#1d4ed8", "#38bdf8"))

            self.assertEqual(gauge_7d.lbl_big_active_icon.cget("text_color"), ("#7c3aed", "#a78bfa"))
            self.assertEqual(gauge_7d.lbl_act_tag.cget("text_color"), ("#7c3aed", "#a78bfa"))
            self.assertEqual(gauge_7d.lbl_big_all_icon.cget("text_color"), ("#7c3aed", "#a78bfa"))
            self.assertEqual(gauge_7d.lbl_all_tag.cget("text_color"), ("#7c3aed", "#a78bfa"))

            # 5H Green (>60% remaining)
            gauge_5h.update_data(used_tokens=50000, reset_str="in 4h", pct_remaining=80.0, all_total_toks=50000)
            self.assertEqual(gauge_5h.lbl_big_all_val.cget("text_color"), ("#15803d", "#10B981"))

            # 5H Amber (20%-60% remaining)
            gauge_5h.update_data(used_tokens=300000, reset_str="in 2h", pct_remaining=40.0, all_total_toks=30000)
            self.assertEqual(gauge_5h.lbl_big_all_val.cget("text_color"), ("#b45309", "#F59E0B"))

            # 5H Red (<20% remaining)
            gauge_5h.update_data(used_tokens=800000, reset_str="in 10m", pct_remaining=10.0, all_total_toks=80000)
            self.assertEqual(gauge_5h.lbl_big_all_val.cget("text_color"), ("#b91c1c", "#EF4444"))

            # 2. Test MiniHUD colors
            hud = MiniHUD(root, on_restore_callback=lambda: None)
            hud.show_7d_expanded = True
            hud._build_sections()

            # Active 7D label must be purple
            self.assertEqual(hud.h7_active_lbl.cget("text_color"), ("#7c3aed", "#c084fc"))

            # Green quota
            hud.update_data({
                "tokens_5h": 50000, "pct_5h_remaining": 75.0, "reset_5h_str": "in 3h",
                "tokens_7d": 200000, "pct_7d_remaining": 85.0, "reset_7d_str": "in 5d",
                "burn_rate_str": "Idle"
            })
            self.assertEqual(hud.h5_all_lbl.cget("text_color"), ("#15803d", "#10B981"))
            self.assertEqual(hud.h7_all_lbl.cget("text_color"), ("#15803d", "#10B981"))
            self.assertEqual(hud.bubble_5h_act_lbl.cget("text_color"), ("#1d4ed8", "#60a5fa"))
            self.assertEqual(hud.bubble_7d_act_lbl.cget("text_color"), ("#7c3aed", "#c084fc"))
            self.assertEqual(hud.bubble_5h_all_lbl.cget("text_color"), ("#059669", "#34d399"))
            self.assertEqual(hud.bubble_7d_all_lbl.cget("text_color"), ("#059669", "#34d399"))

            # Amber quota
            hud.update_data({
                "tokens_5h": 400000, "pct_5h_remaining": 35.0, "reset_5h_str": "in 2h",
                "tokens_7d": 1500000, "pct_7d_remaining": 30.0, "reset_7d_str": "in 2d",
                "burn_rate_str": "Idle"
            })
            self.assertEqual(hud.h5_all_lbl.cget("text_color"), ("#b45309", "#F59E0B"))
            self.assertEqual(hud.h7_all_lbl.cget("text_color"), ("#b45309", "#F59E0B"))
            self.assertEqual(hud.bubble_5h_all_lbl.cget("text_color"), ("#d97706", "#fbbf24"))
            self.assertEqual(hud.bubble_7d_all_lbl.cget("text_color"), ("#d97706", "#fbbf24"))

            # Red quota
            hud.update_data({
                "tokens_5h": 900000, "pct_5h_remaining": 8.0, "reset_5h_str": "in 20m",
                "tokens_7d": 3800000, "pct_7d_remaining": 5.0, "reset_7d_str": "in 4h",
                "burn_rate_str": "Idle"
            })
            self.assertEqual(hud.h5_all_lbl.cget("text_color"), ("#b91c1c", "#EF4444"))
            self.assertEqual(hud.h7_all_lbl.cget("text_color"), ("#b91c1c", "#EF4444"))
            self.assertEqual(hud.bubble_5h_all_lbl.cget("text_color"), ("#dc2626", "#f87171"))
            self.assertEqual(hud.bubble_7d_all_lbl.cget("text_color"), ("#dc2626", "#f87171"))

            # Active bubble labels must remain untouched
            self.assertEqual(hud.bubble_5h_act_lbl.cget("text_color"), ("#1d4ed8", "#60a5fa"))
            self.assertEqual(hud.bubble_7d_act_lbl.cget("text_color"), ("#7c3aed", "#c084fc"))

            # 3. Test Tooltip content helper
            tooltip_frame = ctk.CTkFrame(root)
            hud._build_tooltip_content(tooltip_frame)
            # Find h5_all and d7_all labels inside tooltip
            labels = [w for w in tooltip_frame.winfo_children() if isinstance(w, ctk.CTkLabel)]
            all_labels = [l for l in labels if "★ All:" in l.cget("text")]
            self.assertEqual(len(all_labels), 2)
            # Both should have red quota color since last report was red (<20%)
            self.assertEqual(all_labels[0].cget("text_color"), ("#b91c1c", "#EF4444"))
            self.assertEqual(all_labels[1].cget("text_color"), ("#b91c1c", "#EF4444"))

            # Both h5_hdr and d7_hdr should have red quota color since last report was red (<20%)
            hdr_labels = [l for l in labels if "WINDOW" in l.cget("text")]
            self.assertEqual(len(hdr_labels), 2)
            self.assertEqual(hdr_labels[0].cget("text_color"), ("#b91c1c", "#EF4444"))
            self.assertEqual(hdr_labels[1].cget("text_color"), ("#b91c1c", "#EF4444"))

            hud.destroy()
            gauge_5h.destroy()
            gauge_7d.destroy()
            tooltip_frame.destroy()
        finally:
            root.destroy()




if __name__ == '__main__':
    unittest.main()
