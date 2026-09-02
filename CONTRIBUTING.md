# Contributing to Gemini Token Counter & Live Quota Monitor

Thank you for your interest in contributing to **Gemini Token Counter & Live Quota Monitor**! We welcome bug reports, feature suggestions, documentation improvements, and code contributions.

---

## 🔒 Confidentiality & Zero-Leak Security Policy

To protect user privacy and avoid accidental exposure of sensitive information, all contributors must strictly adhere to these rules:

1. **Zero Hardcoded Secrets**: Under NO circumstances should any API keys, OAuth tokens, client secrets, passwords, or credentials be added to code, tests, documentation, or commit messages.
2. **No User Transcripts in Git**: Never commit personal `.jsonl` session files, `account_usage.json`, or local databases. All user state must strictly reside in user profile directories ignored by git.
3. **Synthetic Test Fixtures Only**: When writing tests, always use RFC standard placeholder domains (`user@example.com`, `developer@company.org`) and synthetic session UUIDs.
4. **Dynamic Portability**: Never hardcode developer-specific machine paths (`C:\Users\<user>`, `/home/<user>`). Always use dynamic resolution via environment variables (`Path.home()`, `%USERPROFILE%`, `%APPDATA%`).

---

## 🛠️ Development Setup

### 1. Clone & Set Up Environment
```bash
git clone https://github.com/Dev-RaheelAhmad/gemini-token-counter-tool.git
cd gemini-token-counter-tool

# Create and activate a virtual environment (optional)
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux / WSL:
source venv/bin/activate

# Install dependencies and editable package
pip install -r requirements.txt
pip install -e .
```

### 2. Running Tests
Before submitting any changes, verify that the entire test suite passes:

```bash
python -m unittest tests/test_all.py
```

All 76 unit tests must pass with 100% success rate.

---

## 📐 Architecture & Performance Guidelines

1. **0.0% Idle CPU Overhead**: Background watchers must use stat-based change detection (checking `st_mtime` and `st_size`) to avoid spinning CPU loops or continuous subprocess invocations.
2. **Crash Resilience & Atomic Writes**: Any disk persistence must use atomic file replacements (`.tmp` write followed by `replace()`) to prevent state corruption.
3. **Theme Compatibility**: All GUI components must support both Light and Dark mode using tuple color values (e.g. `fg_color=("#f1f5f9", "#0f131a")`).

---

## 🚀 Submitting a Pull Request

1. Fork the repository and create your branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Make your modifications, adhering to the coding and confidentiality standards.
3. Run the unit test suite (`python -m unittest tests/test_all.py`).
4. Commit your changes with a clear, concise commit message.
5. Push to your fork and open a Pull Request against the `main` branch.
