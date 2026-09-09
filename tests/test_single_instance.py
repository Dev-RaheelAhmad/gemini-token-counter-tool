import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

# Add project root to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from core.single_instance import SingleInstanceManager, RESTORE_COMMAND


class TestSingleInstance(unittest.TestCase):
    def test_first_instance_acquires_successfully(self):
        mgr = SingleInstanceManager(app_name="test-first-instance")
        try:
            acquired = mgr.acquire_or_activate()
            self.assertTrue(acquired)
            self.assertTrue(mgr._is_primary)
        finally:
            mgr.release()
            self.assertTrue(mgr._released)

    def test_second_instance_returns_false_and_signals_callback(self):
        mgr1 = SingleInstanceManager(app_name="test-second-instance")
        callback_called = []

        try:
            self.assertTrue(mgr1.acquire_or_activate())
            mgr1.set_restore_callback(lambda: callback_called.append(True))

            # Second instance with same app name
            mgr2 = SingleInstanceManager(app_name="test-second-instance")
            try:
                acquired2 = mgr2.acquire_or_activate()
                self.assertFalse(acquired2)
            finally:
                mgr2.release()

            # Allow brief moment for socket message transmission
            time.sleep(0.1)
            self.assertEqual(len(callback_called), 1)
            self.assertTrue(callback_called[0])

        finally:
            mgr1.release()

    def test_port_file_lifecycle(self):
        mgr = SingleInstanceManager(app_name="test-port-file")
        try:
            self.assertTrue(mgr.acquire_or_activate())
            self.assertTrue(mgr._port_file.exists())
            port = int(mgr._port_file.read_text(encoding="utf-8").strip())
            self.assertGreater(port, 0)
        finally:
            mgr.release()
            self.assertFalse(mgr._port_file.exists())

    def test_posix_fallback_acquisition(self):
        mgr1 = SingleInstanceManager(app_name="test-posix-mode")
        called = []
        with patch("sys.platform", "linux"):
            try:
                self.assertTrue(mgr1.acquire_or_activate())
                mgr1.set_restore_callback(lambda: called.append(True))

                mgr2 = SingleInstanceManager(app_name="test-posix-mode")
                try:
                    self.assertFalse(mgr2.acquire_or_activate())
                finally:
                    mgr2.release()

                time.sleep(0.1)
                self.assertEqual(len(called), 1)
            finally:
                mgr1.release()

    def test_activate_existing_window_windows(self):
        mgr = SingleInstanceManager(app_name="test-win-activate")
        with patch("sys.platform", "win32"), \
             patch("ctypes.windll.user32.FindWindowW", return_value=12345) as mock_find, \
             patch("ctypes.windll.user32.ShowWindow") as mock_show, \
             patch("ctypes.windll.user32.SetForegroundWindow") as mock_foreground:

            mgr._activate_existing_window()
            mock_find.assert_called_once_with(None, "Gemini Token Counter - Desktop Monitor")
            mock_show.assert_called_once_with(12345, 9)
            mock_foreground.assert_called_once_with(12345)

    def test_idempotent_release(self):
        mgr = SingleInstanceManager(app_name="test-idempotent-release")
        mgr.release()
        mgr.release()
        self.assertTrue(mgr._released)


if __name__ == "__main__":
    unittest.main()
