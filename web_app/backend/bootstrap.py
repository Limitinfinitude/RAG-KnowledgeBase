"""构建用户站 / 管理站 / 合并站 FastAPI 实例的共享逻辑。"""
from __future__ import annotations

import hashlib
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from config import STREAMLIT_KB_DIR, WEB_SERVER_DIR, WEB_USERS_ROOT
from utils.auth_store import init_auth_db, prune_expired_sessions

from . import ingest_queue, vdb_cache
from .middleware import auth_kb_audit_middleware
from .routers import admin_routes, auth_routes, public_routes, rag_routes

_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SHARED_DIR = os.path.join(_PROJECT_ROOT, "web_app", "frontend", "shared")
_USER_DIR = os.path.join(_PROJECT_ROOT, "web_app", "frontend", "user")
_ADMIN_DIR = os.path.join(_PROJECT_ROOT, "web_app", "frontend", "admin")
_UPLOAD_SW_PATH = os.path.join(_SHARED_DIR, "upload-sw.js")
_FAVICON_PATH = os.path.join(_SHARED_DIR, "assets", "favicon.ico")

_LEGACY_ADMIN_REDIRECTS: dict[str, str] = {
    "/admin.html": "/admin/users.html",
    "/admin-kb.html": "/admin/docs.html",
    "/admin-settings.html": "/admin/settings.html",
    "/admin-console.html": "/admin/users.html",
    "/admin/console.html": "/admin/users.html",
    "/admin-users.html": "/admin/users.html",
    "/admin-docs.html": "/admin/docs.html",
    "/admin-monitor.html": "/admin/monitor.html",
    "/admin-logs.html": "/admin/logs.html",
    "/admin-feedback.html": "/admin/feedback.html",
    "/admin-analytics.html": "/admin/analytics.html",
    "/admin-flags.html": "/admin/flags.html",
    "/admin-advanced.html": "/admin/advanced.html",
    "/admin-vector.html": "/admin/vector.html",
    "/admin-login.html": "/admin/login.html",
    "/admin-register.html": "/admin/register.html",
    "/admin/index.html": "/admin/hub.html",
    "/admin/kb.html": "/admin/docs.html",
    "/admin": "/admin/hub.html",
    "/admin/": "/admin/hub.html",
}


_lifespan_refcount = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """单进程多 ASGI 应用（如双端口）时共用：仅首实例做初始化，末实例退出时收尾。"""
    global _lifespan_refcount
    _lifespan_refcount += 1
    if _lifespan_refcount == 1:
        init_auth_db()
        prune_expired_sessions()
        os.makedirs(WEB_SERVER_DIR, exist_ok=True)
        os.makedirs(WEB_USERS_ROOT, exist_ok=True)
        os.makedirs(STREAMLIT_KB_DIR, exist_ok=True)
        ingest_queue.start_worker()
    try:
        yield
    finally:
        _lifespan_refcount -= 1
        if _lifespan_refcount == 0:
            ingest_queue.stop_worker()
            vdb_cache.clear_all_cache()


def _redirect_handler(destination: str):
    async def _go():
        return RedirectResponse(url=destination, status_code=307)

    return _go


def _legacy_redirect_operation_id(legacy_path: str) -> str:
    """OpenAPI operation_id：路径含 /admin 与 /admin/ 等需区分，避免重复。"""
    h = hashlib.sha256(legacy_path.encode("utf-8")).hexdigest()[:16]
    return f"legacy_redirect_{h}"


def _add_favicon_route(app: FastAPI) -> None:
    """浏览器默认请求 /favicon.ico；无文件时 204，避免静态挂载前 404 刷屏。"""

    @app.get("/favicon.ico", include_in_schema=False)
    async def serve_favicon():
        if os.path.isfile(_FAVICON_PATH):
            return FileResponse(_FAVICON_PATH, media_type="image/x-icon")
        return Response(status_code=204)


def _add_upload_sw_route(app: FastAPI) -> None:
    @app.get("/upload-sw.js")
    async def serve_upload_service_worker():
        if not os.path.isfile(_UPLOAD_SW_PATH):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="upload-sw.js missing")
        return FileResponse(
            _UPLOAD_SW_PATH,
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"},
        )


def _apply_cors_and_auth_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(auth_kb_audit_middleware)


def _include_core_routers(app: FastAPI, *, include_admin: bool) -> None:
    app.include_router(public_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(auth_routes.user_compat_router)
    if include_admin:
        app.include_router(admin_routes.router)
    app.include_router(rag_routes.router)


def _mount_static_shared(app: FastAPI) -> None:
    app.mount("/static", StaticFiles(directory=_SHARED_DIR), name="static")


def _add_admin_html_no_cache_middleware(app: FastAPI) -> None:
    """管理端各 .html 易被浏览器强缓存，导致侧栏改版后仍显示旧导航；统一禁止缓存 HTML。"""

    @app.middleware("http")
    async def admin_html_no_cache(request: Request, call_next):
        response = await call_next(request)
        p = request.url.path
        if p.startswith("/admin/") and (p.endswith(".html") or p == "/admin" or p.endswith("/")):
            response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
        return response


def _register_legacy_admin_redirects(app: FastAPI, target_base: str = "") -> None:
    """target_base 如 http://127.0.0.1:8766，用于用户站把旧书签指到管理端。"""
    for legacy, path in _LEGACY_ADMIN_REDIRECTS.items():
        dest = f"{target_base.rstrip('/')}{path}" if target_base else path
        app.add_api_route(
            legacy,
            _redirect_handler(dest),
            methods=["GET", "HEAD"],
            operation_id=_legacy_redirect_operation_id(legacy),
            include_in_schema=False,
        )


def create_user_application() -> FastAPI:
    """
    仅用户前端 + 业务 API（不含 /api/admin）。
    环境变量 RAG_ADMIN_PUBLIC_ORIGIN（可选）：如 http://127.0.0.1:8766，
    用于 /admin*.html 旧书签 307 到管理端。
    """
    app = FastAPI(title="RAG Web — 用户站", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    _apply_cors_and_auth_middleware(app)

    admin_origin = (os.environ.get("RAG_ADMIN_PUBLIC_ORIGIN") or "").strip().rstrip("/")

    @app.middleware("http")
    async def reject_admin_api(request: Request, call_next):
        p = request.url.path
        if p.startswith("/api/admin/"):
            return JSONResponse(
                status_code=404,
                content={"detail": "管理接口已迁移至管理端进程，请使用管理站端口访问。"},
            )
        if p == "/api/auth/register-admin" and request.method == "POST":
            return JSONResponse(
                status_code=404,
                content={"detail": "管理员注册仅在管理端站点提供。"},
            )
        return await call_next(request)

    _include_core_routers(app, include_admin=False)
    _add_upload_sw_route(app)
    _add_favicon_route(app)
    _register_legacy_admin_redirects(app, target_base=admin_origin)
    _mount_static_shared(app)
    app.mount("/", StaticFiles(directory=_USER_DIR, html=True), name="user_web")
    return app


def create_admin_application() -> FastAPI:
    """
    管理前端 + 全量 API（含 /api/admin 与问答/文档等，供管理端页面调用）。
    根路径 / 重定向到 /admin/。
    """
    app = FastAPI(title="RAG Web — 管理站", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    _apply_cors_and_auth_middleware(app)
    _add_admin_html_no_cache_middleware(app)

    _include_core_routers(app, include_admin=True)
    _add_upload_sw_route(app)
    _add_favicon_route(app)
    for legacy, target in _LEGACY_ADMIN_REDIRECTS.items():
        app.add_api_route(
            legacy,
            _redirect_handler(target),
            methods=["GET", "HEAD"],
            operation_id=_legacy_redirect_operation_id(legacy),
            include_in_schema=False,
        )

    @app.get("/")
    async def root_to_admin():
        return RedirectResponse(url="/admin/users.html", status_code=307)

    _mount_static_shared(app)
    app.mount("/admin", StaticFiles(directory=_ADMIN_DIR, html=True), name="admin")
    return app


def create_full_application() -> FastAPI:
    """单进程：用户 / + 管理 /admin/（与历史行为一致）。"""
    app = FastAPI(title="RAG Web API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    _apply_cors_and_auth_middleware(app)
    _add_admin_html_no_cache_middleware(app)
    _include_core_routers(app, include_admin=True)
    _add_upload_sw_route(app)
    _add_favicon_route(app)
    for legacy, target in _LEGACY_ADMIN_REDIRECTS.items():
        app.add_api_route(
            legacy,
            _redirect_handler(target),
            methods=["GET", "HEAD"],
            operation_id=_legacy_redirect_operation_id(legacy),
            include_in_schema=False,
        )
    _mount_static_shared(app)
    app.mount("/admin", StaticFiles(directory=_ADMIN_DIR, html=True), name="admin")
    app.mount("/", StaticFiles(directory=_USER_DIR, html=True), name="user_web")
    return app
