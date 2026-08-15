"""Uvicorn 等与部署相关的性能相关参数（环境变量集中读取）。"""
from __future__ import annotations

import os
from typing import Any, Dict


def get_uvicorn_config_extras() -> Dict[str, Any]:
    """
    传入 uvicorn.Config(..., **get_uvicorn_config_extras())。
    见项目根目录 PERFORMANCE.md。
    """
    lc = int(os.environ.get("UVICORN_LIMIT_CONCURRENCY", "120"))
    ka = int(os.environ.get("UVICORN_TIMEOUT_KEEP_ALIVE", "5"))
    return {
        "limit_concurrency": max(8, lc),
        "timeout_keep_alive": max(1, ka),
    }
