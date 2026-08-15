"""上传内容敏感词扫描（服务端策略，非法律合规保证）。"""
from __future__ import annotations

import json
from typing import List

from utils.admin_docs import soft_delete_document
from utils.auth_store import log_platform_event
from utils.metadata_manager import update_document_metadata
from utils.web_system_settings import load_system_settings


def _parse_word_list(raw: str) -> List[str]:
    s = (raw or "").replace("\r\n", "\n")
    return [x.strip() for x in s.split("\n") if len(x.strip()) >= 2]


def decode_bytes_sample(data: bytes, max_len: int = 120_000) -> str:
    if not data:
        return ""
    chunk = data[:max_len]
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            return chunk.decode(enc)
        except UnicodeDecodeError:
            continue
    return chunk.decode("utf-8", errors="ignore")


def find_sensitive_hits(text: str, words: List[str]) -> List[str]:
    if not text or not words:
        return []
    folded = text.casefold()
    hits: List[str] = []
    for w in words:
        wf = w.casefold()
        if wf and wf in folded:
            hits.append(w)
        if len(hits) >= 24:
            break
    return hits


def apply_compliance_after_staged_ingest(user_id: int, file_name: str, raw_bytes: bytes) -> None:
    s = load_system_settings()
    words = _parse_word_list(str(s.get("sensitive_words") or ""))
    if not words:
        return
    text = decode_bytes_sample(raw_bytes)
    hits = find_sensitive_hits(text, words)
    if not hits:
        return
    update_document_metadata(
        file_name,
        compliance_flag="violation",
        compliance_hits=",".join(hits[:12]),
        compliance_note="敏感词自动扫描",
    )
    auto = bool(s.get("compliance_auto_disable", True))
    if auto:
        soft_delete_document(user_id, file_name, actor_username="compliance")
    log_platform_event(
        actor_id=None,
        actor_username="system",
        action="compliance_violation",
        target=f"user:{user_id} doc:{file_name}",
        detail=json.dumps({"hits": hits[:12], "auto_soft_deleted": auto}, ensure_ascii=False),
        client_ip=None,
    )
