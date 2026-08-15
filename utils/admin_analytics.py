"""管理端全站统计与运营指标（读 SQLite 用户表 + 各用户 knowledge_db 元数据）。"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from utils.admin_docs import _iter_user_ids, _load_user_meta, list_platform_kb_catalog
from utils.auth_store import list_users_admin
from web_app.backend.stats_helpers import (
    faiss_index_size_bytes,
    list_registered_user_ids,
    user_kb_doc_stats,
    user_kb_dir_total_bytes,
)


def _parse_upload_day(upload_time: str) -> Optional[str]:
    s = (upload_time or "").strip()
    if len(s) >= 10:
        return s[:10].replace("/", "-")
    return None


def _parse_iso_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _collect_upload_counts_by_day() -> Dict[str, int]:
    by_day: Dict[str, int] = defaultdict(int)
    for uid in _iter_user_ids():
        meta = _load_user_meta(uid)
        docs = meta.get("documents") or {}
        for d in docs.values():
            if not isinstance(d, dict) or d.get("is_deleted"):
                continue
            day = _parse_upload_day(str(d.get("upload_time") or ""))
            if day:
                by_day[day] += 1
    return dict(by_day)


def build_upload_trend(*, days: int = 30) -> List[Dict[str, Any]]:
    days = max(7, min(int(days), 90))
    by_day = _collect_upload_counts_by_day()
    today = datetime.now(timezone.utc).date()
    out: List[Dict[str, Any]] = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        out.append({"date": ds, "uploads": int(by_day.get(ds, 0))})
    return out


def platform_analytics_overview(*, trend_days: int = 30, active_days: int = 30) -> Dict[str, Any]:
    trend_days = max(7, min(int(trend_days), 90))
    active_days = max(1, min(int(active_days), 365))

    rows = list_users_admin()
    user_total = len(rows)
    cutoff = datetime.now(timezone.utc) - timedelta(days=active_days)
    users_active = 0
    for r in rows:
        dt = _parse_iso_dt(r.get("last_login_at"))
        if dt is not None and dt >= cutoff:
            users_active += 1

    name_by_id = {int(r["id"]): str(r.get("username") or "") for r in rows}
    kb_rows = list_platform_kb_catalog(name_by_id)
    knowledge_bases_total = len(kb_rows)

    total_docs = 0
    total_chunks = 0
    total_faiss = 0
    for r in rows:
        uid = int(r["id"])
        st = user_kb_doc_stats(uid)
        total_docs += int(st["doc_count"])
        total_chunks += int(st["total_chunks"])
        total_faiss += faiss_index_size_bytes(uid)

    all_ids = sorted(set(list_registered_user_ids()) | {int(r["id"]) for r in rows})
    storage_bytes_total = sum(user_kb_dir_total_bytes(uid) for uid in all_ids)

    upload_trend = build_upload_trend(days=trend_days)
    uploads_in_window = sum(x["uploads"] for x in upload_trend)

    return {
        "user_total": user_total,
        "users_active": users_active,
        "active_users_window_days": active_days,
        "knowledge_bases_total": knowledge_bases_total,
        "documents_total": total_docs,
        "chunks_total": total_chunks,
        "storage_bytes_total": int(storage_bytes_total),
        "storage_mb_total": round(storage_bytes_total / (1024 * 1024), 2),
        "faiss_bytes_total": int(total_faiss),
        "faiss_mb_total": round(total_faiss / (1024 * 1024), 2),
        "disk_user_folders": len(all_ids),
        "upload_trend": upload_trend,
        "uploads_sum_in_trend": uploads_in_window,
        "trend_days": trend_days,
    }
