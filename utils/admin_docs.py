from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from config import WEB_USERS_ROOT
from utils.web_system_settings import is_kb_disabled_for_user


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kb_dir(user_id: int) -> str:
    return os.path.join(WEB_USERS_ROOT, str(int(user_id)), "knowledge_db")


def _meta_path(user_id: int) -> str:
    return os.path.join(_kb_dir(user_id), "documents_metadata.json")


def _load_user_meta(user_id: int) -> Dict[str, Any]:
    p = _meta_path(user_id)
    if not os.path.isfile(p):
        return {"documents": {}, "categories": ["默认知识库"]}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"documents": {}, "categories": ["默认知识库"]}
    if isinstance(data, dict):
        docs = data.get("documents")
        if isinstance(docs, dict):
            return {"documents": docs, "categories": data.get("categories") or ["默认知识库"]}
        if isinstance(docs, list):
            mapped = {str(d.get("file_name") or ""): d for d in docs if isinstance(d, dict)}
            return {"documents": mapped, "categories": data.get("categories") or ["默认知识库"]}
    if isinstance(data, list):
        mapped = {str(d.get("file_name") or ""): d for d in data if isinstance(d, dict)}
        return {"documents": mapped, "categories": ["默认知识库"]}
    return {"documents": {}, "categories": ["默认知识库"]}


def _save_user_meta(user_id: int, meta: Dict[str, Any]) -> None:
    p = _meta_path(user_id)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    docs = meta.get("documents") or {}
    cats = meta.get("categories") or ["默认知识库"]
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"documents": docs, "categories": cats}, f, ensure_ascii=False, indent=2)


def _iter_user_ids() -> List[int]:
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


def list_admin_documents(user_id: int | None = None, status: str = "active") -> List[Dict[str, Any]]:
    ids = [int(user_id)] if user_id is not None else _iter_user_ids()
    want_deleted = status == "deleted"
    out: List[Dict[str, Any]] = []
    for uid in ids:
        meta = _load_user_meta(uid)
        for name, d in (meta.get("documents") or {}).items():
            if not isinstance(d, dict):
                continue
            file_name = str(d.get("file_name") or name or "").strip()
            if not file_name:
                continue
            deleted = bool(d.get("is_deleted"))
            if want_deleted and not deleted:
                continue
            if (not want_deleted) and deleted:
                continue
            item = dict(d)
            item["file_name"] = file_name
            item["user_id"] = uid
            item["status"] = "deleted" if deleted else "active"
            out.append(item)
    out.sort(key=lambda x: str(x.get("update_time") or x.get("upload_time") or ""), reverse=True)
    return out


def soft_delete_document(user_id: int, file_name: str, actor_username: str | None = None) -> bool:
    meta = _load_user_meta(user_id)
    docs = meta.get("documents") or {}
    d = docs.get(file_name)
    if not isinstance(d, dict):
        return False
    d["is_deleted"] = True
    d["deleted_at"] = _now_iso()
    d["deleted_by"] = actor_username or "admin"
    d["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_user_meta(user_id, meta)
    return True


def restore_document(user_id: int, file_name: str) -> bool:
    meta = _load_user_meta(user_id)
    docs = meta.get("documents") or {}
    d = docs.get(file_name)
    if not isinstance(d, dict):
        return False
    d["is_deleted"] = False
    d.pop("deleted_at", None)
    d.pop("deleted_by", None)
    d["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_user_meta(user_id, meta)
    return True


def purge_deleted_documents(user_id: int | None = None) -> Tuple[int, int]:
    ids = [int(user_id)] if user_id is not None else _iter_user_ids()
    users_touched = 0
    removed = 0
    for uid in ids:
        meta = _load_user_meta(uid)
        docs = meta.get("documents") or {}
        keep: Dict[str, Any] = {}
        changed = False
        for name, d in docs.items():
            if isinstance(d, dict) and d.get("is_deleted"):
                removed += 1
                changed = True
                continue
            keep[name] = d
        if changed:
            users_touched += 1
            meta["documents"] = keep
            _save_user_meta(uid, meta)
    return removed, users_touched


def list_platform_kb_catalog(username_by_id: Dict[int, str]) -> List[Dict[str, Any]]:
    """全站用户知识库汇总（按 metadata 分类与文档统计）。"""
    ids = sorted(set(_iter_user_ids()) | set(username_by_id.keys()))
    rows: List[Dict[str, Any]] = []
    for uid in ids:
        meta = _load_user_meta(uid)
        cats = list(meta.get("categories") or ["默认知识库"])
        docs_raw = meta.get("documents") or {}
        by_cat: Dict[str, List[Dict[str, Any]]] = {}
        for _name, d in docs_raw.items():
            if not isinstance(d, dict) or d.get("is_deleted"):
                continue
            c = str(d.get("category") or "默认知识库")
            by_cat.setdefault(c, []).append(d)
        for cat in cats:
            if cat == "全部知识库":
                continue
            lst = by_cat.get(cat, [])
            uploads = sorted(str(x.get("upload_time") or "") for x in lst if x.get("upload_time"))
            rows.append(
                {
                    "user_id": uid,
                    "username": username_by_id.get(uid, "（无账号目录）"),
                    "category": cat,
                    "doc_count": len(lst),
                    "first_upload_time": uploads[0] if uploads else None,
                    "admin_disabled": is_kb_disabled_for_user(uid, cat),
                }
            )
    rows.sort(key=lambda x: (x["user_id"], x["category"]))
    return rows


def soft_delete_all_docs_in_category(
    user_id: int, category: str, actor_username: str | None = None
) -> int:
    meta = _load_user_meta(user_id)
    docs = meta.get("documents") or {}
    n = 0
    for _fn, d in list(docs.items()):
        if not isinstance(d, dict) or d.get("is_deleted"):
            continue
        if str(d.get("category") or "") != category:
            continue
        fn = str(d.get("file_name") or _fn or "").strip()
        if not fn:
            continue
        if soft_delete_document(user_id, fn, actor_username=actor_username):
            n += 1
    return n

