#!/usr/bin/env python3
"""Lifecycle IR validator.

Usage:
    python lifecycle-ir/validate.py validate <bundle-directory|document.json> [--strict]
    python lifecycle-ir/validate.py report <bundle-directory>
    python lifecycle-ir/validate.py examples
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lcir.cli import main  # noqa: E402  - path setup must precede the import

if __name__ == "__main__":
    sys.exit(main())
