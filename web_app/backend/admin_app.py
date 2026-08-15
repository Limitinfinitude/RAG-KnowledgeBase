"""管理站 ASGI：管理前端 + 全量 API（含 /api/admin）。启动示例：uvicorn web_app.backend.admin_app:app --host 0.0.0.0 --port 8766"""
from __future__ import annotations

from web_app.backend.bootstrap import create_admin_application

app = create_admin_application()

__all__ = ["app"]
