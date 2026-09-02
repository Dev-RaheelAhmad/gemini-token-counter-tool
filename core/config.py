import os
import json
from pathlib import Path
from typing import Dict, Any

# Predefined default scope constants for flexible scenario configurations
DEFAULT_ACTIVE_SESSIONS_ONLY: bool = True        # Global session scope default (Active Chat)
DEFAULT_ACTIVE_SESSIONS_ONLY_5H: bool = True     # 5-Hour view scope (Active Chat)
DEFAULT_ACTIVE_SESSIONS_ONLY_7D: bool = False    # 7-Day view scope (All Chats)

DEFAULT_CONFIG: Dict[str, Any] = {
    "config_version": 14,
    "limit_5h": 1000000,
    "limit_7d": 4000000,
    "show_manual_limits": False,
    "refresh_interval_sec": 3,
    "always_on_top": False,
    "minimize_to_tray": True,
    "close_to_tray": True,
    "auto_track_active": True,
    "theme": "dark",
    "mini_hud_opacity": 1.0,
    "hud_show_5h": True,
    "hud_show_7d": True,
    "hud_show_session": True,
    "hud_show_thinking": True,
    "hud_show_io": False,
    "hud_show_progress": True,
    "hud_show_7d_expanded": False,
    "hud_always_on_top": True,
    "hud_minimized": False,
    "custom_brain_dirs": [],
    "window_geometry": "",
    "mini_hud_geometry": "",
    "mini_hud_bubble_geometry": "",
    "selected_account": "active",
    "active_sessions_only": DEFAULT_ACTIVE_SESSIONS_ONLY,
    "dashboard_timeframe": "5h",
}


def get_config_dir() -> Path:
    """Gets user-specific config directory with multi-fallback support."""
    candidate_paths = []

    if "APPDATA" in os.environ:
        candidate_paths.append(Path(os.environ["APPDATA"]) / "GeminiTokenCounter")

    if "USERPROFILE" in os.environ:
        candidate_paths.append(Path(os.environ["USERPROFILE"]) / ".gemini-token-counter")

    candidate_paths.append(Path.home() / ".gemini-token-counter")
    candidate_paths.append(Path(__file__).parent.parent / ".config")

    for p in candidate_paths:
        try:
            p.mkdir(parents=True, exist_ok=True)
            # Test write permissions
            test_file = p / ".perm_check"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            return p
        except Exception:
            continue

    return Path(".")


def get_config_file() -> Path:
    return get_config_dir() / "config.json"


class ConfigManager:
    def __init__(self):
        self.config_path = get_config_file()
        self.data: Dict[str, Any] = DEFAULT_CONFIG.copy()
        self.load()

    def load(self) -> Dict[str, Any]:
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        self.data.update(loaded)
                        # Schema version migration:
                        ver = loaded.get("config_version", 1)
                        save_needed = False

                        # Version 2 migration: update legacy default for show_manual_limits to False
                        if ver < 2:
                            self.data["show_manual_limits"] = False
                            self.data["config_version"] = 2
                            save_needed = True
                        # Version 3 migration: update default active_sessions_only
                        if ver < 3:
                            self.data["active_sessions_only"] = DEFAULT_ACTIVE_SESSIONS_ONLY
                            self.data["config_version"] = 3
                            save_needed = True
                        # Version 4 & 5 migration: ensure show_manual_limits defaults to False by default
                        if ver < 5:
                            self.data["show_manual_limits"] = False
                            self.data["config_version"] = 5
                            save_needed = True
                        if ver < 6:
                            self.data["show_manual_limits"] = False
                            self.data["config_version"] = 6
                            save_needed = True
                        if ver < 7:
                            self.data["show_manual_limits"] = False
                            if "mini_hud_opacity" not in loaded or loaded.get("mini_hud_opacity") == 0.92:
                                self.data["mini_hud_opacity"] = 1.0
                            self.data["config_version"] = 7
                            save_needed = True
                        if ver < 8:
                            self.data["show_manual_limits"] = False
                            if "mini_hud_opacity" not in loaded or loaded.get("mini_hud_opacity") == 0.92:
                                self.data["mini_hud_opacity"] = 1.0
                            # Reset legacy oversized window geometry
                            raw_geo = str(loaded.get("window_geometry", "")).strip()
                            if raw_geo.startswith("1400x860") or raw_geo.startswith("1285x853"):
                                self.data["window_geometry"] = ""
                            self.data["config_version"] = 8
                            save_needed = True
                        if ver < 9:
                            self.data["show_manual_limits"] = False
                            if "mini_hud_opacity" not in loaded or loaded.get("mini_hud_opacity") in (0.92, 0.75):
                                self.data["mini_hud_opacity"] = 1.0
                            # Reset oversized or full-screen snap window geometry to centered compact default
                            raw_geo = str(loaded.get("window_geometry", "")).strip()
                            if raw_geo:
                                import re
                                m_geo = re.match(r"^(\d+)x(\d+)", raw_geo)
                                if m_geo and (int(m_geo.group(1)) > 1100 or int(m_geo.group(2)) > 750):
                                    self.data["window_geometry"] = ""
                            self.data["config_version"] = 9
                            save_needed = True
                        if ver < 10:
                            self.data["show_manual_limits"] = False
                            if "mini_hud_opacity" not in loaded or loaded.get("mini_hud_opacity") in (0.92, 0.75):
                                self.data["mini_hud_opacity"] = 1.0
                            # Reset previous default geometries (800x600, 680x620) so window re-centers at 900x600
                            raw_geo = str(loaded.get("window_geometry", "")).strip()
                            if raw_geo:
                                import re
                                m_geo = re.match(r"^(\d+)x(\d+)", raw_geo)
                                if m_geo and (int(m_geo.group(1)) in (800, 680, 1400, 1285, 1870) or int(m_geo.group(1)) > 1100 or int(m_geo.group(2)) > 750):
                                    self.data["window_geometry"] = ""
                            self.data["config_version"] = 10
                            save_needed = True
                        if ver < 11:
                            self.data["show_manual_limits"] = False
                            self.data["mini_hud_opacity"] = 1.0
                            self.data["window_geometry"] = ""
                            self.data["config_version"] = 11
                            save_needed = True
                        if ver < 12:
                            self.data["show_manual_limits"] = False
                            self.data["mini_hud_opacity"] = 1.0
                            self.data["window_geometry"] = ""
                            if self.data.get("mini_hud_bubble_geometry") in ("+500+300", "+1251+549", "+1660+910"):
                                self.data["mini_hud_bubble_geometry"] = ""
                            self.data["config_version"] = 12
                            save_needed = True
                        if ver < 13:
                            self.data["show_manual_limits"] = False
                            self.data["mini_hud_opacity"] = 1.0
                            self.data["window_geometry"] = ""
                            self.data["mini_hud_bubble_geometry"] = ""
                            self.data["mini_hud_geometry"] = ""
                            self.data["config_version"] = 13
                            save_needed = True
                        if ver < 14:
                            self.data["show_manual_limits"] = False
                            self.data["mini_hud_opacity"] = 1.0
                            self.data["window_geometry"] = ""
                            self.data["mini_hud_bubble_geometry"] = ""
                            self.data["mini_hud_geometry"] = ""
                            self.data["config_version"] = 14
                            save_needed = True
                            
                        if save_needed:
                            self.save()
            except Exception:
                pass
        return self.data

    def save(self):
        try:
            temp_file = Path(self.config_path).with_suffix(".tmp")
            temp_file.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            max_attempts = 5
            for attempt in range(max_attempts):
                try:
                    temp_file.replace(self.config_path)
                    break
                except OSError:
                    if attempt == max_attempts - 1:
                        try:
                            Path(self.config_path).write_text(json.dumps(self.data, indent=2), encoding="utf-8")
                            temp_file.unlink(missing_ok=True)
                        except Exception:
                            pass
                    else:
                        import time
                        time.sleep(0.05 * (2 ** attempt))
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        val = self.data.get(key)
        if val is not None:
            return val
        if default is not None:
            return default
        return DEFAULT_CONFIG.get(key)

    def set(self, key: str, value: Any, save_now: bool = True):
        self.data[key] = value
        if save_now:
            self.save()


# Singleton config instance
config = ConfigManager()
