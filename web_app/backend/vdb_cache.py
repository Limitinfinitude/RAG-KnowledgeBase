"""Web 多用户：按 user_id 缓存 (vector_db, embeddings)，变更后 bump 失效。

超出容量时按 LRU 淘汰，避免多用户轮流访问时内存无限增长（小内存机器必备）。
"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import Any, Dict, Tuple

_lock = threading.RLock()
_cache: "OrderedDict[int, Tuple[Any, Any, float]]" = OrderedDict()


def _max_cached_users() -> int:
    return max(1, int(os.environ.get("RAG_VDB_CACHE_MAX_USERS", "12")))


def get_cached_vdb_pair(user_id: int) -> Tuple[Any, Any]:
    from services.vector_store import load_embeddings_and_vector_db
    from utils.path_context import get_kb_dir

    kb = get_kb_dir()
    idx = os.path.join(kb, "faiss_index", "index.faiss")
    mtime = os.path.getmtime(idx) if os.path.isfile(idx) else 0.0
    uid = int(user_id)

    with _lock:
        hit = _cache.get(uid)
        if hit is not None and hit[2] == mtime:
            _cache.move_to_end(uid)
            return hit[0], hit[1]
        if hit is not None:
            del _cache[uid]

    vdb, emb = load_embeddings_and_vector_db()

    with _lock:
        _cache[uid] = (vdb, emb, mtime)
        _cache.move_to_end(uid)
        cap = _max_cached_users()
        while len(_cache) > cap:
            _cache.popitem(last=False)
    return vdb, emb


def bump_user_cache(user_id: int) -> None:
    with _lock:
        _cache.pop(int(user_id), None)


def clear_all_cache() -> None:
    with _lock:
        _cache.clear()


def cache_stats() -> Dict[str, int]:
    """运维/健康检查可选：当前缓存条目数与容量。"""
    with _lock:
        return {"vdb_cache_entries": len(_cache), "vdb_cache_cap": _max_cached_users()}
