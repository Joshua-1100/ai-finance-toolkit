#!/usr/bin/env python3
"""Launcher. Run this file to start the reconciliation.

    python run_recon.py

Exists so nobody has to know what `python -m recon.cli` means.
"""

import sys
from pathlib import Path

# Make the launcher work from any working directory, including a double-click.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from recon.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
