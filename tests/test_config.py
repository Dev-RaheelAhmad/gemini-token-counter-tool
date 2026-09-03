import os
import sys
import unittest
import tempfile
import json
from pathlib import Path

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from core.config import ConfigManager, get_config_dir, DEFAULT_CONFIG


class TestConfig(unittest.TestCase):
    def test_default_config_keys(self):
        self.assertIn("limit_5h", DEFAULT_CONFIG)
        self.assertIn("limit_7d", DEFAULT_CONFIG)
        self.assertIn("refresh_interval_sec", DEFAULT_CONFIG)
        self.assertIn("theme", DEFAULT_CONFIG)

    def test_config_get_set(self):
        cm = ConfigManager()
        cm.set("test_key", "test_value", save_now=False)
        self.assertEqual(cm.get("test_key"), "test_value")
        self.assertEqual(cm.get("nonexistent_key", "fallback"), "fallback")

    def test_get_config_dir(self):
        cfg_dir = get_config_dir()
        self.assertIsInstance(cfg_dir, Path)
        self.assertTrue(cfg_dir.exists())

    def test_v2_migration(self):
        # Test that legacy config with version < 2 and show_manual_limits=True migrates to False and v14
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        try:
            with open(tmp.name, "w", encoding="utf-8") as f:
                json.dump({"config_version": 1, "show_manual_limits": True, "active_sessions_only": False}, f)
            cm = ConfigManager()
            cm.config_path = Path(tmp.name)
            cm.load()
            self.assertFalse(cm.get("show_manual_limits"))
            self.assertTrue(cm.get("active_sessions_only"))
            self.assertEqual(cm.get("mini_hud_opacity"), 1.0)
            self.assertEqual(cm.get("config_version"), 14)
        finally:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def test_v3_migration(self):
        # Test that v2 config migrates active_sessions_only and updates to v14
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        try:
            with open(tmp.name, "w", encoding="utf-8") as f:
                json.dump({"config_version": 2, "active_sessions_only": False}, f)
            cm = ConfigManager()
            cm.config_path = Path(tmp.name)
            cm.load()
            self.assertTrue(cm.get("active_sessions_only"))
            self.assertEqual(cm.get("config_version"), 14)
        finally:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def test_v4_migration(self):
        # Test that v3 config migrates show_manual_limits to False and updates to v14
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        try:
            with open(tmp.name, "w", encoding="utf-8") as f:
                json.dump({"config_version": 3, "show_manual_limits": True}, f)
            cm = ConfigManager()
            cm.config_path = Path(tmp.name)
            cm.load()
            self.assertFalse(cm.get("show_manual_limits"))
            self.assertEqual(cm.get("config_version"), 14)
        finally:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def test_v5_migration(self):
        # Test that v4 config migrates show_manual_limits to False and updates to v14
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        try:
            with open(tmp.name, "w", encoding="utf-8") as f:
                json.dump({"config_version": 4, "show_manual_limits": True}, f)
            cm = ConfigManager()
            cm.config_path = Path(tmp.name)
            cm.load()
            self.assertFalse(cm.get("show_manual_limits"))
            self.assertEqual(cm.get("config_version"), 14)
        finally:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def test_v14_migration(self):
        # Test that v13 config resets geometries and updates to v14
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        try:
            with open(tmp.name, "w", encoding="utf-8") as f:
                json.dump({"config_version": 13, "show_manual_limits": True, "mini_hud_opacity": 0.75, "mini_hud_bubble_geometry": "+500+300", "mini_hud_geometry": "+1200+400", "window_geometry": "1125x750+318+132"}, f)
            cm = ConfigManager()
            cm.config_path = Path(tmp.name)
            cm.load()
            self.assertFalse(cm.get("show_manual_limits"))
            self.assertEqual(cm.get("mini_hud_opacity"), 1.0)
            self.assertEqual(cm.get("window_geometry"), "")
            self.assertEqual(cm.get("mini_hud_bubble_geometry"), "")
            self.assertEqual(cm.get("mini_hud_geometry"), "")
            self.assertEqual(cm.get("config_version"), 14)
        finally:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def test_default_scope_constants(self):
        from core.config import (
            DEFAULT_ACTIVE_SESSIONS_ONLY,
            DEFAULT_ACTIVE_SESSIONS_ONLY_5H,
            DEFAULT_ACTIVE_SESSIONS_ONLY_7D
        )
        self.assertTrue(DEFAULT_ACTIVE_SESSIONS_ONLY)
        self.assertTrue(DEFAULT_ACTIVE_SESSIONS_ONLY_5H)
        self.assertFalse(DEFAULT_ACTIVE_SESSIONS_ONLY_7D)


if __name__ == "__main__":
    unittest.main()
