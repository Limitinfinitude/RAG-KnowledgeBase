"""用户与登录会话：MySQL（config 中 MYSQL_*）。"""
from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import SESSION_DAYS
from utils.auth_db_backend import get_conn, is_integrity_error, mysql_init_tables
from utils.rag_mysql_bootstrap import bootstrap_rag_mysql_schema


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_nickname(username: str) -> str:
    u = (username or "").strip()
    return "用户" + u[:5]


def _hash_password(password: str, salt: bytes | None = None) -> str:
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return salt.hex() + "$" + dk.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
        return dk.hex() == hash_hex
    except Exception:
        return False


def bootstrap_auth_defaults(conn: Any) -> None:
    """规范化 status、补默认昵称、无管理员时首用户升为 admin。"""
    conn.execute("UPDATE users SET status = 'active' WHERE status IS NULL OR status = ''")
    for row in conn.execute("SELECT id, username FROM users").fetchall():
        uid, uname = int(row["id"]), str(row["username"])
        n = conn.execute("SELECT nickname FROM users WHERE id=?", (uid,)).fetchone()
        nick = str(n["nickname"] or "").strip() if n else ""
        if not nick:
            conn.execute(
                "UPDATE users SET nickname = ? WHERE id = ?",
                (default_nickname(uname), uid),
            )
    admin_row = conn.execute(
        "SELECT COUNT(*) AS c FROM users WHERE role = 'admin'"
    ).fetchone()
    admin_n = int(admin_row["c"] or 0) if admin_row else 0
    if admin_n == 0:
        first_row = conn.execute("SELECT MIN(id) AS m FROM users").fetchone()
        first = first_row["m"] if first_row else None
        if first is not None:
            conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (int(first),))
    now = _utc_now().isoformat()
    conn.execute(
        "INSERT IGNORE INTO app_settings (id, payload, updated_at) VALUES (1, '{}', ?)",
        (now,),
    )


def init_auth_db() -> None:
    mysql_init_tables()
    with get_conn() as conn:
        bootstrap_auth_defaults(conn)
        bootstrap_rag_mysql_schema(conn)


@dataclass
class User:
    id: int
    username: str
    nickname: str
    role: str
    avatar: Optional[str] = None
    status: str = "active"

    @property
    def is_admin(self) -> bool:
        return (self.role or "").lower() == "admin"


def _row_to_user(row: Any) -> User:
    nick = str(row["nickname"] if "nickname" in row.keys() else "") or default_nickname(
        str(row["username"])
    )
    role = str(row["role"] if "role" in row.keys() else "user") or "user"
    av = None
    if "avatar" in row.keys() and row["avatar"]:
        av = str(row["avatar"])
    status = str(row["status"] if "status" in row.keys() else "active") or "active"
    return User(
        id=int(row["id"]),
        username=str(row["username"]),
        nickname=nick,
        role=role,
        avatar=av,
        status=status,
    )


def create_user(username: str, password: str, *, admin_portal: bool = False) -> User:
    from utils.web_system_settings import is_registration_enabled

    if not is_registration_enabled():
        raise ValueError("当前已关闭注册")
    username = username.strip()
    if len(username) < 3 or len(username) > 32:
        raise ValueError("用户名长度为 3～32 个字符")
    if not all(c.isalnum() or c == "_" for c in username):
        raise ValueError("用户名仅允许字母、数字、下划线")
    if len(password) < 8:
        raise ValueError("密码至少 8 位")
    if len(password) > 128:
        raise ValueError("密码过长")
    ph = _hash_password(password)
    now = _utc_now().isoformat()
    nick = default_nickname(username)
    with get_conn() as conn:
        row_n = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        n_users = int(row_n["c"] or 0) if row_n else 0
        if admin_portal:
            # 管理端注册页：新账号一律为管理员（允许多个管理员并存）
            role_to_set = "admin"
        else:
            row_a = conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE LOWER(TRIM(COALESCE(role, ''))) = 'admin'"
            ).fetchone()
            admin_count = int(row_a["c"] or 0) if row_a else 0
            # 用户站：首个账号且库中尚无管理员时，设为管理员以便冷启动
            role_to_set = "admin" if n_users == 0 and admin_count == 0 else "user"

        try:
            cur = conn.execute(
                """
                INSERT INTO users (username, password_hash, created_at, nickname, role, status)
                VALUES (?, ?, ?, ?, ?, 'active')
                """,
                (username, ph, now, nick, role_to_set),
            )
            uid = int(cur.lastrowid)
        except Exception as e:
            if not is_integrity_error(e):
                raise
            raise ValueError("用户名已存在") from e
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, nickname, role, avatar, status FROM users WHERE id = ?",
            (uid,),
        ).fetchone()
    assert row is not None
    return _row_to_user(row)


def get_user_by_username(
    username: str,
) -> Optional[tuple[int, str, str, str, str, Optional[str], str]]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, username, password_hash, nickname, role, avatar, status
            FROM users WHERE username = ? COLLATE NOCASE
            """,
            (username.strip(),),
        ).fetchone()
    if row is None:
        return None
    av = row["avatar"] if row["avatar"] else None
    return (
        int(row["id"]),
        str(row["username"]),
        str(row["password_hash"]),
        str(row["nickname"] or "") or default_nickname(str(row["username"])),
        str(row["role"] or "user"),
        str(av) if av else None,
        str(row["status"] or "active"),
    )


def authenticate(username: str, password: str) -> Optional[User]:
    row = get_user_by_username(username)
    if row is None:
        return None
    uid, uname, ph, nick, role, avatar, status = row
    if not verify_password(password, ph):
        return None
    if status != "active":
        return None
    return User(id=uid, username=uname, nickname=nick, role=role, avatar=avatar, status=status)


def create_session(user_id: int) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    exp = _utc_now() + timedelta(days=SESSION_DAYS)
    now = _utc_now().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (user_id, token, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (user_id, token, exp.isoformat(), now),
        )
        conn.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (now, int(user_id)),
        )
    return token, exp


def delete_session(token: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def delete_user_sessions(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def get_user_from_token(token: str) -> Optional[User]:
    if not token:
        return None
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.nickname, u.role, u.avatar, u.status, s.expires_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
    if row is None:
        return None
    try:
        exp = datetime.fromisoformat(str(row["expires_at"]))
    except Exception:
        delete_session(token)
        return None
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if _utc_now() > exp:
        delete_session(token)
        return None
    if str(row["status"] or "active") != "active":
        delete_session(token)
        return None
    return _row_to_user(row)


def prune_expired_sessions() -> None:
    now = _utc_now().isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))


def update_user_profile(user_id: int, updates: Dict[str, Any]) -> User:
    """updates 可含 nickname、avatar（空字符串或 None 表示清除头像）。"""
    if not updates:
        raise ValueError("无更新字段")
    parts: List[str] = []
    params: List[Any] = []
    if "nickname" in updates:
        nickname = (updates["nickname"] or "").strip()
        if len(nickname) < 1 or len(nickname) > 32:
            raise ValueError("昵称为 1～32 个字符")
        parts.append("nickname = ?")
        params.append(nickname)
    if "avatar" in updates:
        av = updates["avatar"]
        if av is None or av == "":
            parts.append("avatar = NULL")
        else:
            s = str(av).strip()
            if len(s) > 350_000:
                raise ValueError("头像数据过大")
            if not s.startswith("data:image/") or ";base64," not in s:
                raise ValueError("头像须为 data:image/*;base64,... 格式")
            parts.append("avatar = ?")
            params.append(s)
    if not parts:
        raise ValueError("无有效更新字段")
    with get_conn() as conn:
        q = "UPDATE users SET " + ", ".join(parts) + " WHERE id = ?"
        conn.execute(q, (*params, user_id))
        row = conn.execute(
            "SELECT id, username, nickname, role, avatar, status FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        raise ValueError("用户不存在")
    return _row_to_user(row)


def update_user_password(user_id: int, new_password: str) -> None:
    """用户自助改密（调用方负责校验旧密码）。"""
    pwd = (new_password or "").strip()
    if len(pwd) < 8 or len(pwd) > 128:
        raise ValueError("密码长度须为 8～128 个字符")
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (_hash_password(pwd), user_id),
        )


def get_user_password_hash(user_id: int) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if row is None:
        return None
    return str(row["password_hash"]) if hasattr(row, "keys") else str(row[0])


def list_user_feedback_mine(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """用户端「我的反馈」：含处理状态与管理员回复（闭环展示）。"""
    limit = max(1, min(int(limit), 200))
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, title, content, status, admin_reply, replied_at
            FROM user_feedback WHERE user_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def list_users_admin(search: Optional[str] = None) -> List[Dict[str, Any]]:
    q = (search or "").strip()
    with get_conn() as conn:
        if not q:
            rows = conn.execute(
                """
                SELECT id, username, nickname, role, created_at, status, disabled_at, last_login_at
                FROM users ORDER BY id ASC
                """
            ).fetchall()
        else:
            like = f"%{q}%"
            rows = conn.execute(
                """
                SELECT id, username, nickname, role, created_at, status, disabled_at, last_login_at
                FROM users
                WHERE CAST(id AS TEXT) LIKE ? OR username LIKE ? OR IFNULL(nickname, '') LIKE ?
                ORDER BY id ASC
                """,
                (like, like, like),
            ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def set_user_role(target_user_id: int, role: str) -> None:
    r = (role or "").strip().lower()
    if r not in ("admin", "user"):
        raise ValueError("角色只能是 admin 或 user")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT role FROM users WHERE id = ?", (target_user_id,)
        ).fetchone()
        if row is None:
            raise ValueError("用户不存在")
        was_admin = str(row["role"] or "").lower() == "admin"
        if was_admin and r == "user":
            n = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM users WHERE role = 'admin'"
                ).fetchone()["c"]
                or 0
            )
            if n <= 1:
                raise ValueError("至少保留一名管理员")
        cur = conn.execute("UPDATE users SET role = ? WHERE id = ?", (r, target_user_id))
        if cur.rowcount == 0:
            raise ValueError("用户不存在")


def admin_create_user(username: str, password: str, role: str = "user") -> User:
    r = (role or "user").strip().lower()
    if r not in ("admin", "user"):
        raise ValueError("角色只能是 admin 或 user")
    username = username.strip()
    if len(username) < 3 or len(username) > 32:
        raise ValueError("用户名长度为 3～32 个字符")
    if not all(c.isalnum() or c == "_" for c in username):
        raise ValueError("用户名仅允许字母、数字、下划线")
    if len(password) < 8:
        raise ValueError("密码至少 8 位")
    if len(password) > 128:
        raise ValueError("密码过长")
    ph = _hash_password(password)
    now = _utc_now().isoformat()
    nick = default_nickname(username)
    with get_conn() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO users (username, password_hash, created_at, nickname, role, status)
                VALUES (?, ?, ?, ?, ?, 'active')
                """,
                (username, ph, now, nick, r),
            )
            uid = int(cur.lastrowid)
        except Exception as e:
            if not is_integrity_error(e):
                raise
            raise ValueError("用户名已存在") from e
        row = conn.execute(
            "SELECT id, username, nickname, role, avatar, status FROM users WHERE id = ?",
            (uid,),
        ).fetchone()
    assert row is not None
    return _row_to_user(row)


def admin_update_user(target_user_id: int, updates: Dict[str, Any]) -> None:
    if not updates:
        raise ValueError("无更新字段")
    parts: List[str] = []
    params: List[Any] = []
    if "nickname" in updates:
        nickname = (updates["nickname"] or "").strip()
        if len(nickname) < 1 or len(nickname) > 32:
            raise ValueError("昵称为 1～32 个字符")
        parts.append("nickname = ?")
        params.append(nickname)
    if "role" in updates:
        role = str(updates["role"] or "").strip().lower()
        if role not in ("admin", "user"):
            raise ValueError("角色只能是 admin 或 user")
        parts.append("role = ?")
        params.append(role)
    if "status" in updates:
        status = str(updates["status"] or "").strip().lower()
        if status not in ("active", "disabled"):
            raise ValueError("状态只能是 active 或 disabled")
        parts.append("status = ?")
        params.append(status)
        if status == "disabled":
            parts.append("disabled_at = ?")
            params.append(_utc_now().isoformat())
        else:
            parts.append("disabled_at = NULL")
    if not parts:
        raise ValueError("无有效更新字段")
    with get_conn() as conn:
        row = conn.execute("SELECT role FROM users WHERE id = ?", (target_user_id,)).fetchone()
        if row is None:
            raise ValueError("用户不存在")
        cur_role = str(row["role"] or "user").lower()
        next_role = (
            str(updates["role"] or "").strip().lower() if "role" in updates else cur_role
        )
        if cur_role == "admin" and next_role == "user":
            n = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM users WHERE role = 'admin'"
                ).fetchone()["c"]
                or 0
            )
            if n <= 1:
                raise ValueError("至少保留一名管理员")
        q = "UPDATE users SET " + ", ".join(parts) + " WHERE id = ?"
        cur = conn.execute(q, (*params, target_user_id))
        if cur.rowcount == 0:
            raise ValueError("用户不存在")
        if "status" in updates and str(updates["status"]).lower() == "disabled":
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (target_user_id,))


def admin_reset_password(target_user_id: int, new_password: str) -> None:
    pwd = str(new_password or "")
    if len(pwd) < 8:
        raise ValueError("密码至少 8 位")
    if len(pwd) > 128:
        raise ValueError("密码过长")
    ph = _hash_password(pwd)
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (ph, target_user_id),
        )
        if cur.rowcount == 0:
            raise ValueError("用户不存在")
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (target_user_id,))


def log_api_audit(
    *,
    user_id: Optional[int],
    username: Optional[str],
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    error: Optional[str] = None,
) -> None:
    now = _utc_now().isoformat()
    err = (error or "")[:2000]
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO api_audit (created_at, user_id, username, method, path, status_code, duration_ms, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now, user_id, username, method, path, status_code, duration_ms, err or None),
        )


def list_api_audit(limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, user_id, username, method, path, status_code, duration_ms, error
            FROM api_audit ORDER BY id DESC LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def get_user_chat_counts() -> Dict[int, int]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT user_id, COUNT(*) AS c
            FROM api_audit
            WHERE path = '/api/chat' AND user_id IS NOT NULL
            GROUP BY user_id
            """
        ).fetchall()
    out: Dict[int, int] = {}
    for r in rows:
        try:
            out[int(r["user_id"])] = int(r["c"] or 0)
        except Exception:
            continue
    return out


def log_login_event(
    *,
    user_id: Optional[int],
    username: Optional[str],
    outcome: str,
    ip: str,
    user_agent: str,
    detail: Optional[str] = None,
) -> None:
    now = _utc_now().isoformat()
    un = (username or "")[:128]
    oc = (outcome or "")[:64]
    ua = (user_agent or "")[:500]
    det = (detail or "")[:2000] or None
    ip_s = (ip or "")[:128]
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO login_audit (created_at, user_id, username, outcome, ip, user_agent, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (now, user_id, un or None, oc, ip_s or None, ua or None, det),
        )


def list_login_audit(limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, user_id, username, outcome, ip, user_agent, detail
            FROM login_audit ORDER BY id DESC LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def log_platform_event(
    *,
    actor_id: Optional[int],
    actor_username: Optional[str],
    action: str,
    target: Optional[str],
    detail: Optional[str],
    client_ip: Optional[str],
) -> None:
    now = _utc_now().isoformat()
    act = (action or "")[:128]
    tgt = (target or "")[:500] if target else None
    det = (detail or "")[:4000] if detail else None
    au = (actor_username or "")[:128] if actor_username else None
    ip = (client_ip or "")[:128] if client_ip else None
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO platform_audit (created_at, actor_id, actor_username, action, target, detail, client_ip)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (now, actor_id, au, act, tgt, det, ip),
        )


def list_platform_audit(limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, actor_id, actor_username, action, target, detail, client_ip
            FROM platform_audit ORDER BY id DESC LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def get_username_for_id(user_id: int) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (int(user_id),)).fetchone()
    if row is None:
        return None
    return str(row["username"] or "")


def delete_user_completely(user_id: int) -> None:
    """删除用户行（会话级联删除）并移除 WEB_USERS_ROOT 下该用户目录。"""
    import shutil

    from config import WEB_USERS_ROOT

    uid = int(user_id)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, role FROM users WHERE id = ?", (uid,)
        ).fetchone()
        if row is None:
            raise ValueError("用户不存在")
        if str(row["role"] or "").lower() == "admin":
            n = int(
                conn.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'admin'").fetchone()[
                    "c"
                ]
                or 0
            )
            if n <= 1:
                raise ValueError("不能删除最后一个管理员")
        conn.execute("UPDATE user_feedback SET user_id = NULL WHERE user_id = ?", (uid,))
        try:
            conn.execute(
                "UPDATE message_quality_feedback SET user_id = NULL, username = NULL WHERE user_id = ?",
                (uid,),
            )
        except Exception:
            pass
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    try:
        from utils.web_ui_state_mysql import delete_user_web_state_mysql

        delete_user_web_state_mysql(uid)
    except Exception:
        pass
    udir = os.path.join(WEB_USERS_ROOT, str(uid))
    if os.path.isdir(udir):
        shutil.rmtree(udir, ignore_errors=True)


def record_login_failure(*, ip: str, username: Optional[str], reason: str) -> None:
    now = _utc_now().isoformat()
    ip_s = (ip or "")[:128] or "unknown"
    un = ((username or "").strip()[:32] or None) if username else None
    rs = (reason or "")[:64] or "fail"
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO login_failure (created_at, ip, username, reason)
            VALUES (?, ?, ?, ?)
            """,
            (now, ip_s, un, rs),
        )


def count_login_failures_ip(ip: str, *, window_minutes: int) -> int:
    ip_s = (ip or "")[:128] or "unknown"
    win = max(1, int(window_minutes))
    cutoff = (_utc_now() - timedelta(minutes=win)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c FROM login_failure
            WHERE ip = ? AND created_at >= ?
            """,
            (ip_s, cutoff),
        ).fetchone()
    return int(row["c"] or 0) if row else 0


def count_login_failures_username(username: str, *, window_minutes: int) -> int:
    un = (username or "").strip()[:32]
    if not un:
        return 0
    win = max(1, int(window_minutes))
    cutoff = (_utc_now() - timedelta(minutes=win)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c FROM login_failure
            WHERE username = ? AND created_at >= ?
            """,
            (un, cutoff),
        ).fetchone()
    return int(row["c"] or 0) if row else 0


def list_login_failures(limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, ip, username, reason
            FROM login_failure ORDER BY id DESC LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def create_user_feedback(
    *,
    user_id: Optional[int],
    username: Optional[str],
    title: str,
    content: str,
    contact: Optional[str],
) -> int:
    now = _utc_now().isoformat()
    tit = (title or "").strip()[:200]
    body = (content or "").strip()
    if len(body) < 4:
        raise ValueError("反馈内容至少 4 个字符")
    if len(body) > 20000:
        raise ValueError("反馈内容过长")
    ct = (contact or "").strip()[:128] or None
    un = (username or "").strip()[:128] or None
    uid = int(user_id) if user_id is not None else None
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO user_feedback (created_at, user_id, username, title, content, contact, status)
            VALUES (?, ?, ?, ?, ?, ?, 'open')
            """,
            (now, uid, un, tit, body, ct),
        )
        return int(conn.lastrowid)


def create_message_quality_feedback(
    *,
    user_id: Optional[int],
    username: Optional[str],
    rating: str,
    page_mode: str,
    client_conv_id: Optional[str],
    message_index: Optional[int],
    user_message_excerpt: Optional[str],
    assistant_excerpt: Optional[str],
    client_meta: Optional[str],
) -> int:
    """问答页「有用 / 需改进」落库；未登录时 user_id 为空。"""
    r = (rating or "").strip().lower()
    if r not in ("good", "bad"):
        raise ValueError("rating 须为 good 或 bad")
    pm = (page_mode or "").strip().lower()
    if pm not in ("rag", "instant"):
        pm = "rag"
    now = _utc_now().isoformat()
    uid = int(user_id) if user_id is not None else None
    un = (username or "").strip()[:128] or None
    ccid = (client_conv_id or "").strip()[:128] or None
    mi = int(message_index) if message_index is not None else None
    uex = (user_message_excerpt or "").strip()[:2000] or None
    aex = (assistant_excerpt or "").strip()
    if len(aex) > 32000:
        aex = aex[:32000]
    aex = aex or None
    cmeta = (client_meta or "").strip()[:1000] or None
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO message_quality_feedback (
                created_at, user_id, username, rating, page_mode, client_conv_id,
                message_index, user_message_excerpt, assistant_excerpt, client_meta
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now, uid, un, r, pm, ccid, mi, uex, aex, cmeta),
        )
        return int(conn.lastrowid)


def list_message_quality_feedback_admin(
    limit: int = 100,
    offset: int = 0,
    rating: Optional[str] = None,
) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    rt = (rating or "").strip().lower() or None
    if rt and rt not in ("good", "bad"):
        rt = None
    with get_conn() as conn:
        if rt:
            rows = conn.execute(
                """
                SELECT id, created_at, user_id, username, rating, page_mode, client_conv_id,
                       message_index, user_message_excerpt,
                       LEFT(assistant_excerpt, 2000) AS assistant_excerpt_preview,
                       client_meta
                FROM message_quality_feedback WHERE rating = ?
                ORDER BY id DESC LIMIT ? OFFSET ?
                """,
                (rt, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, created_at, user_id, username, rating, page_mode, client_conv_id,
                       message_index, user_message_excerpt,
                       LEFT(assistant_excerpt, 2000) AS assistant_excerpt_preview,
                       client_meta
                FROM message_quality_feedback
                ORDER BY id DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def list_message_quality_feedback_export(
    limit: int = 100_000,
) -> List[Dict[str, Any]]:
    """全量导出（CSV/JSON），按 id 升序；上限防止误扫全表。"""
    lim = max(1, min(int(limit), 200_000))
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, user_id, username, rating, page_mode, client_conv_id,
                   message_index, user_message_excerpt, assistant_excerpt, client_meta
            FROM message_quality_feedback
            ORDER BY id ASC
            LIMIT ?
            """,
            (lim,),
        ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def list_user_feedback_admin(
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    st = (status or "").strip().lower() or None
    with get_conn() as conn:
        if st:
            rows = conn.execute(
                """
                SELECT id, created_at, user_id, username, title, content, contact, status, admin_reply, replied_at
                FROM user_feedback WHERE status = ?
                ORDER BY id DESC LIMIT ? OFFSET ?
                """,
                (st, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, created_at, user_id, username, title, content, contact, status, admin_reply, replied_at
                FROM user_feedback ORDER BY id DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def admin_update_feedback(
    feedback_id: int,
    *,
    status: Optional[str] = None,
    admin_reply: Optional[str] = None,
) -> None:
    fid = int(feedback_id)
    parts: List[str] = []
    params: List[Any] = []
    if status is not None:
        st = str(status).strip().lower()[:16]
        if st not in ("open", "processing", "closed"):
            raise ValueError("状态须为 open、processing 或 closed")
        parts.append("status = ?")
        params.append(st)
    if admin_reply is not None:
        parts.append("admin_reply = ?")
        params.append((admin_reply or "")[:16000])
        parts.append("replied_at = ?")
        params.append(_utc_now().isoformat())
    if not parts:
        raise ValueError("无更新字段")
    params.append(fid)
    sql = "UPDATE user_feedback SET " + ", ".join(parts) + " WHERE id = ?"
    with get_conn() as conn:
        cur = conn.execute(sql, tuple(params))
        if cur.rowcount == 0:
            raise ValueError("反馈不存在")
