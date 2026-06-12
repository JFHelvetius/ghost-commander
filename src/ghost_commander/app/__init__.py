"""Streamlit dashboard launcher."""

from __future__ import annotations

import sys
from pathlib import Path


def run() -> None:
    """Launch the dashboard via the Streamlit CLI (entry point ``ghost-commander-app``)."""
    from streamlit.web import cli as stcli

    script = str(Path(__file__).with_name("dashboard.py"))
    sys.argv = ["streamlit", "run", script, "--theme.base", "dark"]
    sys.exit(stcli.main())


__all__ = ["run"]
