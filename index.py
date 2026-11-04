"""Vercel entry point: serves the what-if console from ml_startup/app/api.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'ml_startup' / 'app'))

from api import app  # noqa: E402,F401
