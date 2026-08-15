"""兼容旧启动命令：uvicorn services.fastapi_app:app"""
from web_app.backend.app import app

__all__ = ["app"]
