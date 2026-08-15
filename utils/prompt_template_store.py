"""从 MySQL 读取全局提示词；带短 TTL 缓存，管理端保存后 invalidate。"""
from __future__ import annotations

import time
from typing import Optional

from utils.auth_db_backend import get_conn

_CACHE: dict[str, tuple[float, Optional[str]]] = {}
_TTL_SEC = 45.0


def invalidate_prompt_template_cache() -> None:
    _CACHE.clear()


def _fetch_prompt_body_from_db(slug: str) -> Optional[str]:
    s = (slug or "").strip()
    if not s:
        return None
    try:
        with get_conn() as conn:
            try:
                row = conn.execute(
                    """
                    SELECT template_body FROM prompt_templates
                    WHERE slug = ? AND user_id IS NULL
                      AND COALESCE(is_active, 1) = 1
                    ORDER BY id ASC LIMIT 1
                    """,
                    (s,),
                ).fetchone()
            except Exception:
                row = conn.execute(
                    """
                    SELECT template_body FROM prompt_templates
                    WHERE slug = ? AND user_id IS NULL
                    ORDER BY id ASC LIMIT 1
                    """,
                    (s,),
                ).fetchone()
        if not row:
            return None
        t = row["template_body"] if isinstance(row, dict) else row[0]
        out = str(t or "").strip()
        return out or None
    except Exception:
        return None


def get_builtin_prompt_body_cached(slug: str) -> Optional[str]:
    """有有效行则返回正文；否则 None（调用方用代码内建模板）。"""
    s = (slug or "").strip()
    if not s:
        return None
    now = time.time()
    ent = _CACHE.get(s)
    if ent is not None and now - ent[0] < _TTL_SEC:
        return ent[1]
    body = _fetch_prompt_body_from_db(s)
    _CACHE[s] = (now, body)
    return body


def get_builtin_prompt_body(slug: str) -> Optional[str]:
    """无缓存读库（管理端拉取全文等）。"""
    return _fetch_prompt_body_from_db(slug)
