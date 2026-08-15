from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException, Request
from fastapi.routing import APIRouter

from utils.auth_store import (
    User,
    count_login_failures_ip,
    count_login_failures_username,
    create_session,
    create_user,
    delete_session,
    delete_user_completely,
    get_user_by_username,
    log_login_event,
    log_platform_event,
    record_login_failure,
    update_user_profile,
    verify_password,
)
from utils.web_system_settings import get_login_bruteforce_settings
from web_app.backend.request_client import get_client_ip
from web_app.backend.schemas import DeleteAccountBody, LoginBody, MePatchBody, RegisterBody, WebUiStatePutBody
from web_app.backend.user_web_state import load_web_ui_state, save_web_ui_state

router = APIRouter(prefix="/api/auth", tags=["auth"])
# 旧版前端 / 缓存仍请求 /api/user/web-ui-state，与 /api/auth 行为一致。
user_compat_router = APIRouter(prefix="/api/user", tags=["user-compat"])


def _user_public(u) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "nickname": u.nickname,
        "role": u.role,
        "is_admin": u.is_admin,
        "avatar": getattr(u, "avatar", None) or None,
    }


def _register_response(body: RegisterBody, *, admin_portal: bool = False) -> dict:
    user = create_user(body.username, body.password, admin_portal=admin_portal)
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "role": user.role,
        "avatar": user.avatar,
    }


@router.post("/register")
def auth_register(body: RegisterBody):
    """普通用户注册（用户端页面应调用此路径）。"""
    try:
        return _register_response(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/register-admin")
def auth_register_admin(body: RegisterBody):
    """管理端注册页：新注册用户 role=admin（可与已有管理员并存，仍受「允许公开注册」开关约束）。"""
    try:
        return _register_response(body, admin_portal=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/login")
def auth_login(body: LoginBody, request: Request):
    ip = get_client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:400]
    uname_try = (body.username or "").strip()
    en, win_min, max_ip, max_user = get_login_bruteforce_settings()
    if en:
        if count_login_failures_ip(ip, window_minutes=win_min) >= max_ip:
            log_login_event(
                user_id=None,
                username=uname_try[:64] or None,
                outcome="fail_bruteforce_block_ip",
                ip=ip,
                user_agent=ua,
                detail=None,
            )
            raise HTTPException(status_code=429, detail="登录尝试过多，请稍后再试")
        if uname_try and count_login_failures_username(uname_try, window_minutes=win_min) >= max_user:
            log_login_event(
                user_id=None,
                username=uname_try[:64],
                outcome="fail_bruteforce_block_user",
                ip=ip,
                user_agent=ua,
                detail=None,
            )
            raise HTTPException(status_code=429, detail="登录尝试过多，请稍后再试")
    row = get_user_by_username(body.username)
    if row is None:
        record_login_failure(ip=ip, username=uname_try or None, reason="unknown_user")
        log_login_event(
            user_id=None,
            username=uname_try[:64] or None,
            outcome="fail_unknown_user",
            ip=ip,
            user_agent=ua,
            detail=None,
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    uid, uname, ph, nick, role, avatar, status = row
    if status != "active":
        record_login_failure(ip=ip, username=uname, reason="disabled")
        log_login_event(
            user_id=uid,
            username=uname,
            outcome="fail_disabled",
            ip=ip,
            user_agent=ua,
            detail=None,
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(body.password, ph):
        record_login_failure(ip=ip, username=uname, reason="bad_password")
        log_login_event(
            user_id=uid,
            username=uname,
            outcome="fail_password",
            ip=ip,
            user_agent=ua,
            detail=None,
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    log_login_event(
        user_id=uid,
        username=uname,
        outcome="success",
        ip=ip,
        user_agent=ua,
        detail=None,
    )
    user = User(id=uid, username=uname, nickname=nick, role=role, avatar=avatar, status=status)
    token, exp = create_session(user.id)
    return {
        "token": token,
        "expires_at": exp.isoformat(),
        "user": _user_public(user),
    }


@router.get("/me")
def auth_me(request: Request):
    u = request.state.user
    return _user_public(u)


@router.get("/web-ui-state")
def auth_get_web_ui_state(request: Request):
    """登录用户 Web 端状态（对话、偏好、人设、主题）；挂在 /api/auth 下，避免根路径 StaticFiles 误吞 /api/user/… 导致 404。"""
    return load_web_ui_state(request.state.user.id)


def _put_web_ui_state(request: Request, body: WebUiStatePutBody) -> dict:
    uid = request.state.user.id
    cur = load_web_ui_state(uid)
    if body.conversation_store is not None:
        cur["conversation_store"] = body.conversation_store
    if body.conversation_store_instant is not None:
        cur["conversation_store_instant"] = body.conversation_store_instant
    if body.chat_prefs is not None:
        cur["chat_prefs"] = body.chat_prefs
    if body.personas_store is not None:
        cur["personas_store"] = body.personas_store
    if body.theme is not None:
        cur["theme"] = body.theme.strip() or "dark"
    try:
        save_web_ui_state(uid, cur)
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e)) from e
    return {"ok": True}


@router.put("/web-ui-state")
def auth_put_web_ui_state(request: Request, body: WebUiStatePutBody):
    return _put_web_ui_state(request, body)


@user_compat_router.get("/web-ui-state")
def user_compat_get_web_ui_state(request: Request):
    return load_web_ui_state(request.state.user.id)


@user_compat_router.put("/web-ui-state")
def user_compat_put_web_ui_state(request: Request, body: WebUiStatePutBody):
    return _put_web_ui_state(request, body)


@router.patch("/me")
def auth_patch_me(request: Request, body: MePatchBody):
    raw: Dict[str, Any] = body.model_dump(exclude_unset=True)
    if not raw:
        raise HTTPException(status_code=400, detail="无更新字段")
    updates: Dict[str, Any] = {}
    if "nickname" in raw and raw["nickname"] is not None:
        nick = (raw["nickname"] or "").strip()
        if len(nick) < 1 or len(nick) > 32:
            raise HTTPException(status_code=400, detail="昵称为 1～32 个字符")
        updates["nickname"] = nick
    if "avatar" in raw:
        updates["avatar"] = raw["avatar"]
    if not updates:
        raise HTTPException(status_code=400, detail="无更新字段")
    try:
        nu = update_user_profile(request.state.user.id, updates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _user_public(nu)


@router.post("/logout")
def auth_logout(request: Request):
    auth = request.headers.get("authorization") or ""
    if auth.startswith("Bearer "):
        delete_session(auth[7:].strip())
    return {"ok": True}


@router.post("/delete-account")
def auth_delete_account(request: Request, body: DeleteAccountBody):
    u = request.state.user
    row = get_user_by_username(u.username)
    if row is None:
        raise HTTPException(status_code=400, detail="用户不存在")
    _uid, uname, ph, *_rest = row
    if body.confirm_text.strip() != uname:
        raise HTTPException(status_code=400, detail="确认文字必须与登录用户名完全一致")
    if not verify_password(body.password, ph):
        raise HTTPException(status_code=400, detail="密码错误")
    log_platform_event(
        actor_id=u.id,
        actor_username=u.username,
        action="self_delete_account",
        target=f"user:{u.id}",
        detail=None,
        client_ip=get_client_ip(request),
    )
    auth = request.headers.get("authorization") or ""
    if auth.startswith("Bearer "):
        delete_session(auth[7:].strip())
    try:
        delete_user_completely(u.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}
