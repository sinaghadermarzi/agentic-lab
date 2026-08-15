"""Run scripts/check_data.py so plain pytest catches any data drift."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_check_data_passes():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_data.py")],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0, f"check_data.py failed:\n{proc.stdout}\n{proc.stderr}"
