"""Streamlit Community Cloud entry point.

Streamlit Cloud auto-detects ``streamlit_app.py`` at the repo root. We make the
``src`` layout importable and hand off to the real dashboard. This keeps the
package src-layout (clean for tests/packaging) while staying one click to deploy.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = str(Path(__file__).parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from ghost_commander.app.dashboard import main  # noqa: E402

main()
