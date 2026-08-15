"""Web 多用户知识库体量统计（读各用户 documents_metadata.json）。"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from config import WEB_USERS_ROOT


def _user_kb_dir(user_id: int) -> str:
    return os.path.join(WEB_USERS_ROOT, str(int(user_id)), "knowledge_db")


def _meta_path(user_id: int) -> str:
    return os.path.join(_user_kb_dir(user_id), "documents_metadata.json")


def user_kb_doc_stats(user_id: int) -> Dict[str, Any]:
    p = _meta_path(user_id)
    if not os.path.isfile(p):
        return {"doc_count": 0, "total_chunks": 0, "total_size_mb": 0.0}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"doc_count": 0, "total_chunks": 0, "total_size_mb": 0.0}
    if isinstance(data, list):
        docs = [d for d in data if isinstance(d, dict)]
    elif isinstance(data, dict) and "documents" in data:
        raw_docs = data["documents"]
        if isinstance(raw_docs, dict):
            docs = [d for d in raw_docs.values() if isinstance(d, dict)]
        elif isinstance(raw_docs, list):
            docs = [d for d in raw_docs if isinstance(d, dict)]
        else:
            docs = []
    else:
        docs = []
    docs = [d for d in docs if not bool(d.get("is_deleted"))]
    total_chunks = 0
    total_size = 0.0
    for d in docs:
        if not isinstance(d, dict):
            continue
        total_chunks += int(d.get("chunks_count") or 0)
        total_size += float(d.get("file_size_mb") or 0)
    return {
        "doc_count": len(docs),
        "total_chunks": int(total_chunks),
        "total_size_mb": round(total_size, 2),
    }


def faiss_index_size_bytes(user_id: int) -> int:
    d = os.path.join(_user_kb_dir(user_id), "faiss_index")
    if not os.path.isdir(d):
        return 0
    n = 0
    for root, _, files in os.walk(d):
        for fn in files:
            try:
                n += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return n


def user_kb_dir_total_bytes(user_id: int) -> int:
    """用户 Web 数据目录总占用（含 knowledge_db、web_ui_state 等）。"""
    root = os.path.join(WEB_USERS_ROOT, str(int(user_id)))
    if not os.path.isdir(root):
        return 0
    n = 0
    for walk_root, _, files in os.walk(root):
        for fn in files:
            try:
                n += os.path.getsize(os.path.join(walk_root, fn))
            except OSError:
                pass
    return n


def list_registered_user_ids() -> List[int]:
    if not os.path.isdir(WEB_USERS_ROOT):
        return []
    out: List[int] = []
    for name in os.listdir(WEB_USERS_ROOT):
        p = os.path.join(WEB_USERS_ROOT, name)
        if not os.path.isdir(p):
            continue
        try:
            out.append(int(name))
        except ValueError:
            continue
    return sorted(out)
