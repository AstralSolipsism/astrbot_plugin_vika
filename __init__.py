from __future__ import annotations

import sys
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent
_LOCAL_ASTRAL_VIKA_SRC = _PACKAGE_ROOT / "astral_vika" / "src"

if _LOCAL_ASTRAL_VIKA_SRC.is_dir():
    _local_sdk_path = str(_LOCAL_ASTRAL_VIKA_SRC)
    if _local_sdk_path not in sys.path:
        sys.path.insert(0, _local_sdk_path)

__all__ = []
