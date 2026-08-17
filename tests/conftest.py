import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# scripts/ holds the modules under test (verifier.py, run_eval.py, ...)
sys.path.insert(0, str(ROOT / "scripts"))

CONFIG = ROOT / "config"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Neutralize time.sleep so the full-question-loop tests don't actually wait
    (min_interval is 1s per sample; irrelevant to correctness)."""
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)
