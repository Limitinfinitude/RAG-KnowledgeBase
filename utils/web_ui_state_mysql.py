"""登录用户 Web 端状态与 MySQL 同步：会话→chat_sessions/chat_messages，偏好→user_preferences。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from config import WEB_USERS_ROOT
from utils.auth_db_backend import get_conn

_PREF_LAYOUT_RAG = "web_conv_layout_rag"
_PREF_LAYOUT_INSTANT = "web_conv_layout_instant"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_from_ms(ms: Any) -> str:
    try:
        n = float(ms)
    except (TypeError, ValueError):
        return _iso_now()
    sec = n / 1000.0 if n > 1_000_000_000_000 else float(n)
    try:
        return datetime.fromtimestamp(sec, tz=timezone.utc).isoformat()
    except (OSError, ValueError, OverflowError):
        return _iso_now()


def _ms_from_iso(s: Any) -> int:
    if s is None:
        return int(datetime.now(timezone.utc).timestamp() * 1000)
    try:
        t = str(s).strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return int(datetime.now(timezone.utc).timestamp() * 1000)


def _set_pref(conn: Any, user_id: int, key: str, value: str) -> None:
    now = _iso_now()
    conn.execute(
        """
        INSERT INTO user_preferences (user_id, pref_key, pref_value, updated_at)
        VALUES (?, ?, ?, ?)
        ON DUPLICATE KEY UPDATE pref_value = VALUES(pref_value), updated_at = VALUES(updated_at)
        """,
        (int(user_id), key[:64], value, now),
    )


def _get_pref(conn: Any, user_id: int, key: str) -> Optional[str]:
    row = conn.execute(
        "SELECT pref_value FROM user_preferences WHERE user_id = ? AND pref_key = ? LIMIT 1",
        (int(user_id), key[:64]),
    ).fetchone()
    if not row:
        return None
    d = row if isinstance(row, dict) else dict(row)
    v = d.get("pref_value")
    return str(v) if v is not None else None


def _row_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {}


def mysql_has_any_web_state(user_id: int) -> bool:
    uid = int(user_id)
    with get_conn() as conn:
        r1 = conn.execute(
            "SELECT id FROM chat_sessions WHERE user_id = ? LIMIT 1",
            (uid,),
        ).fetchone()
        if r1:
            return True
        for pk in (_PREF_LAYOUT_RAG, _PREF_LAYOUT_INSTANT, "chat_prefs", "personas_store", "theme"):
            if _get_pref(conn, uid, pk):
                return True
    return False


def _sync_conversation_json_conn(conn: Any, user_id: int, mode: str, raw: Optional[str]) -> None:
    """在已有连接/事务内写入会话与消息。"""
    if not raw or not str(raw).strip():
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    order: List[str] = list(data.get("order") or [])
    conversations: Dict[str, Any] = data.get("conversations") or {}
    current_id = data.get("currentId")
    version = int(data.get("version") or 2)
    keys_in_store: Set[str] = set(conversations.keys())

    if keys_in_store:
        ph = ",".join(["?"] * len(keys_in_store))
        conn.execute(
            f"""
            DELETE FROM chat_sessions
            WHERE user_id = ? AND mode = ? AND client_conv_key IS NOT NULL
              AND client_conv_key NOT IN ({ph})
            """,
            (int(user_id), mode, *tuple(keys_in_store)),
        )
    else:
        conn.execute(
            "DELETE FROM chat_sessions WHERE user_id = ? AND mode = ?",
            (int(user_id), mode),
        )

    for cid in order:
        conv = conversations.get(cid)
        if not isinstance(conv, dict):
            continue
        ck = str(cid)[:128]
        title = str(conv.get("title") or "")[:512]
        updated_at = _iso_from_ms(conv.get("updatedAt"))
        payload_sql: Optional[str] = None
        if mode == "instant" and conv.get("instantDoc") is not None:
            try:
                payload_sql = json.dumps(conv["instantDoc"], ensure_ascii=False, default=str)
                if len(payload_sql) > 16_000_000:
                    payload_sql = payload_sql[:16_000_000]
            except (TypeError, ValueError):
                payload_sql = None

        row = conn.execute(
            """
            SELECT id FROM chat_sessions
            WHERE user_id = ? AND mode = ? AND client_conv_key = ? LIMIT 1
            """,
            (int(user_id), mode, ck),
        ).fetchone()
        d0 = _row_dict(row)
        if d0.get("id") is not None:
            sid = int(d0["id"])
            conn.execute(
                """
                UPDATE chat_sessions
                SET title = ?, updated_at = ?, session_payload = ?
                WHERE id = ?
                """,
                (title, updated_at, payload_sql, sid),
            )
        else:
            created = _iso_now()
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    user_id, title, mode, client_conv_key, session_payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (int(user_id), title, mode, ck, payload_sql, created, updated_at),
            )
            sid = int(conn.lastrowid)

        conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (sid,))
        msgs = conv.get("messages") or []
        if not isinstance(msgs, list):
            msgs = []
        for i, m in enumerate(msgs):
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "")[:16]
            content = str(m.get("content") or "")
            meta_obj = {}
            for k in ("meta", "timing", "latencyMs"):
                if k in m:
                    meta_obj[k] = m.get(k)
            meta_json: Optional[str] = None
            if meta_obj:
                try:
                    meta_json = json.dumps(meta_obj, ensure_ascii=False, default=str)
                except (TypeError, ValueError):
                    meta_json = None
            pt = m.get("prompt_tokens")
            ct = m.get("completion_tokens")
            pti = int(pt) if pt is not None and str(pt).strip() != "" else None
            cti = int(ct) if ct is not None and str(ct).strip() != "" else None
            conn.execute(
                """
                INSERT INTO chat_messages (
                    session_id, role, content, prompt_tokens, completion_tokens,
                    sort_order, meta_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, role, content, pti, cti, i, meta_json, _iso_now()),
            )
            mid = int(conn.lastrowid)
            srcs = m.get("sources")
            if (
                mid > 0
                and role == "assistant"
                and isinstance(srcs, list)
                and srcs
            ):
                for si, sv in enumerate(srcs):
                    if not isinstance(sv, dict):
                        continue
                    try:
                        ej = json.dumps(sv, ensure_ascii=False, default=str)
                    except (TypeError, ValueError):
                        continue
                    if len(ej) > 16_000_000:
                        ej = ej[:16_000_000]
                    try:
                        conn.execute(
                            """
                            INSERT INTO chat_message_evidence (
                                message_id, sort_order, evidence_json, created_at
                            ) VALUES (?, ?, ?, ?)
                            """,
                            (mid, si, ej, _iso_now()),
                        )
                    except Exception:
                        break

    layout = {"version": version, "currentId": current_id, "order": order}
    pref_key = _PREF_LAYOUT_RAG if mode == "rag" else _PREF_LAYOUT_INSTANT
    _set_pref(conn, user_id, pref_key, json.dumps(layout, ensure_ascii=False, default=str))


def sync_conversation_json_to_mysql(user_id: int, mode: str, raw: Optional[str]) -> None:
    with get_conn() as conn:
        _sync_conversation_json_conn(conn, user_id, mode, raw)


def build_conversation_json_from_mysql(user_id: int, mode: str) -> Optional[str]:
    uid = int(user_id)
    with get_conn() as conn:
        raw_layout = _get_pref(conn, uid, _PREF_LAYOUT_RAG if mode == "rag" else _PREF_LAYOUT_INSTANT)
        order: List[str] = []
        current_id: Any = None
        version = 2
        if raw_layout:
            try:
                layout = json.loads(raw_layout)
                order = list(layout.get("order") or [])
                current_id = layout.get("currentId")
                version = int(layout.get("version") or 2)
            except json.JSONDecodeError:
                order = []
        if not order:
            rows = conn.execute(
                """
                SELECT client_conv_key FROM chat_sessions
                WHERE user_id = ? AND mode = ? AND client_conv_key IS NOT NULL
                ORDER BY updated_at DESC
                """,
                (uid, mode),
            ).fetchall()
            order = [str(_row_dict(r).get("client_conv_key") or "") for r in rows or [] if r]
            order = [x for x in order if x]
            if not order:
                return None
            current_id = current_id or order[0]

        conversations: Dict[str, Any] = {}
        for cid in order:
            if not cid:
                continue
            srow = conn.execute(
                """
                SELECT id, title, updated_at, session_payload FROM chat_sessions
                WHERE user_id = ? AND mode = ? AND client_conv_key = ? LIMIT 1
                """,
                (uid, mode, cid[:128]),
            ).fetchone()
            if not srow:
                continue
            sd = _row_dict(srow)
            sid = int(sd["id"])
            mrows = conn.execute(
                """
                SELECT id, role, content, prompt_tokens, completion_tokens, sort_order, meta_json
                FROM chat_messages WHERE session_id = ?
                ORDER BY sort_order ASC, id ASC
                """,
                (sid,),
            ).fetchall()
            messages: List[Dict[str, Any]] = []
            for mr in mrows or []:
                md = _row_dict(mr)
                m: Dict[str, Any] = {
                    "role": md.get("role") or "",
                    "content": md.get("content") or "",
                }
                if md.get("prompt_tokens") is not None:
                    m["prompt_tokens"] = md["prompt_tokens"]
                if md.get("completion_tokens") is not None:
                    m["completion_tokens"] = md["completion_tokens"]
                legacy_sources: Optional[List[Any]] = None
                mj = md.get("meta_json")
                if mj:
                    try:
                        extra = json.loads(str(mj))
                        if isinstance(extra, dict):
                            for k, v in extra.items():
                                if v is None or k == "sources":
                                    continue
                                m[k] = v
                            ls = extra.get("sources")
                            if isinstance(ls, list):
                                legacy_sources = ls
                    except json.JSONDecodeError:
                        pass
                msg_id = md.get("id")
                sources_loaded: List[Dict[str, Any]] = []
                if msg_id is not None:
                    try:
                        ev_rows = conn.execute(
                            """
                            SELECT evidence_json FROM chat_message_evidence
                            WHERE message_id = ? ORDER BY sort_order ASC, id ASC
                            """,
                            (int(msg_id),),
                        ).fetchall()
                        for er in ev_rows or []:
                            ed = _row_dict(er)
                            raw_ej = ed.get("evidence_json")
                            if not raw_ej:
                                continue
                            try:
                                obj = json.loads(str(raw_ej))
                                if isinstance(obj, dict):
                                    sources_loaded.append(obj)
                            except json.JSONDecodeError:
                                pass
                    except Exception:
                        sources_loaded = []
                if sources_loaded:
                    m["sources"] = sources_loaded
                elif legacy_sources:
                    m["sources"] = legacy_sources
                messages.append(m)

            conv: Dict[str, Any] = {
                "title": sd.get("title") or "",
                "messages": messages,
                "updatedAt": _ms_from_iso(sd.get("updated_at")),
            }
            sp = sd.get("session_payload")
            if mode == "instant" and sp:
                try:
                    conv["instantDoc"] = json.loads(str(sp))
                except json.JSONDecodeError:
                    pass
            conversations[cid] = conv

        if not conversations:
            return None
        if current_id not in conversations:
            current_id = order[0] if order else next(iter(conversations.keys()))
        store = {
            "version": version,
            "currentId": current_id,
            "order": [x for x in order if x in conversations],
            "conversations": conversations,
        }
        return json.dumps(store, ensure_ascii=False, default=str)


def sync_web_ui_payload_to_mysql(user_id: int, payload: Dict[str, Any]) -> None:
    """写入 PUT /web-ui-state 合并后的完整 payload（单事务）。"""
    uid = int(user_id)
    with get_conn() as conn:
        if "conversation_store" in payload and payload["conversation_store"] is not None:
            _sync_conversation_json_conn(conn, uid, "rag", str(payload["conversation_store"]))
        if "conversation_store_instant" in payload and payload["conversation_store_instant"] is not None:
            _sync_conversation_json_conn(conn, uid, "instant", str(payload["conversation_store_instant"]))
        if "chat_prefs" in payload and payload["chat_prefs"] is not None:
            cp = payload["chat_prefs"]
            if isinstance(cp, dict):
                _set_pref(conn, uid, "chat_prefs", json.dumps(cp, ensure_ascii=False, default=str))
        if "personas_store" in payload and payload["personas_store"] is not None:
            ps = payload["personas_store"]
            if isinstance(ps, dict):
                _set_pref(conn, uid, "personas_store", json.dumps(ps, ensure_ascii=False, default=str))
        if "theme" in payload and payload["theme"] is not None:
            th = str(payload["theme"]).strip()[:32] or "dark"
            _set_pref(conn, uid, "theme", th)


def load_web_ui_state_from_mysql(user_id: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    uid = int(user_id)
    cs = build_conversation_json_from_mysql(uid, "rag")
    if cs:
        out["conversation_store"] = cs
    ci = build_conversation_json_from_mysql(uid, "instant")
    if ci:
        out["conversation_store_instant"] = ci
    with get_conn() as conn:
        raw = _get_pref(conn, uid, "chat_prefs")
        if raw:
            try:
                out["chat_prefs"] = json.loads(raw)
            except json.JSONDecodeError:
                pass
        raw = _get_pref(conn, uid, "personas_store")
        if raw:
            try:
                out["personas_store"] = json.loads(raw)
            except json.JSONDecodeError:
                pass
        raw = _get_pref(conn, uid, "theme")
        if raw is not None and str(raw).strip():
            out["theme"] = str(raw).strip()[:32]
    out["version"] = int(out.get("version") or 1)
    out["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return out


def delete_user_web_state_mysql(user_id: int) -> None:
    uid = int(user_id)
    with get_conn() as conn:
        conn.execute("DELETE FROM chat_sessions WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM user_preferences WHERE user_id = ?", (uid,))
    try:
        p = os.path.join(WEB_USERS_ROOT, str(uid), "web_ui_state.json")
        if os.path.isfile(p):
            os.remove(p)
    except OSError:
        pass
