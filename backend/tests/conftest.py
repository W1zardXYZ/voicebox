"""Shared test setup.

The suite mixes flat imports (``from utils.progress import ...``) with
package imports (``from backend import config``). Both the repo root and
the backend directory go on ``sys.path`` here so every test file collects
on its own, regardless of which file loads first.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

for _path in (str(BACKEND_DIR), str(REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
