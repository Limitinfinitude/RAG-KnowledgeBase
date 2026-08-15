"""认证与审计库：仅 MySQL（需 pymysql 与 config 中 MYSQL_*）。"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, List, Optional

from config import (
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
)
from utils.rag_mysql_tables import (
    RAG_MYSQL_ALTER_TRY,
    RAG_MYSQL_COLUMN_UPGRADES,
    RAG_MYSQL_DDL,
    RAG_MYSQL_INDEX_TRY,
)


def ensure_pymysql() -> None:
    try:
        import pymysql  # noqa: F401
    except ImportError as ex:
        raise RuntimeError("认证库使用 MySQL，请先安装：pip install pymysql") from ex


def is_integrity_error(exc: BaseException) -> bool:
    try:
        import pymysql.err

        return isinstance(exc, pymysql.err.IntegrityError)
    except ImportError:
        return False


class AuthConn:
    """pymysql 连接的链式 execute / fetch（SQL 使用 ? 占位符，内部转为 %s）。"""

    __slots__ = ("_raw", "kind", "_cur")

    def __init__(self, raw: Any):
        self._raw = raw
        self.kind = "mysql"
        self._cur: Any = None

    def _adapt_mysql(self, sql: str) -> str:
        s = sql.replace("username = ? COLLATE NOCASE", "LOWER(username) = LOWER(?)")
        s = s.replace("CAST(id AS TEXT)", "CAST(id AS CHAR)")
        return s.replace("?", "%s")

    def execute(self, sql: str, params: Optional[tuple[Any, ...]] = None):
        params = params or ()
        sql = self._adapt_mysql(sql)
        self._cur = self._raw.cursor()
        self._cur.execute(sql, params)
        return self

    def fetchone(self) -> Any:
        if self._cur is None:
            return None
        return self._cur.fetchone()

    def fetchall(self) -> List[Any]:
        if self._cur is None:
            return []
        return self._cur.fetchall()

    @property
    def lastrowid(self) -> int:
        if self._cur is None:
            return 0
        lid = getattr(self._cur, "lastrowid", None)
        return int(lid or 0)

    @property
    def rowcount(self) -> int:
        if self._cur is None:
            return 0
        return int(self._cur.rowcount or 0)


# 与 utils/auth_store.py 中 INSERT/SELECT 字段一致；时间戳存 ISO8601 字符串。
MYSQL_DDL: List[str] = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(32) NOT NULL COMMENT '登录名，唯一，与后端校验 3-32 一致',
        password_hash VARCHAR(256) NOT NULL COMMENT 'salt$hash 十六进制',
        created_at VARCHAR(40) NOT NULL COMMENT 'UTC ISO8601',
        nickname VARCHAR(32) NOT NULL DEFAULT '' COMMENT '展示名 1-32',
        role VARCHAR(16) NOT NULL DEFAULT 'user' COMMENT 'admin|user',
        avatar MEDIUMTEXT NULL COMMENT 'data:image/*;base64,...',
        status VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT 'active|disabled',
        disabled_at VARCHAR(40) NULL,
        last_login_at VARCHAR(40) NULL,
        UNIQUE KEY uq_users_username (username)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT UNSIGNED NOT NULL,
        token VARCHAR(64) NOT NULL,
        expires_at VARCHAR(40) NOT NULL,
        created_at VARCHAR(40) NOT NULL,
        UNIQUE KEY uq_sessions_token (token),
        KEY idx_sessions_expires (expires_at),
        KEY idx_sessions_user (user_id),
        CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS api_audit (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        created_at VARCHAR(40) NOT NULL,
        user_id BIGINT UNSIGNED NULL,
        username VARCHAR(128) NULL,
        method VARCHAR(16) NULL,
        path VARCHAR(2048) NULL,
        status_code INT NULL,
        duration_ms DOUBLE NULL,
        error VARCHAR(4000) NULL COMMENT '写入时截断约 2000 字符',
        KEY idx_api_audit_created (created_at),
        KEY idx_api_audit_path_uid (path(128), user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS login_audit (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        created_at VARCHAR(40) NOT NULL,
        user_id BIGINT UNSIGNED NULL,
        username VARCHAR(128) NULL,
        outcome VARCHAR(64) NOT NULL,
        ip VARCHAR(128) NULL,
        user_agent VARCHAR(500) NULL,
        detail VARCHAR(4000) NULL,
        KEY idx_login_audit_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS platform_audit (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        created_at VARCHAR(40) NOT NULL,
        actor_id BIGINT UNSIGNED NULL,
        actor_username VARCHAR(128) NULL,
        action VARCHAR(128) NOT NULL,
        target VARCHAR(500) NULL,
        detail VARCHAR(8000) NULL,
        client_ip VARCHAR(128) NULL,
        KEY idx_platform_audit_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # 全局配置 JSON（替代 system_settings.json；与 web_system_settings 字段一致）
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        id TINYINT UNSIGNED PRIMARY KEY,
        payload MEDIUMTEXT NOT NULL,
        updated_at VARCHAR(40) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # 登录失败计数（防暴力破解）；login_audit 为人读流水，本表为策略统计，不重复
    """
    CREATE TABLE IF NOT EXISTS login_failure (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        created_at VARCHAR(40) NOT NULL,
        ip VARCHAR(128) NOT NULL,
        username VARCHAR(32) NULL,
        reason VARCHAR(64) NOT NULL,
        KEY idx_login_failure_ip_created (ip, created_at),
        KEY idx_login_failure_user_created (username, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # 用户意见反馈
    """
    CREATE TABLE IF NOT EXISTS user_feedback (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        created_at VARCHAR(40) NOT NULL,
        user_id BIGINT UNSIGNED NULL,
        username VARCHAR(128) NULL,
        title VARCHAR(200) NOT NULL DEFAULT '',
        content TEXT NOT NULL,
        contact VARCHAR(128) NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'open',
        admin_reply MEDIUMTEXT NULL,
        replied_at VARCHAR(40) NULL,
        KEY idx_user_feedback_created (created_at),
        KEY idx_user_feedback_status (status),
        KEY idx_user_feedback_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]

# 已存在旧表时补齐列
_MYSQL_COLUMN_UPGRADES: List[tuple[str, str, str]] = [
    ("users", "nickname", "VARCHAR(32) NOT NULL DEFAULT ''"),
    ("users", "role", "VARCHAR(16) NOT NULL DEFAULT 'user'"),
    ("users", "avatar", "MEDIUMTEXT NULL"),
    ("users", "status", "VARCHAR(16) NOT NULL DEFAULT 'active'"),
    ("users", "disabled_at", "VARCHAR(40) NULL"),
    ("users", "last_login_at", "VARCHAR(40) NULL"),
    ("api_audit", "error", "VARCHAR(4000) NULL"),
    ("login_audit", "detail", "VARCHAR(4000) NULL"),
    ("platform_audit", "detail", "VARCHAR(8000) NULL"),
]


def _mysql_existing_columns(cur: Any, table: str) -> set[str]:
    cur.execute(
        """
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        """,
        (table,),
    )
    return {str(r["COLUMN_NAME"]).lower() for r in cur.fetchall()}


def _mysql_ensure_indexes(cur: Any) -> None:
    """补建可能缺失的二级索引（忽略已存在）。"""
    stmts = [
        "CREATE INDEX idx_api_audit_path_uid ON api_audit (path(128), user_id)",
    ]
    for sql in stmts:
        try:
            cur.execute(sql)
        except Exception:
            pass


def mysql_upgrade_schema(conn: Any, *, do_commit: bool = True) -> None:
    """对已存在的 MySQL 表追加缺失列与索引。"""
    cur = conn.cursor()
    try:
        for table, col, ddl in _MYSQL_COLUMN_UPGRADES + RAG_MYSQL_COLUMN_UPGRADES:
            have = _mysql_existing_columns(cur, table)
            if not have:
                continue
            if col.lower() not in have:
                cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{col}` {ddl}")
        _mysql_ensure_indexes(cur)
        for sql in RAG_MYSQL_INDEX_TRY:
            try:
                cur.execute(sql)
            except Exception:
                pass
        for sql in RAG_MYSQL_ALTER_TRY:
            try:
                cur.execute(sql.strip())
            except Exception:
                pass
    finally:
        cur.close()
    if do_commit:
        conn.commit()


def _mysql_connect():
    ensure_pymysql()
    import pymysql
    from pymysql.cursors import DictCursor

    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


def mysql_init_tables() -> None:
    ensure_pymysql()
    import pymysql

    try:
        raw = pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            charset="utf8mb4",
            autocommit=True,
        )
    except pymysql.err.OperationalError as e:
        raise RuntimeError(
            "无法连接 MySQL，请检查 MYSQL_HOST/MYSQL_USER/MYSQL_PASSWORD，并先创建数据库 "
            f"{MYSQL_DATABASE!r}（CREATE DATABASE ...）"
        ) from e
    try:
        with raw.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        raw.close()

    conn = _mysql_connect()
    try:
        cur = conn.cursor()
        for stmt in MYSQL_DDL + RAG_MYSQL_DDL:
            cur.execute(stmt.strip())
        cur.close()
        mysql_upgrade_schema(conn, do_commit=False)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_conn() -> Iterator[AuthConn]:
    raw = _mysql_connect()
    try:
        yield AuthConn(raw)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
