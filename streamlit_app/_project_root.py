"""把仓库根目录加入 sys.path（streamlit run streamlit_app/app.py 时默认可导入 utils/config/services）。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_s = str(_ROOT)
if _s not in sys.path:
    sys.path.insert(0, _s)
