"""单进程双监听：用户站与管理站各一端口（默认 4010 / 4011）。

启动::

    python -m web_app.backend.dual_app

环境变量 ``RAG_USER_PORT``、``RAG_ADMIN_PORT`` 可覆盖默认端口。
用户站旧书签 ``/admin*.html`` 若需跳到管理站，可设 ``RAG_ADMIN_PUBLIC_ORIGIN``，例如 ``http://127.0.0.1:4011``。
Uvicorn 并发与 keep-alive 等见项目根目录 ``PERFORMANCE.md``（``UVICORN_*``）。
"""
from __future__ import annotations

import asyncio
import os

import uvicorn

from web_app.backend.bootstrap import create_admin_application, create_user_application
from web_app.backend.server_env import get_uvicorn_config_extras


def _ports() -> tuple[int, int]:
    return (
        int(os.environ.get("RAG_USER_PORT", "4010")),
        int(os.environ.get("RAG_ADMIN_PORT", "4011")),
    )


async def _serve_dual() -> None:
    user_port, admin_port = _ports()
    user_app = create_user_application()
    admin_app = create_admin_application()
    _uv = dict(
        host=os.environ.get("RAG_BIND_HOST", "0.0.0.0"),
        log_level=os.environ.get("UVICORN_LOG_LEVEL", "info"),
    )
    _uv.update(get_uvicorn_config_extras())
    cfg_user = uvicorn.Config(user_app, port=user_port, **_uv)
    cfg_admin = uvicorn.Config(admin_app, port=admin_port, **_uv)
    await asyncio.gather(
        uvicorn.Server(cfg_user).serve(),
        uvicorn.Server(cfg_admin).serve(),
    )


def main() -> None:
    asyncio.run(_serve_dual())


if __name__ == "__main__":
    main()
