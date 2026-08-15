from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from utils.auth_store import (
    create_message_quality_feedback,
    create_user_feedback,
    get_user_from_token,
)
from utils.web_system_settings import public_settings_dict
from web_app.backend.schemas import PublicFeedbackBody, PublicMessageQualityBody

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/settings")
def public_settings():
    return public_settings_dict()


@router.post("/feedback")
def public_post_feedback(request: Request, body: PublicFeedbackBody):
    """匿名或带 Bearer：匿名须填联系方式。"""
    uid = None
    uname = None
    auth = request.headers.get("authorization") or ""
    if auth.startswith("Bearer "):
        u = get_user_from_token(auth[7:].strip())
        if u is not None and int(u.id) > 0:
            uid = int(u.id)
            uname = u.username
    contact = (body.contact or "").strip() or None
    if uid is None:
        if not contact or len(contact) < 3:
            raise HTTPException(
                status_code=400,
                detail="未登录时请填写有效联系方式（至少 3 个字符）",
            )
    try:
        fid = create_user_feedback(
            user_id=uid,
            username=uname,
            title=body.title,
            content=body.content,
            contact=contact,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "id": fid}


@router.post("/message-quality-feedback")
def public_post_message_quality_feedback(request: Request, body: PublicMessageQualityBody):
    """登录则关联 user_id；访客也可提交（用于统计质量）。"""
    uid = None
    uname = None
    auth = request.headers.get("authorization") or ""
    if auth.startswith("Bearer "):
        u = get_user_from_token(auth[7:].strip())
        if u is not None and int(u.id) > 0:
            uid = int(u.id)
            uname = u.username
    try:
        mid = create_message_quality_feedback(
            user_id=uid,
            username=uname,
            rating=body.rating,
            page_mode=body.page_mode,
            client_conv_id=body.client_conv_id,
            message_index=body.message_index,
            user_message_excerpt=body.user_message_excerpt,
            assistant_excerpt=body.assistant_excerpt,
            client_meta=body.client_meta,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "id": mid}
