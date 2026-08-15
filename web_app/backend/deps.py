"""FastAPI 依赖：管理员校验等。"""
from __future__ import annotations

from fastapi import HTTPException, Request

from utils.auth_store import User


def require_admin(request: Request) -> User:
    user: User | None = getattr(request.state, "user", None)
    if user is None or not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def get_admin_user(request: Request) -> User:
    """用于 Depends：仅管理员可访问的路由。"""
    return require_admin(request)
