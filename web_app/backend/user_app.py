"""用户站 ASGI：仅用户前端与非管理 API。启动示例：uvicorn web_app.backend.user_app:app --host 0.0.0.0 --port 8765"""
from __future__ import annotations

from web_app.backend.bootstrap import create_user_application

app = create_user_application()

__all__ = ["app"]
