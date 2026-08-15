"""将各用户 documents_metadata.json 同步到 MySQL kb_documents 表（渐进迁移）。

现状：对话/消息/偏好已 MySQL 为主；但「文档元数据」运行时仍以 documents_metadata.json
为主，kb_documents / kb_chunks / faiss_index_registry 三表为空（仅建了 DDL）。

本脚本做**幂等快照同步**（upsert），把 JSON 元数据落库，为将来「读切换」打基础，
**不改变现有入库流程**（入库仍写 JSON，本脚本只是额外同步一份到 MySQL）。

用法（项目根目录）::

    python scripts/sync_kb_docs_to_mysql.py [--user 1] [--all]

- 指定 --user N：仅同步该用户
- 指定 --all（默认）：同步全部用户
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config import WEB_USERS_ROOT  # noqa: E402
from utils.auth_db_backend import get_conn  # noqa: E402


def _list_users() -> List[int]:
    if not os.path.isdir(WEB_USERS_ROOT):
        return []
    out: List[int] = []
    for name in os.listdir(WEB_USERS_ROOT):
        try:
            out.append(int(name))
        except ValueError:
            continue
    return sorted(out)


def _load_metadata(user_id: int) -> Dict:
    path = os.path.join(WEB_USERS_ROOT, str(user_id), "knowledge_db", "documents_metadata.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [WARN] 读取 {path} 失败: {e}")
        return {}
    docs = data.get("documents")
    return docs if isinstance(docs, dict) else {}


def _upsert_doc(conn, user_id: int, file_name: str, category: str, size_bytes: int,
                file_ext: str, chunk_count: int, created_at: str, updated_at: str) -> None:
    conn.execute(
        """
        INSERT INTO kb_documents
            (user_id, file_name, storage_path, category, size_bytes, file_ext,
             parse_status, chunk_count, description, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'done', ?, '', ?, ?)
        ON DUPLICATE KEY UPDATE
            size_bytes = VALUES(size_bytes),
            chunk_count = VALUES(chunk_count),
            parse_status = 'done',
            updated_at = VALUES(updated_at)
        """,
        (int(user_id), file_name[:512], file_name[:1024], category[:128],
         int(size_bytes), (file_ext or "")[:32], int(chunk_count),
         created_at[:40], updated_at[:40]),
    )


def _sync_one_user(user_id: int) -> int:
    docs = _load_metadata(user_id)
    if not docs:
        return 0
    n = 0
    with get_conn() as conn:
        for file_name, meta in docs.items():
            if not isinstance(meta, dict):
                continue
            try:
                _upsert_doc(
                    conn,
                    user_id,
                    file_name,
                    category=str(meta.get("category") or "默认知识库"),
                    size_bytes=int(meta.get("file_size") or 0),
                    file_ext=str(meta.get("file_type") or ""),
                    chunk_count=int(meta.get("chunks_count") or 0),
                    created_at=str(meta.get("upload_time") or ""),
                    updated_at=str(meta.get("update_time") or meta.get("upload_time") or ""),
                )
                n += 1
            except Exception as e:
                print(f"  [WARN] 同步 {file_name} 失败: {e}")
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description="同步 documents_metadata.json → MySQL kb_documents")
    parser.add_argument("--user", type=int, default=None, help="仅同步指定用户")
    parser.add_argument("--all", action="store_true", default=True, help="同步全部用户（默认）")
    args = parser.parse_args()

    users = [args.user] if args.user is not None else _list_users()
    total = 0
    for uid in users:
        n = _sync_one_user(uid)
        total += n
        print(f"用户 {uid}: 同步 {n} 个文档")
    print(f"\n完成，共同步 {total} 个文档到 kb_documents 表。")


if __name__ == "__main__":
    main()
