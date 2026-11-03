"""Shared runtime helpers.

Adds the project-local ``vendor`` directory (used for wheels that cannot be
installed into the managed site-packages because of the host endpoint-security
policy) to the import path before any database driver is resolved.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VENDOR = Path(__file__).resolve().parents[1] / "vendor"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))
