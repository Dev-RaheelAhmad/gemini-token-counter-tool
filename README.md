# ⚡ Gemini Token Counter & Live Quota Monitor

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20WSL2-0078D6.svg?style=flat&logo=windows&logoColor=white)](https://microsoft.com)
[![GUI Framework](https://img.shields.io/badge/UI-CustomTkinter-2563EB.svg?style=flat)](https://github.com/TomSchimansky/CustomTkinter)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![CPU Usage](https://img.shields.io/badge/Idle%20CPU-0.0%25-brightgreen.svg)]()

A lightweight, high-performance Windows Desktop GUI monitor, floating Mini HUD, and terminal CLI tool for tracking **Google Gemini AI token consumption**, **reasoning/thinking tokens**, and **rolling rate limits** (5-hour and 7-day windows) in real time.

Built specifically for developers using Google Antigravity, Gemini CLI, and Antigravity IDE across Windows native and WSL2 environments.

---

## 🌟 Key Features

- **⚡ Real-Time Zero-Lag Monitoring**: Background watcher that automatically refreshes as you chat in Antigravity using incremental byte-offset JSONL parsing (0.0% CPU when idle).
- **🔒 Immutable Event Ledger (`account_ledger.jsonl`)**: Append-only event log recording atomic updates (`session_registered`, `token_delta`, `account_switched`) to guarantee zero data loss, crash resilience, and complete audit history.
- **👤 Multi-Account Quota Isolation & Mid-Session Tracking**: Automatically detects your active Google Account login and attributes exact per-account token deltas. Switching accounts mid-session accurately attributes subsequent tokens to the new user without corrupting or resetting the previous user's quota.
- **🌐 Google Cloud Server Quota Sync (Optional)**: Seamlessly integrates with [Antigravity-Manager](https://github.com/lbjlaq/Antigravity-Manager) to display 100% accurate server-side quota pools and exact reset countdowns.
- **📊 Complete Token Breakdown**: Input / Prompt Tokens, Thinking / Reasoning Tokens (`<thought>` / `<thinking>` blocks), Output / Candidate Tokens, and Grand Totals with percentage ratios.
- **⏳ Rolling Quota Gauges & Velocity**: Real-time 5-Hour burn rate and 7-Day weekly quotas with recovery countdown timers, color-coded alert thresholds (🟢 Green, 🟡 Amber, 🔴 Red), and instant burn velocity (`tok/hr`).
- **🗕 Floating Mini HUD & 🫧 Floating Bubble**: Draggable, translucent Always-on-Top overlay widget with dynamic sizing, 1-click 7D expansion toggle, ultra-compact Floating Bubble mode with live hover report, and taskbar-free design.
- **🗔 Windows System Tray**: Minimizes cleanly to the Windows notification tray with 1-click launch menus (Dashboard, Mini HUD, Floating Bubble) and live 5-line rich tooltip stats (5H & 7D recovery timers, remaining %, dedicated Active/All counts, and dynamic active user badge).
- **📈 Interactive Usage Graphs & Analytics**: Visualizes token consumption over time (5-Hour rolling, 24-Hour hourly, 7-Day daily, 30-Day daily, Monthly, Yearly, and Turn-by-Turn Session Timelines) with interactive hover tooltips and CSV/JSON export.
- **🔍 Session Explorer**: Search and filter past sessions by UUID, date, or **prompt snippet preview**. Right-click any session to copy ID, view usage graph, open directory in Explorer, or delete the session.
- **🧹 Session Cleaner & Storage Compactor**: Deletes historical chat transcripts from disk and ledger (by age, keeping latest $N$, removing empty sessions, or cleaning all previous) to reclaim disk space.
- **🐧 Automatic WSL2 & Multi-Drive Discovery**: Scans Windows native user profiles, all mounted Windows drives (C:, D:, Z:, etc.), and WSL2 UNC network paths (`\\wsl.localhost\<distro>` and `\\wsl$\<distro>`) directly from Windows with zero subprocess overhead.
- **📁 Custom Paths Manager**: Interactive path manager in Settings with folder browsing (`📁 Browse`), manual path entry, and instant re-scanning.
- **⌨️ Keyboard Shortcuts**: `Ctrl+R` / `F5` (Refresh), `Ctrl+M` (Toggle Mini HUD), `Esc` (Minimize to Tray).
- **🚀 Windows Startup Integration**: 1-click toggle in Settings to auto-launch silently on Windows startup.

---

## ⚡ Optional Enhancement: 100% Server Quota Accuracy

This application works completely out-of-the-box in standalone mode. However, for maximum accuracy, it includes built-in support for [**Antigravity-Manager**](https://github.com/lbjlaq/Antigravity-Manager):

| Mode | Quota Source | 5H / 7D Reset Accuracy | Setup Requirement |
| :--- | :--- | :--- | :--- |
| **🌐 Live Cloud Sync** *(Recommended)* | Google Cloud Server Quota Pools | **100% Exact** (Matches Google server reset timestamps) | Install [Antigravity-Manager](https://github.com/lbjlaq/Antigravity-Manager) |
| **💾 Local Estimation** *(Standalone)* | Local JSONL Transcript Logs & Ledger | **Estimated** (Based on locally parsed sliding windows) | None (100% self-contained) |

> [!TIP]
> **Why install Antigravity-Manager?**
> Having [Antigravity-Manager](https://github.com/lbjlaq/Antigravity-Manager) installed and running in your environment automatically syncs real-time server-side quota pools (`.antigravity_tools/accounts/*.json`). This ensures 100% accurate cloud quota percentages and exact server reset timers. If you choose not to install it, the tool will gracefully fall back to local storage logs, tracking consumption through its internal append-only ledger.

---

## 🏛️ Architecture Overview

```text
  ┌─────────────────────────────────────────────────────────────┐
  │                 Antigravity JSONL Transcripts               │
  │     (Windows Profiles, Mounted Drives, WSL2 UNC Paths)      │
  └──────────────────────────────┬──────────────────────────────┘
                                 │ Incremental Byte-Offset Parsing
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                        Core Engine                          │
  │   • Token Estimator          • 5h / 7d Sliding Windows      │
  │   • Recovery Countdown       • Burn Velocity (tok/hr)       │
  └──────────────────────────────┬──────────────────────────────┘
                                 │
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                  In-Memory Account Ledger                   │
  │   • Account-Scoped Quotas    • Time-Series Metric Buffer    │
  │   • Multi-Account Separation • RAM-Buffered State           │
  │   • Optional Cloud Sync via Antigravity-Manager             │
  └──────────────┬───────────────────────────────┬──────────────┘
                 │                               │
                 │ Atomic Append & Snapshots     │ Real-Time Feeds
                 ▼                               ▼
  ┌──────────────────────────────┐ ┌───────────────────────────┐
  │     account_ledger.jsonl     │ │     Presentation Layer    │
  │      (Append-Only Log)       │ │ • Desktop GUI Dashboard   │
  │      account_usage.json      │ │ • Floating Mini HUD       │
  │      (Database Snapshot)     │ │ • Windows System Tray     │
  └──────────────────────────────┘ │ • Terminal CLI & ASCII    │
                                   └───────────────────────────┘
```

---

## 🧭 Viewing Scopes

The monitor provides 3 dedicated viewing modes to fit every workflow:

| Scope | Top Stat Cards | Quota Gauges (5h / 7d) | Usage Chart |
| :--- | :--- | :--- | :--- |
| **⚡ Active Session** | Token consumption for the **current chat only** | Current chat's rolling burn rate | Time-series for the active chat |
| **👤 User Account** | Tokens consumed by this account in the active chat (with mid-session switch attribution) | **Google Cloud Server Quota** for this user account | All sessions belonging to this user |
| **★ All Accounts** | **Grand total** across all chats and users | Combined device-wide burn rate | Combined device history |

---

## 🚀 Quick Setup & Installation

### Prerequisites
- **Windows 10 / 11** or **WSL2**
- **Python 3.10+** (Ensure *"Add Python to PATH"* is checked during Python installation)
- **Git** (for cloning)

---

### Option 1: 1-Click Installer (Recommended)
Double-click `setup_windows.bat` in the project directory. It will:
1. Validate your Python environment.
2. Install dependencies from `requirements.txt`.
3. Create a **"Gemini Token Monitor"** shortcut on your Desktop and Start Menu.
4. Launch the application immediately.

---

### Option 2: Manual Installation
```powershell
# 1. Clone repository
git clone https://github.com/Dev-RaheelAhmad/gemini-token-counter-tool.git
cd gemini-token-counter-tool

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch Desktop GUI (silent mode without terminal window)
start pythonw token_counter_gui.pyw

# 4. (Optional) Create Desktop shortcut
powershell -ExecutionPolicy Bypass -File create_shortcut.ps1
```

---

## 💻 CLI Usage (Terminal)

The tool provides a comprehensive CLI for headless environments, CI/CD, scripting, and live terminal monitoring:

```bash
# 1. Current active conversation (Default)
python token_counter.py

# 2. Active Google Account rolling quota
python token_counter.py --account

# 3. Specific Google Account rolling quota
python token_counter.py --account user@example.com

# 4. Terminal ASCII Usage Graph (5h default, 24h, 7d, 30d, month, year, session)
python token_counter.py --graph
python token_counter.py --history 24h
python token_counter.py --history 7d
python token_counter.py --history month

# 5. Live refreshing terminal dashboard
python token_counter.py --watch
python token_counter.py --account --watch --interval 2

# 6. Device grand total (across all accounts and historical chats)
python token_counter.py --all

# 7. Specific session ID
python token_counter.py --session <SESSION_ID>

# 8. Machine-readable JSON output (for scripting/piping)
python token_counter.py --json
python token_counter.py --account --json
python token_counter.py --history 7d --json

# 9. Storage Cleaner & Compactor
python token_counter.py --disk-usage
python token_counter.py --clean-older-than 7
python token_counter.py --keep-latest 5
python token_counter.py --delete-session <SESSION_ID>
python token_counter.py --clean-empty
python token_counter.py --clean-previous

# 10. Launch Desktop GUI from terminal
python token_counter.py --gui
```

### CLI Options Reference

| Flag | Short | Description |
| :--- | :---: | :--- |
| `--account [EMAIL]` | `-u` | Report rolling quota for active Google Account or specified email |
| `--all` | `-a` | Report cumulative tokens across all sessions & accounts |
| `--session <ID>` | `-s` | Report tokens for a specific session ID |
| `--watch` | `-w` | Continuously monitor in terminal with live refresh |
| `--interval <SEC>` | `-i` | Polling interval in seconds for `--watch` mode (default: 3) |
| `--graph` | | Render interactive ASCII/Unicode usage chart in terminal |
| `--history <TF>` | | View usage chart for timeframe (`5h`, `24h`, `7d`, `30d`, `month`, `year`, `session`) |
| `--disk-usage` | | Display storage consumption breakdown by session transcripts |
| `--clean-older-than <DAYS>` | | Prune sessions older than specified days |
| `--keep-latest <N>` | | Keep only latest $N$ sessions and prune older ones |
| `--delete-session <ID>` | | Permanently delete a specific session |
| `--clean-empty` | | Remove empty or 0-token session transcripts |
| `--clean-previous` | | Delete all previous sessions, preserving only the active one |
| `--json` | `-j` | Output machine-readable JSON format |
| `--gui` | `-g` | Launch the Desktop GUI monitor |

---

## ⚙️ Configuration Reference

Settings are saved automatically per-user in `%APPDATA%\GeminiTokenCounter\config.json`:

| Key | Type | Default | Description |
| :--- | :---: | :---: | :--- |
| `limit_5h` | integer | `1000000` | 5-hour rolling token limit threshold |
| `limit_7d` | integer | `4000000` | 7-day weekly token limit threshold |
| `show_manual_limits` | boolean | `false` | Show percentage against manual limit thresholds |
| `refresh_interval_sec` | integer | `3` | Watcher polling interval in seconds |
| `always_on_top` | boolean | `false` | Keep dashboard window pinned on top |
| `close_to_tray` | boolean | `true` | Minimize to system tray on window close |
| `minimize_to_tray` | boolean | `true` | Minimize to system tray on minimize |
| `theme` | string | `"dark"` | UI theme (`"dark"`, `"light"`, or `"system"`) |
| `hud_always_on_top` | boolean | `true` | Pin Floating Mini HUD always on top |
| `hud_minimized` | boolean | `false` | Start Mini HUD directly in compact Floating Bubble mode |
| `mini_hud_opacity` | float | `1.0` | HUD background transparency ($0.5$ to $1.0$) |
| `hud_show_5h` | boolean | `true` | Display 5-hour burn gauge in Mini HUD |
| `hud_show_7d` | boolean | `true` | Display 7-day weekly quota in Mini HUD |
| `hud_show_thinking` | boolean | `true` | Display reasoning/thinking tokens in Mini HUD |
| `custom_brain_dirs` | array | `[]` | List of user-configured `.gemini/.../brain` paths |
| `mini_hud_bubble_geometry` | string | `""` | Saved screen position for Floating Bubble |
| `window_geometry` | string | `""` | Saved window position and dimensions (auto-centered by default) |

---

## 🧪 Running Unit Tests

The test suite validates configuration management, token estimation, rate-limit sliding windows, multi-account isolation, append-only event logging, analytics aggregation, cleaner pruning, system tray tooltips, and GUI components:

```bash
python -m unittest tests/test_all.py
```

---

## 📂 Project Structure

```text
gemini-token-counter-tool/
├── core/                         # Core calculation and backend logic
│   ├── account_manager.py        # Multi-account discovery and active user tracking
│   ├── analytics.py              # Time-series aggregation and ASCII chart generation
│   ├── cleaner.py                # Session deletion and disk compactor
│   ├── config.py                 # Persistent configuration manager
│   ├── engine.py                 # Byte-offset JSONL parser & sliding window tracker
│   ├── ledger.py                 # In-memory database & append-only JSONL log
│   ├── realtime_quota.py         # Google Cloud server-side quota reader
│   ├── session_finder.py         # Multi-drive and WSL2 brain directory scanner
│   └── watcher.py                # 0.0% CPU background file watcher
├── gui/                          # CustomTkinter Desktop GUI
│   ├── components/               # Modular UI widgets
│   │   ├── progress_bar.py       # Segmented token ratio bar
│   │   ├── quota_gauge.py        # 5H & 7D rate-limit gauges
│   │   ├── session_table.py      # Searchable session explorer
│   │   ├── stat_card.py          # Metric summary cards
│   │   └── usage_chart.py        # Vector canvas time-series usage chart
│   ├── analytics_dialog.py       # Full analytics & data export dialog
│   ├── app.py                    # Main dashboard application window
│   ├── cleaner_dialog.py         # Session storage cleaner & compactor dialog
│   ├── mini_hud.py               # Translucent floating Always-on-Top widget
│   ├── tray.py                   # Windows system tray integration
│   └── window_utils.py           # Native window positioning and geometry manager
├── tests/
│   └── test_all.py               # Unit test suite
├── create_shortcut.ps1           # Desktop & Start Menu shortcut generator
├── install_shortcut.bat          # 1-click shortcut installer
├── LICENSE                       # MIT License
├── README.md                     # Documentation
├── requirements.txt              # Minimal Python dependencies
├── run_gui.bat                   # Launcher batch script
├── run_silent.vbs                # Headless background launcher
├── setup_windows.bat             # 1-click installer and setup script
├── token_counter.py              # CLI utility and standalone entry point
├── token_counter_gui.py          # Desktop GUI entry point (console mode)
└── token_counter_gui.pyw         # Desktop GUI entry point (silent mode)
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
