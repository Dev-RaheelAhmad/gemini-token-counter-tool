import os
import sys
import tempfile
import shutil
from pathlib import Path

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from core.config import DEFAULT_CONFIG, config

# Strictly isolate global test config to a temporary directory so unit tests never mutate user %APPDATA% state
_test_tmp_dir = tempfile.mkdtemp(prefix="gemini_test_config_")
_test_config_file = Path(_test_tmp_dir) / "config.json"
config.config_path = _test_config_file
config.data = DEFAULT_CONFIG.copy()


def tearDownPackage():
    shutil.rmtree(_test_tmp_dir, ignore_errors=True)
