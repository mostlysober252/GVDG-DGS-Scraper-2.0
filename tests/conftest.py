"""Shared pytest setup for the pipeline test suite.

Ensures the repo root (which contains the ``pipeline`` package) is importable
regardless of the working directory pytest is launched from, and exposes the
fixtures directory as a path constant.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
