import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# scripts/ holds the modules under test (verifier.py, run_eval.py, ...)
sys.path.insert(0, str(ROOT / "scripts"))

CONFIG = ROOT / "config"
