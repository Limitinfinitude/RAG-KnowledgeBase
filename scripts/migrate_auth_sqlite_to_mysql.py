# -*- coding: utf-8 -*-
"""
将旧版 SQLite 单文件（默认 data/web/auth.db）中的认证与审计表一次性导入 MySQL。
应用已固定使用 MySQL；本脚本仅用于从遗留 auth.db 迁移数据。

使用前：
  1. 安装 pymysql；2. 配置与 config 一致的环境变量（MYSQL_*、MYSQL_DATABASE）；
  3. 可先启动一次应用以自动建表，或运行本脚本（会调用 mysql_init_tables）。

可选环境变量 AUTH_SQLITE_SOURCE：SQLite 文件绝对/相对路径（默认项目下 data/web/auth.db）。

用法（在项目根目录）:
  python scripts/migrate_auth_sqlite_to_mysql.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
)
from pymysql.cursors import DictCursor  # noqa: E402
from utils.auth_db_backend import mysql_init_tables  # noqa: E402

_DEFAULT_SQLITE = ROOT / "data" / "web" / "auth.db"


def _mysql() -> Any:
    import pymysql

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


def main() -> None:
    db_path = os.environ.get("AUTH_SQLITE_SOURCE") or str(_DEFAULT_SQLITE)
    if not os.path.isfile(db_path):
        print(f"未找到 SQLite 文件: {db_path}", file=sys.stderr)
        sys.exit(1)

    mysql_init_tables()

    sq = sqlite3.connect(db_path)
    sq.row_factory = sqlite3.Row
    my = _mysql()
    try:
        cur = my.cursor()
        cur.execute("SET FOREIGN_KEY_CHECKS=0")
        for t in (
            "ingest_jobs",
            "message_quality_feedback",
            "faiss_vector_mapping",
            "document_parse_logs",
            "kb_chunks",
            "kb_documents",
            "faiss_index_registry",
            "llm_call_logs",
            "chat_messages",
            "chat_sessions",
            "ai_model_presets",
            "user_preferences",
            "prompt_templates",
            "sys_data_dictionary",
            "sessions",
            "api_audit",
            "login_audit",
            "platform_audit",
            "login_failure",
            "user_feedback",
            "users",
        ):
            cur.execute(f"TRUNCATE TABLE `{t}`")
        cur.execute("SET FOREIGN_KEY_CHECKS=1")
        my.commit()

        users = sq.execute(
            "SELECT id, username, password_hash, created_at, nickname, role, avatar, status, disabled_at, last_login_at FROM users"
        ).fetchall()
        for r in users:
            cur.execute(
                """
                INSERT INTO users (id, username, password_hash, created_at, nickname, role, avatar, status, disabled_at, last_login_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    int(r["id"]),
                    str(r["username"]),
                    str(r["password_hash"]),
                    str(r["created_at"]),
                    str(r["nickname"] or ""),
                    str(r["role"] or "user"),
                    r["avatar"],
                    str(r["status"] or "active"),
                    r["disabled_at"],
                    r["last_login_at"],
                ),
            )

        for r in sq.execute("SELECT id, user_id, token, expires_at, created_at FROM sessions").fetchall():
            cur.execute(
                "INSERT INTO sessions (id, user_id, token, expires_at, created_at) VALUES (%s,%s,%s,%s,%s)",
                (
                    int(r["id"]),
                    int(r["user_id"]),
                    str(r["token"]),
                    str(r["expires_at"]),
                    str(r["created_at"]),
                ),
            )

        try:
            api_rows = sq.execute(
                "SELECT id, created_at, user_id, username, method, path, status_code, duration_ms, error FROM api_audit"
            ).fetchall()
        except sqlite3.OperationalError:
            api_rows = []
        for r in api_rows:
            cur.execute(
                """INSERT INTO api_audit (id, created_at, user_id, username, method, path, status_code, duration_ms, error)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    int(r["id"]),
                    str(r["created_at"]),
                    r["user_id"],
                    r["username"],
                    r["method"],
                    r["path"],
                    r["status_code"],
                    r["duration_ms"],
                    r["error"],
                ),
            )

        try:
            login_rows = sq.execute(
                "SELECT id, created_at, user_id, username, outcome, ip, user_agent, detail FROM login_audit"
            ).fetchall()
        except sqlite3.OperationalError:
            login_rows = []
        for r in login_rows:
            cur.execute(
                """INSERT INTO login_audit (id, created_at, user_id, username, outcome, ip, user_agent, detail)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    int(r["id"]),
                    str(r["created_at"]),
                    r["user_id"],
                    r["username"],
                    str(r["outcome"]),
                    r["ip"],
                    r["user_agent"],
                    r["detail"],
                ),
            )

        try:
            plat_rows = sq.execute(
                "SELECT id, created_at, actor_id, actor_username, action, target, detail, client_ip FROM platform_audit"
            ).fetchall()
        except sqlite3.OperationalError:
            plat_rows = []
        for r in plat_rows:
            cur.execute(
                """INSERT INTO platform_audit (id, created_at, actor_id, actor_username, action, target, detail, client_ip)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    int(r["id"]),
                    str(r["created_at"]),
                    r["actor_id"],
                    r["actor_username"],
                    str(r["action"]),
                    r["target"],
                    r["detail"],
                    r["client_ip"],
                ),
            )

        cur.execute("SELECT COALESCE(MAX(id), 0) AS mx FROM users")
        rmx = cur.fetchone()
        max_uid = int(rmx["mx"] if rmx else 0)
        if max_uid:
            cur.execute("ALTER TABLE users AUTO_INCREMENT = %s", (max_uid + 1,))

        my.commit()
        print(f"已从 {db_path} 导入到 MySQL 库 {MYSQL_DATABASE!r}，共 {len(users)} 个用户。")
    finally:
        my.close()
        sq.close()


if __name__ == "__main__":
    main()
