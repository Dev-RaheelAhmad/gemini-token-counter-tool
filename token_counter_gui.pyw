#!/usr/bin/env python3
"""
Gemini Token Counter - Desktop GUI Entry Point (Silent / Windowless)
"""
import os
import sys

# Add project root to sys.path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from token_counter_gui import main

if __name__ == "__main__":
    main()
