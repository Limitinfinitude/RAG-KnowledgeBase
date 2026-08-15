"""管理端：提示词模板、LLM 日志查询、表行数（白名单）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from utils.auth_db_backend import get_conn
from utils.prompt_template_store import invalidate_prompt_template_cache

_ADMIN_COUNT_TABLES: Tuple[str, ...] = (
    "users",
    "sessions",
    "prompt_templates",
    "llm_call_logs",
    "chat_sessions",
    "chat_messages",
    "chat_message_evidence",
    "kb_documents",
    "kb_chunks",
    "ingest_jobs",
    "faiss_index_registry",
    "user_preferences",
    "ai_model_presets",
    "api_audit",
    "login_audit",
    "platform_audit",
    "user_feedback",
    "message_quality_feedback",
)


def _row_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {}


def list_prompt_templates_meta() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, slug, name, description, is_builtin, is_active, version,
                   created_at, updated_at, updated_by_username,
                   CHAR_LENGTH(template_body) AS body_chars
            FROM prompt_templates
            WHERE user_id IS NULL
            ORDER BY slug ASC
            """,
            (),
        ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        d = _row_dict(r)
        out.append(
            {
                "id": int(d.get("id") or 0),
                "slug": str(d.get("slug") or ""),
                "name": str(d.get("name") or ""),
                "description": d.get("description"),
                "is_builtin": int(d.get("is_builtin") or 0),
                "is_active": int(d.get("is_active") if d.get("is_active") is not None else 1),
                "version": int(d.get("version") or 1),
                "created_at": str(d.get("created_at") or ""),
                "updated_at": str(d.get("updated_at") or ""),
                "updated_by_username": d.get("updated_by_username"),
                "body_chars": int(d.get("body_chars") or 0),
            }
        )
    return out


def get_prompt_template_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    s = (slug or "").strip()
    if not s:
        return None
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, slug, name, template_body, description, is_builtin, is_active, version,
                   created_at, updated_at, updated_by_username
            FROM prompt_templates
            WHERE slug = ? AND user_id IS NULL
            LIMIT 1
            """,
            (s,),
        ).fetchone()
    if not row:
        return None
    d = _row_dict(row)
    return {
        "id": int(d.get("id") or 0),
        "slug": str(d.get("slug") or ""),
        "name": str(d.get("name") or ""),
        "template_body": str(d.get("template_body") or ""),
        "description": d.get("description"),
        "is_builtin": int(d.get("is_builtin") or 0),
        "is_active": int(d.get("is_active") if d.get("is_active") is not None else 1),
        "version": int(d.get("version") or 1),
        "created_at": str(d.get("created_at") or ""),
        "updated_at": str(d.get("updated_at") or ""),
        "updated_by_username": d.get("updated_by_username"),
    }


def update_prompt_template(
    slug: str,
    *,
    admin_username: str,
    template_body: str,
    patch: Optional[Dict[str, Any]] = None,
) -> bool:
    """patch 仅包含前端/路由显式传入的键（如 model_dump exclude_unset）。"""
    s = (slug or "").strip()
    if not s:
        return False
    body = (template_body or "").strip()
    if not body:
        return False
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    actor = (admin_username or "").strip()[:64] or None
    extra = patch or {}

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT name, description, is_active FROM prompt_templates
            WHERE slug = ? AND user_id IS NULL LIMIT 1
            """,
            (s,),
        ).fetchone()
        if not row:
            return False
        d = _row_dict(row)
        nm = str(d.get("name") or "")
        if "name" in extra:
            nm = str(extra.get("name") or "").strip()[:128]
        desc = d.get("description")
        if "description" in extra:
            ds = str(extra.get("description") or "").strip()
            desc = ds[:512] if ds else None
        act = int(d.get("is_active") if d.get("is_active") is not None else 1)
        if "is_active" in extra:
            act = 1 if extra.get("is_active") else 0
        conn.execute(
            """
            UPDATE prompt_templates
            SET template_body = ?, name = ?, description = ?, is_active = ?,
                version = version + 1, updated_at = ?, updated_by_username = ?
            WHERE slug = ? AND user_id IS NULL
            """,
            (body, nm, desc, act, now, actor, s),
        )

    invalidate_prompt_template_cache()
    return True


def list_llm_call_logs_mysql(
    *,
    limit: int = 50,
    offset: int = 0,
    call_type: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    lim = max(1, min(int(limit), 500))
    off = max(0, int(offset))
    ctype = (call_type or "").strip() or None
    if ctype and len(ctype) > 32:
        ctype = ctype[:32]

    with get_conn() as conn:
        if ctype:
            total_row = conn.execute(
                "SELECT COUNT(*) AS c FROM llm_call_logs WHERE call_type = ?",
                (ctype,),
            ).fetchone()
            rows = conn.execute(
                """
                SELECT id, created_at, user_id, session_id, call_type, model,
                       prompt_tokens, completion_tokens, total_tokens,
                       latency_ms, api_path, success, error_message
                FROM llm_call_logs
                WHERE call_type = ?
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (ctype, lim, off),
            ).fetchall()
        else:
            total_row = conn.execute("SELECT COUNT(*) AS c FROM llm_call_logs", ()).fetchone()
            rows = conn.execute(
                """
                SELECT id, created_at, user_id, session_id, call_type, model,
                       prompt_tokens, completion_tokens, total_tokens,
                       latency_ms, api_path, success, error_message
                FROM llm_call_logs
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (lim, off),
            ).fetchall()

    tr = _row_dict(total_row)
    total = int(tr.get("c") or 0)
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        d = _row_dict(r)
        out.append(
            {
                "id": int(d.get("id") or 0),
                "created_at": str(d.get("created_at") or ""),
                "user_id": d.get("user_id"),
                "session_id": d.get("session_id"),
                "call_type": str(d.get("call_type") or ""),
                "model": d.get("model"),
                "prompt_tokens": d.get("prompt_tokens"),
                "completion_tokens": d.get("completion_tokens"),
                "total_tokens": d.get("total_tokens"),
                "latency_ms": d.get("latency_ms"),
                "api_path": d.get("api_path"),
                "success": int(d.get("success") or 0),
                "error_message": d.get("error_message"),
            }
        )
    return out, total


def list_faiss_index_registry_admin(
    *,
    user_id: Optional[int] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit), 2000))
    uid = int(user_id) if user_id is not None else None
    with get_conn() as conn:
        if uid is not None and uid >= 1:
            rows = conn.execute(
                """
                SELECT r.id, r.user_id, r.index_kind, r.storage_key, r.embedding_model,
                       r.dimension, r.vector_count, r.linked_doc_count, r.status,
                       r.last_rebuilt_at, r.notes, r.updated_at,
                       u.username AS username
                FROM faiss_index_registry r
                LEFT JOIN users u ON u.id = r.user_id
                WHERE r.user_id = ?
                ORDER BY r.updated_at DESC
                LIMIT ?
                """,
                (uid, lim),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT r.id, r.user_id, r.index_kind, r.storage_key, r.embedding_model,
                       r.dimension, r.vector_count, r.linked_doc_count, r.status,
                       r.last_rebuilt_at, r.notes, r.updated_at,
                       u.username AS username
                FROM faiss_index_registry r
                LEFT JOIN users u ON u.id = r.user_id
                ORDER BY r.updated_at DESC
                LIMIT ?
                """,
                (lim,),
            ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        d = _row_dict(r)
        out.append(
            {
                "id": int(d.get("id") or 0),
                "user_id": int(d.get("user_id") or 0),
                "username": d.get("username"),
                "index_kind": str(d.get("index_kind") or ""),
                "storage_key": str(d.get("storage_key") or ""),
                "embedding_model": d.get("embedding_model"),
                "dimension": d.get("dimension"),
                "vector_count": int(d.get("vector_count") or 0),
                "linked_doc_count": int(d.get("linked_doc_count") or 0),
                "status": str(d.get("status") or ""),
                "last_rebuilt_at": d.get("last_rebuilt_at"),
                "notes": d.get("notes"),
                "updated_at": str(d.get("updated_at") or ""),
            }
        )
    return out


def patch_faiss_index_registry_admin(
    registry_id: int,
    *,
    notes: Optional[str] = None,
    status: Optional[str] = None,
    update_notes: bool = False,
    update_status: bool = False,
) -> bool:
    rid = int(registry_id)
    if rid < 1:
        return False
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    sets: List[str] = []
    args: List[Any] = []
    if update_notes:
        nt = str(notes or "").strip()[:512]
        sets.append("notes = ?")
        args.append(nt or None)
    if update_status:
        st = str(status or "").strip()[:32]
        if not st:
            return False
        sets.append("status = ?")
        args.append(st)
    if not sets:
        return False
    sets.append("updated_at = ?")
    args.append(now)
    args.append(rid)
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE faiss_index_registry SET {', '.join(sets)} WHERE id = ?",
            tuple(args),
        )
        return int(getattr(cur, "rowcount", 0) or 0) > 0


def admin_mysql_table_counts() -> Dict[str, int]:
    counts: Dict[str, int] = {}
    with get_conn() as conn:
        for t in _ADMIN_COUNT_TABLES:
            try:
                row = conn.execute(f"SELECT COUNT(*) AS c FROM `{t}`", ()).fetchone()
                d = _row_dict(row)
                counts[t] = int(d.get("c") or 0)
            except Exception:
                counts[t] = -1
    return counts
