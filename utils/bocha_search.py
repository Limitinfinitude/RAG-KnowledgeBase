"""博查 Bocha Web Search API（国内常用），POST https://api.bochaai.com/v1/web-search"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

BOCHA_WEB_SEARCH_URL = "https://api.bochaai.com/v1/web-search"

_log = logging.getLogger("rag.bocha")


def _max_evidence_index(items: List[Dict[str, Any]]) -> int:
    m = 0
    for it in items:
        try:
            m = max(m, int(it.get("index") or 0))
        except (TypeError, ValueError):
            pass
    return m


def _resolve_timeout(default: float = 30.0) -> float:
    try:
        return float(os.environ.get("BOCHA_SEARCH_TIMEOUT", str(default)))
    except ValueError:
        return default


def bocha_web_search(
    query: str,
    api_key: str,
    *,
    count: int = 5,
    timeout: Optional[float] = None,
) -> List[Dict[str, str]]:
    """返回若干条 {title, url, description}。"""
    q = (query or "").strip()
    if not q:
        return []
    to = float(timeout) if timeout is not None else _resolve_timeout()
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    body: Dict[str, Any] = {
        "query": q,
        "freshness": "noLimit",
        "summary": True,
        "count": min(max(count, 1), 20),
    }
    _log.info("Bocha Web Search 请求: q=%r count=%s timeout=%s", q[:200], body["count"], to)
    r = requests.post(BOCHA_WEB_SEARCH_URL, headers=headers, json=body, timeout=to)
    r.raise_for_status()
    data = r.json() if r.content else {}
    if not isinstance(data, dict):
        _log.warning("Bocha 响应非 JSON 对象")
        return []
    code = data.get("code")
    if code != 200:
        msg = str(data.get("msg") or data.get("message") or "未知错误")
        _log.error("Bocha 业务错误 code=%s msg=%s", code, msg[:300])
        raise ValueError(f"Bocha API 错误（code={code}）：{msg}")

    inner = data.get("data")
    if not isinstance(inner, dict):
        _log.warning("Bocha 响应无 data 对象, keys=%s", list(data.keys()))
        return []

    web_pages = inner.get("webPages")
    if not isinstance(web_pages, dict):
        _log.warning("Bocha 响应无 webPages, data_keys=%s", list(inner.keys()))
        return []

    results = web_pages.get("value")
    if not isinstance(results, list):
        return []

    out: List[Dict[str, str]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("name") or item.get("title") or "").strip() or "无标题"
        url = str(item.get("url") or "").strip()
        desc = str(
            item.get("summary") or item.get("snippet") or item.get("description") or ""
        ).strip()
        out.append({"title": title, "url": url, "description": desc})

    if out:
        _log.info("Bocha 返回可解析结果 %s 条", len(out))
    else:
        _log.warning("Bocha webPages.value 解析后 0 条")
    return out


def merge_bocha_web_into_evidence(
    query: str,
    api_key: str,
    context_text: str,
    evidence_sources: Optional[List[Dict[str, Any]]],
    *,
    count: int = 5,
    timeout: Optional[float] = None,
) -> Tuple[str, List[Dict[str, Any]], bool, Optional[str]]:
    ev = list(evidence_sources or [])
    ctx = context_text or ""
    try:
        rows = bocha_web_search(query, api_key, count=count, timeout=timeout)
    except requests.HTTPError as e:
        msg = str(e)
        _log.error("Bocha HTTP 错误: %s", msg)
        return ctx, ev, False, msg
    except ValueError as e:
        return ctx, ev, False, str(e)
    except (requests.RequestException, TypeError) as e:
        _log.error("Bocha 请求异常: %s", e)
        return ctx, ev, False, f"博查搜索请求失败：{e}"

    if not rows:
        _log.warning("Bocha 无可用摘要, query=%r", (query or "")[:120])
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
                "metadata": {"url": url, "source": "bocha_web"},
            }
        )
        parts.append(f"[来源{idx}] 文件：网页 — {title}\n{body}")

    frag = "\n\n".join(parts)
    header = "【联网检索摘要】\n\n"
    new_ctx = f"{ctx}\n\n{header}{frag}" if ctx.strip() else f"{header}{frag}"
    return new_ctx, ev, True, None
