from __future__ import annotations

import sys
import os
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent
_VENDORED_ASTRAL_VIKA_SRC = _PACKAGE_ROOT / "vendor" / "astral_vika" / "src"
_LOCAL_ASTRAL_VIKA_SRC = _PACKAGE_ROOT / "astral_vika" / "src"

_SDK_PATHS = [_VENDORED_ASTRAL_VIKA_SRC]
if os.getenv("VIKAMCP_USE_LOCAL_ASTRAL_VIKA") == "1":
    _SDK_PATHS.insert(0, _LOCAL_ASTRAL_VIKA_SRC)

for _sdk_src in reversed(_SDK_PATHS):
    if _sdk_src.is_dir():
        _sdk_path = str(_sdk_src)
        if _sdk_path not in sys.path:
            sys.path.insert(0, _sdk_path)

__all__ = []
