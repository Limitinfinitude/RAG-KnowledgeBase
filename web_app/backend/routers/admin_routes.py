from __future__ import annotations

import csv
import io
import json
import os
import shutil
from typing import Any, Dict, List, Optional

import requests
from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRouter

from utils.admin_docs import (
    list_admin_documents,
    list_platform_kb_catalog,
    purge_deleted_documents,
    restore_document,
    soft_delete_all_docs_in_category,
    soft_delete_document,
)
from utils.auth_store import (
    User,
    admin_create_user,
    admin_reset_password,
    admin_update_feedback,
    admin_update_user,
    delete_user_completely,
    get_username_for_id,
    get_user_chat_counts,
    list_api_audit,
    list_login_audit,
    list_login_failures,
    list_message_quality_feedback_admin,
    list_message_quality_feedback_export,
    list_platform_audit,
    list_user_feedback_admin,
    list_users_admin,
    log_platform_event,
    set_user_role,
)
from utils.logger import get_recent_logs
from web_app.backend.admin_token_payload import build_admin_token_stats_payload
from utils.web_system_settings import (
    admin_settings_response,
    apply_chunk_levels_update,
    get_allowed_extensions,
    load_system_settings,
    merge_rag_defaults_patch,
    save_system_settings,
    set_kb_disabled_for_user,
)
from web_app.backend.request_client import get_client_ip
from web_app.backend.deps import get_admin_user
from utils.path_context import get_kb_dir
from web_app.backend.schemas import (
    AdminAdvancedSettingsBody,
    AdminDestroyUserBody,
    AdminFeedbackPatchBody,
    AdminKbSoftWipeBody,
    AdminKbToggleBody,
    AdminPromptTemplatePutBody,
    AdminResetPasswordBody,
    AdminRoleBody,
    AdminSettingsBody,
    AdminUserCreateBody,
    AdminUserPatchBody,
    AdminFaissRegistryPatchBody,
    AdminVectorUserBody,
    ClearAllBody,
    ModelFetchBody,
    VectorProviderBody,
)
from utils.rag_admin_store import (
    admin_mysql_table_counts,
    get_prompt_template_by_slug,
    list_faiss_index_registry_admin,
    list_llm_call_logs_mysql,
    list_prompt_templates_meta,
    patch_faiss_index_registry_admin,
    update_prompt_template,
)
from web_app.backend import vdb_cache
from web_app.backend.admin_vector_ops import (
    admin_delete_user_bm25,
    admin_reset_user_faiss,
    admin_vector_summary_users,
)
from utils.admin_analytics import platform_analytics_overview
from web_app.backend.stats_helpers import (
    faiss_index_size_bytes,
    list_registered_user_ids,
    user_kb_doc_stats,
)
router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
def admin_users(
    q: Optional[str] = Query(None, description="按用户ID、用户名或昵称模糊查询"),
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    rows = list_users_admin(search=q)
    chat_counts = get_user_chat_counts()
    out: List[Dict[str, Any]] = []
    for r in rows:
        uid = int(r["id"])
        st = user_kb_doc_stats(uid)
        st["vector_index_bytes"] = faiss_index_size_bytes(uid)
        st["chat_count"] = int(chat_counts.get(uid, 0))
        out.append({**dict(r), **st})
    return {"users": out}


@router.post("/users")
def admin_create_user_api(
    request: Request,
    body: AdminUserCreateBody,
    admin_user: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    try:
        u = admin_create_user(body.username, body.password, role=body.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    log_platform_event(
        actor_id=admin_user.id,
        actor_username=admin_user.username,
        action="admin_create_user",
        target=f"user:{u.id} @{u.username}",
        detail=None,
        client_ip=get_client_ip(request),
    )
    return {
        "id": u.id,
        "username": u.username,
        "nickname": u.nickname,
        "role": u.role,
        "status": u.status,
    }


@router.patch("/users/{user_id}")
def admin_patch_user(
    user_id: int,
    body: AdminUserPatchBody,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="无更新字段")
    try:
        admin_update_user(user_id, patch)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


@router.post("/users/{user_id}/reset-password")
def admin_reset_user_password(
    user_id: int,
    body: AdminResetPasswordBody,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    try:
        admin_reset_password(user_id, body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


@router.post("/users/{user_id}/destroy")
def admin_destroy_user(
    request: Request,
    user_id: int,
    body: AdminDestroyUserBody,
    admin_user: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    if not body.confirm:
        raise HTTPException(status_code=400, detail='需要 JSON 体 {"confirm": true, "typed_username": "..."}')
    uname = get_username_for_id(user_id)
    if uname is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if body.typed_username.strip() != uname:
        raise HTTPException(status_code=400, detail="输入的用户名与待删除账号不一致")
    if user_id == admin_user.id:
        raise HTTPException(status_code=400, detail="不能在此流程中删除当前登录管理员自身")
    try:
        delete_user_completely(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    log_platform_event(
        actor_id=admin_user.id,
        actor_username=admin_user.username,
        action="admin_delete_user",
        target=f"user:{user_id} @{uname}",
        detail=None,
        client_ip=get_client_ip(request),
    )
    return {"ok": True}


@router.get("/analytics/overview")
def admin_analytics_overview_api(
    trend_days: int = 30,
    active_days: int = 30,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    td = max(7, min(int(trend_days), 90))
    ad = max(1, min(int(active_days), 365))
    return platform_analytics_overview(trend_days=td, active_days=ad)


@router.get("/stats")
def admin_stats(_: User = Depends(get_admin_user)) -> Dict[str, Any]:
    rows = list_users_admin()
    total_docs = 0
    total_chunks = 0
    total_index = 0
    for r in rows:
        uid = int(r["id"])
        st = user_kb_doc_stats(uid)
        total_docs += int(st["doc_count"])
        total_chunks += int(st["total_chunks"])
        total_index += faiss_index_size_bytes(uid)
    disk_ids = list_registered_user_ids()
    return {
        "user_count": len(rows),
        "kb_folder_user_ids": disk_ids,
        "total_documents_all_users": total_docs,
        "total_chunks_all_users": total_chunks,
        "total_faiss_bytes_all_users": total_index,
    }


@router.get("/settings")
def admin_get_settings(_: User = Depends(get_admin_user)) -> Dict[str, Any]:
    return admin_settings_response()


@router.put("/settings")
def admin_put_settings(
    body: AdminSettingsBody,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}
    if body.registration_enabled is not None:
        patch["registration_enabled"] = bool(body.registration_enabled)
    if body.guest_mode_enabled is not None:
        patch["guest_mode_enabled"] = bool(body.guest_mode_enabled)
    if body.maintenance_mode_enabled is not None:
        patch["maintenance_mode_enabled"] = bool(body.maintenance_mode_enabled)
    if body.rate_limit_qpm_per_user is not None:
        patch["rate_limit_qpm_per_user"] = int(body.rate_limit_qpm_per_user)
    if body.max_upload_mb is not None:
        patch["max_upload_mb"] = int(body.max_upload_mb)
    if body.per_user_storage_mb is not None:
        patch["per_user_storage_mb"] = int(body.per_user_storage_mb)
    if body.per_user_max_upload_mb is not None:
        patch["per_user_max_upload_mb"] = int(body.per_user_max_upload_mb)
    if body.max_docs_per_user is not None:
        patch["max_docs_per_user"] = int(body.max_docs_per_user)
    if body.allowed_extensions is not None:
        exts = [str(x).lstrip(".").lower() for x in body.allowed_extensions if str(x).strip()]
        if not exts:
            raise HTTPException(status_code=400, detail="allowed_extensions 不能为空")
        patch["allowed_extensions"] = exts
    if body.sensitive_words is not None:
        patch["sensitive_words"] = str(body.sensitive_words)
    if body.compliance_auto_disable is not None:
        patch["compliance_auto_disable"] = bool(body.compliance_auto_disable)
    if body.login_bruteforce_enabled is not None:
        patch["login_bruteforce_enabled"] = bool(body.login_bruteforce_enabled)
    if body.login_bruteforce_window_minutes is not None:
        patch["login_bruteforce_window_minutes"] = int(body.login_bruteforce_window_minutes)
    if body.login_bruteforce_max_per_ip is not None:
        patch["login_bruteforce_max_per_ip"] = int(body.login_bruteforce_max_per_ip)
    if body.login_bruteforce_max_per_username is not None:
        patch["login_bruteforce_max_per_username"] = int(body.login_bruteforce_max_per_username)
    if body.rag_show_web_search_ui is not None:
        patch["rag_show_web_search_ui"] = bool(body.rag_show_web_search_ui)
    if body.instant_show_web_search_ui is not None:
        patch["instant_show_web_search_ui"] = bool(body.instant_show_web_search_ui)
    if not patch:
        raise HTTPException(status_code=400, detail="无更新字段")
    save_system_settings(patch)
    return admin_settings_response()


@router.put("/settings/advanced")
def admin_put_advanced_settings(
    body: AdminAdvancedSettingsBody,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}
    if body.system_prompt_extra is not None:
        patch["system_prompt_extra"] = body.system_prompt_extra.strip()
    if body.embedding_model_note is not None:
        patch["embedding_model_note"] = str(body.embedding_model_note).strip()[:500]
    # —— 嵌入/重排序 provider 配置（provider 为任意 vector_providers 中的 name，由归一化校验）——
    if body.embedding_provider is not None:
        patch["embedding_provider"] = str(body.embedding_provider).strip().lower()[:64]
    if body.embedding_model is not None:
        patch["embedding_model"] = str(body.embedding_model).strip()[:256]
    if body.rerank_provider is not None:
        patch["rerank_provider"] = str(body.rerank_provider).strip().lower()[:64]
    if body.rerank_model is not None:
        patch["rerank_model"] = str(body.rerank_model).strip()[:256]
    if body.rag_defaults is not None:
        patch["rag_defaults"] = merge_rag_defaults_patch(body.rag_defaults)
    if body.chunk_levels is not None:
        patch["chunk_levels"] = apply_chunk_levels_update(body.chunk_levels)
    if body.web_search_provider is not None:
        wsp = str(body.web_search_provider).strip().lower()
        patch["web_search_provider"] = wsp if wsp in ("brave", "bocha", "baidu") else "bocha"
    if body.bocha_api_key is not None and str(body.bocha_api_key).strip():
        patch["bocha_api_key"] = str(body.bocha_api_key).strip()
    if body.brave_api_key_server is not None and str(body.brave_api_key_server).strip():
        patch["brave_api_key_server"] = str(body.brave_api_key_server).strip()
    if body.qianfan_api_key is not None and str(body.qianfan_api_key).strip():
        patch["qianfan_api_key"] = str(body.qianfan_api_key).strip()
    if not patch:
        raise HTTPException(status_code=400, detail="无更新字段")
    save_system_settings(patch)
    return admin_settings_response()


def _classify_siliconflow_model(model_id: str) -> str:
    """按模型 id 命名推断硅基流动模型类型（其 /v1/models 不返回 type 字段）。"""
    low = str(model_id).lower()
    if "rerank" in low:
        return "rerank"
    if "embedding" in low or "bge-m3" in low or "bge-large" in low:
        return "embedding"
    return "chat"


@router.post("/models/fetch")
def admin_fetch_models(body: ModelFetchBody, _: User = Depends(get_admin_user)) -> Dict[str, Any]:
    """用提交的 base_url + api_key 拉取模型列表，按 chat / embedding / rerank 分类返回。

    api_key 留空时回退到后端已保存的 siliconflow provider 密钥。
    """
    key = (body.api_key or "").strip()
    base_url = (body.base_url or "").strip().rstrip("/")
    if not key:
        from utils.web_system_settings import get_rerank_config

        key = get_rerank_config().get("api_key") or ""
    if not key:
        raise HTTPException(status_code=400, detail="请先填写 API Key（或先保存 provider 密钥）")
    if not base_url:
        raise HTTPException(status_code=400, detail="请填写 Base URL")
    try:
        resp = requests.get(
            f"{base_url}/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"请求失败: {e}") from e
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"返回 {resp.status_code}: {resp.text[:200]}")
    data = resp.json().get("data") or []
    chat: List[str] = []
    embedding: List[str] = []
    rerank: List[str] = []
    for m in data:
        mid = str(m.get("id") or "").strip()
        if not mid:
            continue
        kind = _classify_siliconflow_model(mid)
        if kind == "embedding":
            embedding.append(mid)
        elif kind == "rerank":
            rerank.append(mid)
        else:
            chat.append(mid)
    chat.sort()
    embedding.sort()
    rerank.sort()
    return {"chat": chat, "embedding": embedding, "rerank": rerank, "total": len(chat) + len(embedding) + len(rerank)}


@router.get("/vector-providers")
def admin_get_vector_providers(_: User = Depends(get_admin_user)) -> Dict[str, Any]:
    from utils.web_system_settings import get_vector_providers

    providers = get_vector_providers()
    safe = []
    for p in providers:
        d = {k: (v if k != "api_key" else "") for k, v in p.items()}
        d["has_api_key"] = bool((p.get("api_key") or "").strip())
        safe.append(d)
    return {"providers": safe}


@router.post("/vector-providers")
def admin_add_vector_provider(body: VectorProviderBody, _: User = Depends(get_admin_user)) -> Dict[str, Any]:
    from utils.web_system_settings import load_system_settings, save_system_settings

    name = body.name.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="provider 名称不能为空")
    s = load_system_settings()
    providers = list(s.get("vector_providers") or [])
    if any(p.get("name") == name for p in providers):
        raise HTTPException(status_code=400, detail=f"provider「{name}」已存在")
    providers.append({
        "name": name,
        "label": (body.label or name).strip()[:64],
        "type": (body.type or "openai").strip().lower() if (body.type or "openai").strip().lower() in ("local", "openai") else "openai",
        "base_url": (body.base_url or "").strip()[:256],
        "api_key": (body.api_key or "").strip(),
    })
    save_system_settings({"vector_providers": providers})
    return {"ok": True}


@router.delete("/vector-providers/{name}")
def admin_delete_vector_provider(name: str, _: User = Depends(get_admin_user)) -> Dict[str, Any]:
    from utils.web_system_settings import load_system_settings, save_system_settings

    name = name.strip().lower()
    if name == "local":
        raise HTTPException(status_code=400, detail="本地 provider 不可删除")
    s = load_system_settings()
    providers = [p for p in (s.get("vector_providers") or []) if p.get("name") != name]
    if len(providers) == len(s.get("vector_providers") or []):
        raise HTTPException(status_code=404, detail=f"provider「{name}」不存在")
    patch = {"vector_providers": providers}
    # 若删除的是当前激活的 provider，回退到 local
    if s.get("embedding_provider") == name:
        patch["embedding_provider"] = "local"
    if s.get("rerank_provider") == name:
        patch["rerank_provider"] = "local"
    save_system_settings(patch)
    return {"ok": True}


@router.put("/vector-providers/{name}")
def admin_update_vector_provider(name: str, body: VectorProviderBody, _: User = Depends(get_admin_user)) -> Dict[str, Any]:
    """更新 provider 的 label/type/base_url/api_key（name 用作定位，不可改）。"""
    from utils.web_system_settings import load_system_settings, save_system_settings

    name = name.strip().lower()
    s = load_system_settings()
    providers = list(s.get("vector_providers") or [])
    target = next((p for p in providers if p.get("name") == name), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"provider「{name}」不存在")
    if body.label is not None and str(body.label).strip():
        target["label"] = str(body.label).strip()[:64]
    if body.type is not None and str(body.type).strip().lower() in ("local", "openai"):
        target["type"] = str(body.type).strip().lower()
    if body.base_url is not None and str(body.base_url).strip():
        target["base_url"] = str(body.base_url).strip()[:256]
    if body.api_key is not None and str(body.api_key).strip():
        target["api_key"] = str(body.api_key).strip()
    save_system_settings({"vector_providers": providers})
    return {"ok": True}


@router.get("/vector/summary")
def admin_vector_summary(_: User = Depends(get_admin_user)) -> Dict[str, Any]:
    rows = list_users_admin()
    db_ids = [int(r["id"]) for r in rows]
    disk_ids = list_registered_user_ids()
    all_ids = sorted(set(db_ids) | set(disk_ids))
    return {"users": admin_vector_summary_users(all_ids)}


@router.post("/vector/reset-faiss")
def admin_vector_reset_faiss(
    body: AdminVectorUserBody,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    admin_reset_user_faiss(body.user_id)
    vdb_cache.bump_user_cache(body.user_id)
    return {"ok": True, "user_id": body.user_id}


@router.post("/vector/delete-bm25")
def admin_vector_delete_bm25(
    body: AdminVectorUserBody,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    return admin_delete_user_bm25(body.user_id)


@router.get("/audit")
def admin_audit(
    limit: int = 200,
    offset: int = 0,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    return {"items": list_api_audit(limit=limit, offset=offset)}


@router.get("/login-audit")
def admin_login_audit(
    limit: int = 200,
    offset: int = 0,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    return {"items": list_login_audit(limit=limit, offset=offset)}


@router.get("/platform-audit")
def admin_platform_audit(
    limit: int = 200,
    offset: int = 0,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    return {"items": list_platform_audit(limit=limit, offset=offset)}


@router.get("/login-failures")
def admin_login_failures(
    limit: int = 200,
    offset: int = 0,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    """防暴力破解用失败计数流水（非 login_audit 人读流水）。"""
    return {"items": list_login_failures(limit=limit, offset=offset)}


@router.get("/message-quality-feedback")
def admin_list_message_quality_feedback(
    limit: int = 100,
    offset: int = 0,
    rating: Optional[str] = None,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    """助手消息点赞/点踩流水（表 message_quality_feedback）。"""
    return {
        "items": list_message_quality_feedback_admin(
            limit=limit, offset=offset, rating=rating
        )
    }


@router.get("/message-quality-feedback/export")
def admin_export_message_quality_feedback(
    kind: str = Query("csv", description="csv 或 json"),
    _: User = Depends(get_admin_user),
):
    """导出消息质量反馈（UTF-8；CSV 带 BOM 便于 Excel）。"""
    rows = list_message_quality_feedback_export()
    k = (kind or "csv").strip().lower()
    if k == "json":
        payload = json.dumps(rows, ensure_ascii=False).encode("utf-8")

        def gen_json():
            yield payload

        return StreamingResponse(
            gen_json(),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="message_quality_feedback.json"'
            },
        )
    buf = io.StringIO()
    buf.write("\ufeff")
    if rows:
        fieldnames = list(rows[0].keys())
        w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({fn: ("" if r.get(fn) is None else str(r.get(fn))) for fn in fieldnames})
    data = buf.getvalue().encode("utf-8")

    def gen_csv():
        yield data

    return StreamingResponse(
        gen_csv(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="message_quality_feedback.csv"'
        },
    )


@router.get("/faiss-registry")
def admin_faiss_registry_list(
    user_id: Optional[int] = Query(None, ge=1),
    limit: int = Query(500, ge=1, le=2000),
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    return {"items": list_faiss_index_registry_admin(user_id=user_id, limit=limit)}


@router.patch("/faiss-registry/{registry_id}")
def admin_faiss_registry_patch(
    registry_id: int,
    body: AdminFaissRegistryPatchBody,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    raw = body.model_dump(exclude_unset=True)
    ok = patch_faiss_index_registry_admin(
        registry_id,
        notes=raw.get("notes"),
        status=raw.get("status"),
        update_notes="notes" in raw,
        update_status="status" in raw,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="未找到记录或无可更新字段")
    return {"ok": True}


@router.get("/feedback")
def admin_list_feedback(
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    return {"items": list_user_feedback_admin(limit=limit, offset=offset, status=status)}


@router.patch("/feedback/{feedback_id}")
def admin_patch_feedback(
    feedback_id: int,
    body: AdminFeedbackPatchBody,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="无更新字段")
    try:
        admin_update_feedback(
            feedback_id,
            status=patch.get("status"),
            admin_reply=patch.get("admin_reply"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


@router.get("/knowledge-bases/catalog")
def admin_kb_catalog(_: User = Depends(get_admin_user)) -> Dict[str, Any]:
    rows_db = list_users_admin()
    name_by_id = {int(r["id"]): str(r.get("username") or "") for r in rows_db}
    return {"items": list_platform_kb_catalog(name_by_id)}


@router.post("/knowledge-bases/toggle")
def admin_kb_toggle(
    request: Request,
    body: AdminKbToggleBody,
    admin_user: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    set_kb_disabled_for_user(body.user_id, body.category, body.disabled)
    log_platform_event(
        actor_id=admin_user.id,
        actor_username=admin_user.username,
        action="kb_toggle_disabled" if body.disabled else "kb_toggle_enabled",
        target=f"user:{body.user_id} cat:{body.category}",
        detail=None,
        client_ip=get_client_ip(request),
    )
    return {"ok": True}


@router.post("/knowledge-bases/soft-wipe")
def admin_kb_soft_wipe(
    request: Request,
    body: AdminKbSoftWipeBody,
    admin_user: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    if not body.confirm:
        raise HTTPException(status_code=400, detail='需要 confirm: true')
    if body.typed_category.strip() != body.category.strip():
        raise HTTPException(status_code=400, detail="确认输入的知识库名称不一致")
    n = soft_delete_all_docs_in_category(
        body.user_id, body.category.strip(), actor_username=admin_user.username
    )
    log_platform_event(
        actor_id=admin_user.id,
        actor_username=admin_user.username,
        action="kb_soft_wipe_category",
        target=f"user:{body.user_id} cat:{body.category}",
        detail=f"docs_soft_deleted={n}",
        client_ip=get_client_ip(request),
    )
    vdb_cache.bump_user_cache(body.user_id)
    return {"ok": True, "soft_deleted": n}


@router.get("/prompt-templates")
def admin_prompt_templates_list(_: User = Depends(get_admin_user)) -> Dict[str, Any]:
    return {"items": list_prompt_templates_meta()}


@router.get("/prompt-templates/{slug}")
def admin_prompt_template_get(slug: str, _: User = Depends(get_admin_user)) -> Dict[str, Any]:
    row = get_prompt_template_by_slug(slug.strip())
    if not row:
        raise HTTPException(status_code=404, detail="未找到该模板")
    return row


@router.put("/prompt-templates/{slug}")
def admin_prompt_template_put(
    slug: str,
    body: AdminPromptTemplatePutBody,
    admin_user: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    s = slug.strip()
    if not s:
        raise HTTPException(status_code=400, detail="slug 无效")
    raw = body.model_dump(exclude_unset=True)
    template_body = raw.pop("template_body", None) or ""
    ok = update_prompt_template(
        s,
        admin_username=admin_user.username,
        template_body=template_body,
        patch=raw,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="未找到该模板或正文为空")
    row = get_prompt_template_by_slug(s)
    return {"ok": True, "item": row}


@router.get("/llm-mysql-logs")
def admin_llm_mysql_logs(
    limit: int = 50,
    offset: int = 0,
    call_type: Optional[str] = None,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    items, total = list_llm_call_logs_mysql(
        limit=limit,
        offset=offset,
        call_type=call_type,
    )
    return {
        "items": items,
        "total": total,
        "limit": max(1, min(int(limit), 500)),
        "offset": max(0, int(offset)),
    }


@router.get("/mysql-table-counts")
def admin_mysql_table_counts_api(_: User = Depends(get_admin_user)) -> Dict[str, Any]:
    return {"counts": admin_mysql_table_counts()}


@router.get("/token-stats")
def admin_token_stats(_: User = Depends(get_admin_user)) -> Dict[str, Any]:
    """汇总 statistics.json 中的 LLM token 记录（含按模型、按用户）。"""
    return build_admin_token_stats_payload()


@router.get("/tokens-summary")
def admin_tokens_summary(_: User = Depends(get_admin_user)) -> Dict[str, Any]:
    """与 token-stats 相同；部分网关/代理对带连字符的路径处理异常时可改用本路径。"""
    return build_admin_token_stats_payload()


@router.post("/clear-all-knowledge")
def admin_clear_all_knowledge(
    request: Request,
    body: ClearAllBody,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    """清空当前登录管理员（在 path_context 下）的个人知识库索引与元数据。"""
    if not body.confirm:
        raise HTTPException(status_code=400, detail='需要 JSON 体 {"confirm": true}')
    uid = request.state.user.id
    kb = get_kb_dir()
    index_dir = os.path.join(kb, "faiss_index")
    if os.path.isdir(index_dir):
        shutil.rmtree(index_dir)
    meta_path = os.path.join(kb, "documents_metadata.json")
    if os.path.isfile(meta_path):
        os.remove(meta_path)
    for name in ("bm25_index.pkl", "bm25_docs.pkl"):
        p = os.path.join(kb, name)
        if os.path.isfile(p):
            os.remove(p)
    vdb_cache.bump_user_cache(uid)
    return {"ok": True, "scope": "current_user_only"}


@router.get("/documents")
def admin_documents(
    user_id: int | None = None,
    status: str = "active",
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    st = (status or "active").strip().lower()
    if st not in ("active", "deleted"):
        raise HTTPException(status_code=400, detail="status 必须为 active 或 deleted")
    return {"documents": list_admin_documents(user_id=user_id, status=st)}


@router.post("/documents/delete")
def admin_soft_delete_document(
    user_id: int,
    file_name: str,
    admin_user: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    ok = soft_delete_document(int(user_id), str(file_name), actor_username=admin_user.username)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"ok": True}


@router.post("/documents/restore")
def admin_restore_document(
    user_id: int,
    file_name: str,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    ok = restore_document(int(user_id), str(file_name))
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"ok": True}


@router.post("/documents/purge")
def admin_purge_deleted_documents(
    user_id: int | None = None,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    removed, users_touched = purge_deleted_documents(user_id=user_id)
    return {"ok": True, "removed": int(removed), "users_touched": int(users_touched)}


@router.get("/logs")
def admin_logs(
    category: str = "queries",
    limit: int = 100,
    _: User = Depends(get_admin_user),
) -> Dict[str, Any]:
    lim = max(1, min(int(limit), 500))
    if category == "all":
        return {"items": get_recent_logs(limit=lim)}
    return {"items": get_recent_logs(category=category, limit=lim)}


@router.patch("/users/{user_id}/role")
def admin_user_role(
    user_id: int,
    body: AdminRoleBody,
    _: User = Depends(get_admin_user),
) -> Dict[str, str]:
    try:
        set_user_role(user_id, body.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


@router.get("/openapi.json")
def admin_openapi_schema(request: Request, _: User = Depends(get_admin_user)) -> Dict[str, Any]:
    """OpenAPI 规范（仅管理员，供 /admin/api-docs.html 加载）；用户站不暴露 /openapi.json。"""
    return request.app.openapi()
