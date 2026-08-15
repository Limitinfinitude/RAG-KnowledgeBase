"""即时文档通道：按管理端配置拉取联网摘要，拼入 system 提示（与 RAG 共用供应商与密钥）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from utils.bocha_search import merge_bocha_web_into_evidence
from utils.brave_search import merge_brave_web_into_evidence
from utils.qianfan_web_search import merge_qianfan_web_into_evidence
from utils.web_system_settings import (
    get_bocha_api_key_resolved,
    get_brave_api_key_resolved,
    get_qianfan_api_key_resolved,
    get_web_search_provider,
)


def fetch_instant_web_with_evidence(query: str) -> Tuple[str, bool, Optional[str], List[Dict[str, Any]]]:
    """
    返回可追加到 system 的联网摘要文本，以及网页证据列表（与 RAG 联网条目结构一致）。
    返回：(追加文本, 是否成功并入至少一条摘要, 错误说明或 None, evidence 列表)
    """
    q = (query or "").strip()
    if not q:
        return "", False, None, []

    provider = get_web_search_provider()
    ev: List[Dict[str, Any]] = []
    ctx = ""

    if provider == "bocha":
        key = get_bocha_api_key_resolved()
        if not key:
            return "", False, "未配置博查 API Key", []
        ctx2, ev2, has_web, err = merge_bocha_web_into_evidence(q, key, ctx, ev, count=5)
        return (ctx2 or ""), has_web, err, ev2
    if provider == "baidu":
        key = get_qianfan_api_key_resolved()
        if not key:
            return "", False, "未配置百度千帆 API Key", []
        ctx2, ev2, has_web, err = merge_qianfan_web_into_evidence(q, key, ctx, ev, count=8)
        return (ctx2 or ""), has_web, err, ev2
    key = get_brave_api_key_resolved()
    if not key:
        return "", False, "未配置 Brave Search API Key", []
    ctx2, ev2, has_web, err = merge_brave_web_into_evidence(q, key, ctx, ev, count=5)
    return (ctx2 or ""), has_web, err, ev2


def fetch_instant_web_block(query: str) -> Tuple[str, bool, Optional[str]]:
    """仅文本块；证据列表见 fetch_instant_web_with_evidence。"""
    ctx, ok, err, _ = fetch_instant_web_with_evidence(query)
    return ctx, ok, err
