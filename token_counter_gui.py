#!/usr/bin/env python3
"""
Gemini Token Counter - Windows Desktop GUI & Live Monitor
"""
import os
import sys

root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from gui.app import GeminiTokenCounterApp


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            myappid = "google.gemini.tokenmonitor.v1"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    app = GeminiTokenCounterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
