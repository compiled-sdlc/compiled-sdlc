"""Test configuration.

The IR validator lives under lifecycle-ir/, whose name is not a legal Python
package name, so its implementation package is put on the path here rather than
installed.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lifecycle-ir"))
sys.path.insert(0, str(REPO))
