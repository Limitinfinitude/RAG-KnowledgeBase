"""认证、按用户知识库上下文、API 审计日志。"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request
from starlette.responses import JSONResponse

from utils.auth_store import User, get_user_from_token, log_api_audit
from utils.path_context import reset_kb_context, set_user_kb_context
from utils.web_system_settings import (
    get_rate_limit_qpm_per_user,
    is_guest_mode_enabled,
    is_maintenance_mode,
)

# 参与「每分钟问答次数」限流的路径；若新增独立聊天 POST 路径，须同步加入，避免漏限流。
CHAT_QPM_PATHS: frozenset[str] = frozenset(
    {
        "/api/chat",
        "/api/chat/instant",
    }
)

_CHAT_QPM_WINDOW_SEC = 60.0
_user_chat_buckets: dict[int, deque[float]] = defaultdict(deque)
_CHAT_BUCKETS_MAX = 5000  # 桶总数上限：一次性访客的空桶只在下次请求时清理，超量时主动清扫
_GUEST_ALLOWED = {
    *CHAT_QPM_PATHS,
    "/api/instant-doc/parse",
    "/api/knowledge-bases",
    "/api/kb/stats",
    "/api/documents",
    "/api/documents/preview",
    "/api/indexed-sources",
    "/api/config/presets",
    "/api/config/summary",
    "/api/bm25-status",
}


def _skip_auth(path: str, method: str) -> bool:
    if method == "OPTIONS":
        return True
    if path == "/api/health":
        return True
    if path.startswith("/api/public/"):
        return True
    if path == "/api/auth/register" and method == "POST":
        return True
    if path == "/api/auth/register-admin" and method == "POST":
        return True
    if path == "/api/auth/login" and method == "POST":
        return True
    if path == "/api/public/feedback" and method == "POST":
        return True
    return False


def _skip_audit(path: str) -> bool:
    return path == "/api/health"


async def auth_kb_audit_middleware(request: Request, call_next):
    path = request.url.path
    method = request.method

    if not path.startswith("/api/"):
        return await call_next(request)

    t0 = time.perf_counter()

    if _skip_auth(path, method):
        status_code = 500
        err_text: str | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as e:
            err_text = str(e)
            status_code = 500
            raise
        finally:
            if not _skip_audit(path):
                log_api_audit(
                    user_id=None,
                    username=None,
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                    error=err_text,
                )

    auth = request.headers.get("authorization") or ""
    if not auth.startswith("Bearer "):
        if is_guest_mode_enabled() and path in _GUEST_ALLOWED:
            request.state.user = User(
                id=0,
                username="guest",
                nickname="游客",
                role="user",
                avatar=None,
                status="active",
            )
            t_kb, t_api = set_user_kb_context(0)
            status_code = 500
            err_text: str | None = None
            try:
                response = await call_next(request)
                status_code = response.status_code
                return response
            except Exception as e:
                err_text = str(e)
                status_code = 500
                raise
            finally:
                if not _skip_audit(path):
                    log_api_audit(
                        user_id=0,
                        username="guest",
                        method=method,
                        path=path,
                        status_code=status_code,
                        duration_ms=(time.perf_counter() - t0) * 1000,
                        error=err_text,
                    )
                reset_kb_context(t_kb, t_api)
        if not _skip_audit(path):
            log_api_audit(
                user_id=None,
                username=None,
                method=method,
                path=path,
                status_code=401,
                duration_ms=(time.perf_counter() - t0) * 1000,
                error=None,
            )
        return JSONResponse(
            status_code=401,
            content={"detail": "未登录或缺少令牌，请先登录"},
        )

    token = auth[7:].strip()
    user = get_user_from_token(token)
    if user is None:
        if not _skip_audit(path):
            log_api_audit(
                user_id=None,
                username=None,
                method=method,
                path=path,
                status_code=401,
                duration_ms=(time.perf_counter() - t0) * 1000,
                error=None,
            )
        return JSONResponse(
            status_code=401,
            content={"detail": "登录已失效，请重新登录"},
        )

    request.state.user = user
    if is_maintenance_mode() and not user.is_admin:
        if not _skip_audit(path):
            log_api_audit(
                user_id=user.id,
                username=user.username,
                method=method,
                path=path,
                status_code=503,
                duration_ms=(time.perf_counter() - t0) * 1000,
                error="maintenance_mode",
            )
        return JSONResponse(
            status_code=503,
            content={"detail": "系统维护中，请稍后再试"},
        )
    if path in CHAT_QPM_PATHS:
        qpm = get_rate_limit_qpm_per_user()
        now = time.time()
        if len(_user_chat_buckets) > _CHAT_BUCKETS_MAX:
            # 一次性访客的空桶/过期桶清扫，防止长期运行的慢泄漏
            for uid in [u for u, b in _user_chat_buckets.items() if not b or now - b[-1] > _CHAT_QPM_WINDOW_SEC]:
                _user_chat_buckets.pop(uid, None)
        bucket = _user_chat_buckets[int(user.id)]
        while bucket and now - bucket[0] > _CHAT_QPM_WINDOW_SEC:
            bucket.popleft()
        if len(bucket) >= qpm:
            if not _skip_audit(path):
                log_api_audit(
                    user_id=user.id,
                    username=user.username,
                    method=method,
                    path=path,
                    status_code=429,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                    error="chat_rate_limited",
                )
            return JSONResponse(
                status_code=429,
                content={"detail": f"请求过于频繁，请稍后再试（每分钟上限 {qpm} 次）"},
            )
        bucket.append(now)
    t_kb, t_api = set_user_kb_context(user.id)
    status_code = 500
    err_text: str | None = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception as e:
        err_text = str(e)
        status_code = 500
        raise
    finally:
        if not _skip_audit(path):
            log_api_audit(
                user_id=user.id,
                username=user.username,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=(time.perf_counter() - t0) * 1000,
                error=err_text,
            )
        reset_kb_context(t_kb, t_api)
