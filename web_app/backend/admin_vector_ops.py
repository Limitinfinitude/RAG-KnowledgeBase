"""管理员向量库维护：按用户知识库目录操作 FAISS / BM25。"""
from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List

from langchain_community.vectorstores import FAISS

from config import WEB_USERS_ROOT
from utils.embedding import get_embeddings
from utils.metadata_manager import load_metadata, save_metadata
from utils.path_context import get_kb_dir, reset_kb_context, set_user_kb_context

from .stats_helpers import faiss_index_size_bytes, user_kb_doc_stats


def _kb_dir_for_user(user_id: int) -> str:
    return os.path.join(WEB_USERS_ROOT, str(int(user_id)), "knowledge_db")


def admin_vector_summary_users(user_ids: List[int]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for uid in user_ids:
        kb = _kb_dir_for_user(uid)
        bm25 = os.path.isfile(os.path.join(kb, "bm25_index.pkl"))
        st = user_kb_doc_stats(uid)
        out.append(
            {
                "user_id": int(uid),
                "faiss_bytes": faiss_index_size_bytes(uid),
                "bm25_index_exists": bm25,
                "doc_count": int(st["doc_count"]),
                "total_chunks": int(st["total_chunks"]),
                "kb_path": kb.replace("\\", "/"),
            }
        )
    return out


def admin_reset_user_faiss(user_id: int) -> Dict[str, Any]:
    """删除 FAISS 目录并写入空索引；将未删除文档的 chunks_count 置 0。"""
    t_kb, t_api = set_user_kb_context(user_id)
    try:
        kb = get_kb_dir()
        index_dir = os.path.join(kb, "faiss_index")
        if os.path.isdir(index_dir):
            shutil.rmtree(index_dir)
        emb = get_embeddings()
        empty_db = FAISS.from_texts(
            texts=["初始空文档"],
            embedding=emb,
            metadatas=[{"source_file": "system", "note": "empty_init"}],
        )
        os.makedirs(index_dir, exist_ok=True)
        empty_db.save_local(index_dir)
        meta = load_metadata()
        docs = meta.get("documents") or {}
        if isinstance(docs, dict):
            for _fn, d in docs.items():
                if isinstance(d, dict) and not d.get("is_deleted"):
                    d["chunks_count"] = 0
            save_metadata(meta)
        return {"ok": True, "user_id": int(user_id)}
    finally:
        reset_kb_context(t_kb, t_api)


def admin_delete_user_bm25(user_id: int) -> Dict[str, Any]:
    t_kb, t_api = set_user_kb_context(user_id)
    try:
        kb = get_kb_dir()
        removed = 0
        for name in ("bm25_index.pkl", "bm25_docs.pkl"):
            p = os.path.join(kb, name)
            if os.path.isfile(p):
                try:
                    os.remove(p)
                    removed += 1
                except OSError:
                    pass
        return {"ok": True, "user_id": int(user_id), "files_removed": removed}
    finally:
        reset_kb_context(t_kb, t_api)
