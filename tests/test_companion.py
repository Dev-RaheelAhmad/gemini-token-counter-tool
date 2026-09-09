import os
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from core.companion import (
    get_default_antigravity_tools_path,
    resolve_antigravity_tools_path,
    is_antigravity_tools_installed,
    is_antigravity_tools_running,
    launch_antigravity_tools,
    get_antigravity_tools_status,
)
from core.config import config


class TestCompanionApp(unittest.TestCase):
    def setUp(self):
        self._orig_auto_launch = config.get("auto_launch_antigravity_tools")
        self._orig_path = config.get("antigravity_tools_path")

    def tearDown(self):
        config.set("auto_launch_antigravity_tools", self._orig_auto_launch, save_now=False)
        config.set("antigravity_tools_path", self._orig_path, save_now=False)

    def test_default_path_resolution_localappdata(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\MockAppData\Local"}):
            p = get_default_antigravity_tools_path()
            self.assertEqual(str(p).replace("/", "\\"), r"C:\MockAppData\Local\Antigravity Tools\antigravity-tools.exe")

    def test_default_path_resolution_userprofile_fallback(self):
        env = dict(os.environ)
        env.pop("LOCALAPPDATA", None)
        env["USERPROFILE"] = r"C:\MockUser"
        with patch.dict(os.environ, env, clear=True):
            p = get_default_antigravity_tools_path()
            self.assertEqual(str(p).replace("/", "\\"), r"C:\MockUser\AppData\Local\Antigravity Tools\antigravity-tools.exe")

    def test_resolve_custom_path_argument(self):
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            resolved = resolve_antigravity_tools_path(custom_path=str(tmp_path))
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved.resolve(), tmp_path.resolve())
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_resolve_config_path(self):
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            config.set("antigravity_tools_path", str(tmp_path), save_now=False)
            resolved = resolve_antigravity_tools_path()
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved.resolve(), tmp_path.resolve())
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_resolve_not_found(self):
        config.set("antigravity_tools_path", r"C:\NonExistentDir\NonExistentTool.exe", save_now=False)
        with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\EmptyPathXYZ", "ProgramFiles": r"C:\EmptyPathXYZ"}):
            with patch("shutil.which", return_value=None):
                resolved = resolve_antigravity_tools_path(r"C:\NoSuchDir\NoSuchFile.exe")
                # When passed an explicit non-existent file, it falls through to candidates, which also don't exist
                # If the host machine happens to have antigravity-tools.exe installed at default location, default_p exists
                # So we also patch get_default_antigravity_tools_path to a non-existent path
                with patch("core.companion.get_default_antigravity_tools_path", return_value=Path(r"C:\Fake\none.exe")):
                    resolved2 = resolve_antigravity_tools_path(r"C:\NoSuchDir\NoSuchFile.exe")
                    self.assertIsNone(resolved2)
                    self.assertFalse(is_antigravity_tools_installed(r"C:\NoSuchDir\NoSuchFile.exe"))

    def test_is_antigravity_tools_installed(self):
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            self.assertTrue(is_antigravity_tools_installed(str(tmp_path)))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_is_antigravity_tools_running_mock(self):
        with patch("sys.platform", "linux"):
            running, pid = is_antigravity_tools_running()
            self.assertFalse(running)
            self.assertIsNone(pid)

    def test_launch_disabled(self):
        config.set("auto_launch_antigravity_tools", False, save_now=False)
        success, msg = launch_antigravity_tools(force=False)
        self.assertFalse(success)
        self.assertEqual(msg, "disabled")

    def test_launch_already_running(self):
        config.set("auto_launch_antigravity_tools", True, save_now=False)
        with patch("core.companion.is_antigravity_tools_running", return_value=(True, 12345)):
            success, msg = launch_antigravity_tools(force=False)
            self.assertTrue(success)
            self.assertEqual(msg, "already_running")

    def test_launch_not_installed(self):
        config.set("auto_launch_antigravity_tools", True, save_now=False)
        with patch("core.companion.is_antigravity_tools_running", return_value=(False, None)):
            with patch("core.companion.resolve_antigravity_tools_path", return_value=None):
                success, msg = launch_antigravity_tools(force=True)
                self.assertFalse(success)
                self.assertEqual(msg, "not_installed")

    def test_launch_success_spawn(self):
        config.set("auto_launch_antigravity_tools", True, save_now=False)
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            with patch("core.companion.is_antigravity_tools_running", return_value=(False, None)):
                with patch("subprocess.Popen") as mock_popen:
                    mock_proc = MagicMock()
                    mock_proc.pid = 9999
                    mock_popen.return_value = mock_proc

                    success, msg = launch_antigravity_tools(custom_path=str(tmp_path), force=True)
                    self.assertTrue(success)
                    self.assertEqual(msg, "launched")
                    self.assertTrue(mock_popen.called)
                    args, kwargs = mock_popen.call_args
                    self.assertEqual(args[0], [str(tmp_path)])
                    self.assertEqual(kwargs["cwd"], str(tmp_path.parent))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_get_status_structure(self):
        with patch("core.companion.is_antigravity_tools_running", return_value=(True, 45678)):
            with patch("core.companion.resolve_antigravity_tools_path", return_value=Path(r"C:\Mock\antigravity-tools.exe")):
                st = get_antigravity_tools_status()
                self.assertTrue(st["installed"])
                self.assertTrue(st["running"])
                self.assertEqual(st["pid"], 45678)
                self.assertIn("antigravity-tools.exe", st["path"])
                self.assertIn("auto_launch_enabled", st)

    def test_gui_companion_warning_banner(self):
        from gui.app import GeminiTokenCounterApp
        app = MagicMock()
        app.winfo_exists.return_value = True
        app.companion_banner_frame = None
        app.middle_container = MagicMock()
        app.middle_container.winfo_exists.return_value = True
        app.main_container = MagicMock()

        with patch("customtkinter.CTkFrame") as mock_frame, \
             patch("customtkinter.CTkLabel"), \
             patch("customtkinter.CTkButton"), \
             patch("customtkinter.CTkFont"):
            mock_banner_instance = MagicMock()
            mock_frame.return_value = mock_banner_instance

            GeminiTokenCounterApp._show_companion_warning_banner(app)
            self.assertIsNotNone(app.companion_banner_frame)

            GeminiTokenCounterApp._dismiss_companion_warning_banner(app)
            self.assertIsNone(app.companion_banner_frame)

    def test_gui_launch_companion_on_initial_start_already_running(self):
        from gui.app import GeminiTokenCounterApp
        app = MagicMock()
        app._companion_startup_triggered = False
        config.set("auto_launch_antigravity_tools", True, save_now=False)

        with patch("core.companion.is_antigravity_tools_running", return_value=(True, 9999)), \
             patch("threading.Thread") as mock_thread:
            GeminiTokenCounterApp._launch_companion_on_initial_start(app)
            self.assertTrue(app._companion_startup_triggered)
            app._dismiss_companion_warning_banner.assert_called_once()
            app._show_companion_warning_banner.assert_not_called()
            mock_thread.assert_not_called()

    def test_gui_launch_companion_on_initial_start_not_installed(self):
        from gui.app import GeminiTokenCounterApp
        app = MagicMock()
        app._companion_startup_triggered = False
        config.set("auto_launch_antigravity_tools", True, save_now=False)

        with patch("core.companion.is_antigravity_tools_running", return_value=(False, None)), \
             patch("core.companion.is_antigravity_tools_installed", return_value=False), \
             patch("threading.Thread") as mock_thread:
            GeminiTokenCounterApp._launch_companion_on_initial_start(app)
            self.assertTrue(app._companion_startup_triggered)
            app._show_companion_warning_banner.assert_called_once()
            mock_thread.assert_not_called()

    def test_gui_launch_companion_on_initial_start_not_running_installed(self):
        from gui.app import GeminiTokenCounterApp
        app = MagicMock()
        app._companion_startup_triggered = False
        config.set("auto_launch_antigravity_tools", True, save_now=False)

        with patch("core.companion.is_antigravity_tools_running", return_value=(False, None)), \
             patch("core.companion.is_antigravity_tools_installed", return_value=True), \
             patch("threading.Thread") as mock_thread:
            mock_instance = MagicMock()
            mock_thread.return_value = mock_instance

            GeminiTokenCounterApp._launch_companion_on_initial_start(app)
            self.assertTrue(app._companion_startup_triggered)
            app._dismiss_companion_warning_banner.assert_called_once()
            mock_thread.assert_called_once()
            mock_instance.start.assert_called_once()

    def test_gui_launch_companion_strictly_once(self):
        from gui.app import GeminiTokenCounterApp
        app = MagicMock()
        app._companion_startup_triggered = True  # Already triggered

        with patch("core.companion.is_antigravity_tools_running") as mock_running:
            GeminiTokenCounterApp._launch_companion_on_initial_start(app)
            mock_running.assert_not_called()


if __name__ == "__main__":
    unittest.main()
