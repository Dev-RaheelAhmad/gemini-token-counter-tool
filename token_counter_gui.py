#!/usr/bin/env python3
"""
Gemini Token Counter - Desktop GUI & Live Monitor
"""
import os
import sys

# Add project root to sys.path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from core.single_instance import SingleInstanceManager
from gui.app import GeminiTokenCounterApp


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            myappid = "google.gemini.tokenmonitor.v1"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    # Ensure single instance
    single_instance = SingleInstanceManager(app_name="gemini-token-counter")
    if not single_instance.acquire_or_activate():
        # Another instance is already running; it has been signaled to restore and focus.
        sys.exit(0)

    app = GeminiTokenCounterApp()
    app.single_instance = single_instance
    single_instance.set_restore_callback(lambda: app._safe_after(0, app.show_dashboard))
    try:
        app.mainloop()
    finally:
        single_instance.release()


if __name__ == "__main__":
    main()
