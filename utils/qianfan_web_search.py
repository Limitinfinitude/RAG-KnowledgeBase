"""百度千帆 AI 搜索 web_search：POST /v2/ai_search/web_search（qianfan.baidubce.com）"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

QIANFAN_WEB_SEARCH_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"

_log = logging.getLogger("rag.qianfan")


def _query_char_units(s: str) -> int:
    """千帆限制：内容长度 72 个「字符位」，汉字计 2。"""
    n = 0
    for ch in s or "":
        n += 2 if "\u4e00" <= ch <= "\u9fff" else 1
    return n


def _truncate_qianfan_query(query: str, max_units: int = 72) -> str:
    q = (query or "").strip()
    if _query_char_units(q) <= max_units:
        return q
    out: List[str] = []
    u = 0
    for ch in q:
        c = 2 if "\u4e00" <= ch <= "\u9fff" else 1
        if u + c > max_units:
            break
        out.append(ch)
        u += c
    return "".join(out)


def _resolve_timeout(default: float = 30.0) -> float:
    try:
        return float(os.environ.get("QIANFAN_WEB_SEARCH_TIMEOUT", str(default)))
    except ValueError:
        return default


def qianfan_web_search(
    query: str,
    api_key: str,
    *,
    count: int = 10,
    timeout: Optional[float] = None,
    search_recency_filter: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    返回若干条 {title, url, description}，仅取 type=web 的 references。
    """
    content = _truncate_qianfan_query(query)
    if not content:
        return []
    top_k = min(max(int(count), 1), 50)
    to = float(timeout) if timeout is not None else _resolve_timeout()
    # 文档示例同时出现过 Authorization 与 X-Appbuilder-Authorization，双写兼容
    token = api_key.strip()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Appbuilder-Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body: Dict[str, Any] = {
        "messages": [{"role": "user", "content": content}],
        "search_source": "baidu_search_v2",
        "resource_type_filter": [{"type": "web", "top_k": top_k}],
    }
    rec = (search_recency_filter or os.environ.get("QIANFAN_SEARCH_RECENCY") or "").strip()
    if rec in ("week", "month", "semiyear", "year"):
        body["search_recency_filter"] = rec

    _log.info(
        "千帆 web_search 请求: content_len_units=%s top_k=%s timeout=%s",
        _query_char_units(content),
        top_k,
        to,
    )
    r = requests.post(QIANFAN_WEB_SEARCH_URL, headers=headers, json=body, timeout=to)
    r.raise_for_status()
    data = r.json() if r.content else {}
    if not isinstance(data, dict):
        _log.warning("千帆响应非 JSON 对象")
        return []

    refs = data.get("references")
    if refs is None and data.get("code") is not None:
        msg = str(data.get("message") or data.get("msg") or "未知错误")
        _log.error("千帆业务错误 code=%s msg=%s", data.get("code"), msg[:400])
        raise ValueError(f"千帆搜索错误：{msg}")

    if not isinstance(refs, list):
        _log.warning("千帆响应无 references 列表, keys=%s", list(data.keys()))
        return []

    out: List[Dict[str, str]] = []
    for item in refs:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "web").lower() != "web":
            continue
        title = str(item.get("title") or item.get("web_anchor") or "").strip() or "无标题"
        url = str(item.get("url") or "").strip()
        desc = str(item.get("content") or "").strip()
        if not url and not desc:
            continue
        out.append({"title": title, "url": url, "description": desc})

    if out:
        _log.info("千帆返回网页条数=%s", len(out))
    else:
        _log.warning("千帆 references 中无可用网页条目")
    return out


def merge_qianfan_web_into_evidence(
    query: str,
    api_key: str,
    context_text: str,
    evidence_sources: Optional[List[Dict[str, Any]]],
    *,
    count: int = 10,
    timeout: Optional[float] = None,
) -> Tuple[str, List[Dict[str, Any]], bool, Optional[str]]:
    def _max_evidence_index(items: List[Dict[str, Any]]) -> int:
        m = 0
        for it in items:
            try:
                m = max(m, int(it.get("index") or 0))
            except (TypeError, ValueError):
                pass
        return m

    ev = list(evidence_sources or [])
    ctx = context_text or ""
    try:
        rows = qianfan_web_search(query, api_key, count=count, timeout=timeout)
    except requests.HTTPError as e:
        _log.error("千帆 HTTP 错误: %s", e)
        return ctx, ev, False, str(e)
    except ValueError as e:
        return ctx, ev, False, str(e)
    except (requests.RequestException, TypeError) as e:
        _log.error("千帆请求异常: %s", e)
        return ctx, ev, False, f"千帆搜索请求失败：{e}"

    if not rows:
        return ctx, ev, False, None

    base = _max_evidence_index(ev) + 1
    parts: List[str] = []
    for i, row in enumerate(rows):
        idx = base + i
        title = row["title"]
        url = row["url"]
        desc = row["description"]
        body = f"链接：{url}\n摘要：{desc}" if url else desc
        ev.append(
            {
                "index": idx,
                "file": f"网页 — {title}",
                "content": body,
                "score": None,
                "chunk_level": "web",
                "metadata": {"url": url, "source": "qianfan_baidu_web"},
            }
        )
        parts.append(f"[来源{idx}] 文件：网页 — {title}\n{body}")

    frag = "\n\n".join(parts)
    header = "【联网检索摘要】\n\n"
    new_ctx = f"{ctx}\n\n{header}{frag}" if ctx.strip() else f"{header}{frag}"
    return new_ctx, ev, True, None
