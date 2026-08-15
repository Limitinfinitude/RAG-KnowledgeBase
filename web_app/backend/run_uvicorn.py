"""单端口启动 FastAPI（单体 app），自动应用 PERFORMANCE.md 中的 Uvicorn 性能参数。

用法（项目根目录）::

    python -m web_app.backend.run_uvicorn

环境变量：``PORT``（默认 8765）、``RAG_BIND_HOST``、``UVICORN_*``、``UVICORN_LOG_LEVEL``。
"""
from __future__ import annotations

import os

import uvicorn

from web_app.backend.server_env import get_uvicorn_config_extras


def main() -> None:
    host = os.environ.get("RAG_BIND_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8765"))
    kw = get_uvicorn_config_extras()
    kw["log_level"] = os.environ.get("UVICORN_LOG_LEVEL", "info")
    uvicorn.run("web_app.backend.app:app", host=host, port=port, **kw)


if __name__ == "__main__":
    main()
