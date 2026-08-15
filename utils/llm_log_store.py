"""将 LLM 用量写入 MySQL `llm_call_logs`；失败静默，避免影响主流程。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from config import MYSQL_DATABASE, MYSQL_HOST, MYSQL_PASSWORD, MYSQL_PORT, MYSQL_USER
from utils.auth_db_backend import ensure_pymysql


def insert_llm_call_log_best_effort(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    model: str = "unknown",
    call_type: str = "qa",
    user_id: Optional[int] = None,
    session_id: Optional[int] = None,
    latency_ms: Optional[float] = None,
    api_path: Optional[str] = None,
    success: bool = True,
    error_message: Optional[str] = None,
) -> None:
    try:
        ensure_pymysql()
        import pymysql

        now = datetime.now(timezone.utc).isoformat()
        pt = int(prompt_tokens or 0)
        ct = int(completion_tokens or 0)
        tt = int(total_tokens or 0)
        uid = int(user_id) if user_id is not None else None
        sid = int(session_id) if session_id is not None else None
        lat = float(latency_ms) if latency_ms is not None else None
        path = (api_path or "").strip() or None
        if path and len(path) > 256:
            path = path[:256]
        err = (error_message or "").strip() or None
        if err and len(err) > 4000:
            err = err[:4000]
        m = (model or "unknown").strip() or "unknown"
        if len(m) > 128:
            m = m[:128]
        ctype = (call_type or "qa").strip() or "qa"
        if len(ctype) > 32:
            ctype = ctype[:32]

        raw = pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset="utf8mb4",
            autocommit=True,
        )
        try:
            with raw.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO llm_call_logs (
                        created_at, user_id, session_id, call_type, model,
                        prompt_tokens, completion_tokens, total_tokens,
                        latency_ms, api_path, success, error_message
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        now,
                        uid,
                        sid,
                        ctype,
                        m,
                        pt,
                        ct,
                        tt,
                        lat,
                        path,
                        1 if success else 0,
                        err,
                    ),
                )
        finally:
            raw.close()
    except Exception:
        pass
