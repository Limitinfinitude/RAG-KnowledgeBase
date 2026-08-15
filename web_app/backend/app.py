"""Web 线上入口（单端口单体）：用户 ``/``、管理 ``/admin/``。

- 单体：``uvicorn web_app.backend.app:app --host 0.0.0.0 --port 8765``
- 双端口（同进程）：``python -m web_app.backend.dual_app``（默认 4010 用户 / 4011 管理）

接口划分与 OpenAPI 说明见 ``bootstrap.create_*_application`` 及项目说明文档。
"""
from __future__ import annotations

from web_app.backend.bootstrap import create_full_application

app = create_full_application()

__all__ = ["app"]
