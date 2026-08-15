"""Brave Search API：为 RAG 追加网页摘要片段（需环境变量 BRAVE_SEARCH_API_KEY）。"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

_brave_log = logging.getLogger("rag.brave")


def _resolve_brave_timeout(default: float = 30.0) -> float:
    try:
        import config as c

        t = getattr(c, "BRAVE_SEARCH_TIMEOUT", None)
        if t is not None:
            return float(t)
    except Exception:
        pass
    try:
        return float(os.environ.get("BRAVE_SEARCH_TIMEOUT", str(default)))
    except ValueError:
        return default


def _resolve_brave_proxies() -> Optional[Dict[str, str]]:
    """仅 Brave 请求使用的代理；未配置则交给 requests 使用环境变量 HTTP(S)_PROXY。"""
    p = (os.environ.get("BRAVE_HTTPS_PROXY") or "").strip()
    if not p:
        try:
            import config as c

            p = (getattr(c, "BRAVE_HTTPS_PROXY", None) or "").strip()
        except Exception:
            p = ""
    if p:
        return {"http": p, "https": p}
    return None


def _friendly_brave_network_error(exc: BaseException) -> str:
    raw = str(exc).lower()
    if "timeout" in raw or "timed out" in raw:
        return (
            "连接 Brave 搜索（api.search.brave.com）超时。该域名在部分网络环境下无法直连（与 DeepSeek 等接口无关）。"
            "请尝试：1) 在系统或终端设置 HTTPS_PROXY；2) 或设置环境变量 BRAVE_HTTPS_PROXY（仅用于 Brave）；"
            "3) 或适当增加 BRAVE_SEARCH_TIMEOUT。详见 config.py 中说明。"
        )
    if "connection refused" in raw or "getaddrinfo failed" in raw or "name or service not known" in raw:
        return (
            "无法连接 Brave 搜索（DNS 失败或连接被拒绝）。请检查网络、代理与防火墙。"
        )
    return f"Brave 搜索请求失败：{exc}"


def _max_evidence_index(items: List[Dict[str, Any]]) -> int:
    m = 0
    for it in items:
        try:
            m = max(m, int(it.get("index") or 0))
        except (TypeError, ValueError):
            pass
    return m


def brave_web_search(
    query: str,
    api_key: str,
    *,
    count: int = 5,
    timeout: Optional[float] = None,
    proxies: Optional[Dict[str, str]] = None,
) -> List[Dict[str, str]]:
    """返回若干条 {title, url, description}；失败抛 requests.HTTPError 或 requests.RequestException。"""
    q = (query or "").strip()
    if not q:
        return []
    to = float(timeout) if timeout is not None else _resolve_brave_timeout()
    px = proxies if proxies is not None else _resolve_brave_proxies()
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key.strip(),
    }
    _brave_log.info(
        "Brave Web Search 请求: q=%r count=%s timeout=%s proxy=%s",
        q[:200],
        count,
        to,
        "on" if px else "off",
    )
    r = requests.get(
        BRAVE_WEB_SEARCH_URL,
        params={"q": q, "count": min(max(count, 1), 20)},
        headers=headers,
        timeout=to,
        proxies=px,
    )
    r.raise_for_status()
    data = r.json() if r.content else {}
    web = (data.get("web") or {}) if isinstance(data, dict) else {}
    results = web.get("results") if isinstance(web, dict) else None
    if not isinstance(results, list):
        top = list(data.keys()) if isinstance(data, dict) else type(data).__name__
        _brave_log.warning(
            "Brave 响应无有效 web.results，HTTP=%s top_keys=%s",
            r.status_code,
            top,
        )
        return []
    out: List[Dict[str, str]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip() or "无标题"
        url = str(item.get("url") or "").strip()
        desc = str(item.get("description") or item.get("snippet") or "").strip()
        out.append({"title": title, "url": url, "description": desc})
    if not out:
        _brave_log.warning(
            "Brave web.results 非空但解析后 0 条（原始条数=%s）",
            len(results),
        )
    else:
        _brave_log.info("Brave 返回可解析结果 %s 条", len(out))
    return out


def merge_brave_web_into_evidence(
    query: str,
    api_key: str,
    context_text: str,
    evidence_sources: Optional[List[Dict[str, Any]]],
    *,
    count: int = 5,
    timeout: Optional[float] = None,
) -> Tuple[str, List[Dict[str, Any]], bool, Optional[str]]:
    """
    在知识库编号上下文后追加 Brave 网页摘要，证据列表续编号。
    返回：(新 context_text, 新 evidence 列表, 是否追加了网页, 错误说明或 None)
    """
    ev = list(evidence_sources or [])
    ctx = context_text or ""
    try:
        rows = brave_web_search(query, api_key, count=count, timeout=timeout)
    except requests.HTTPError as e:
        msg = str(e)
        if e.response is not None and e.response.status_code in (401, 403):
            msg = "Brave 搜索 API 鉴权失败，请检查 BRAVE_SEARCH_API_KEY。"
        _brave_log.error("Brave HTTP 错误: %s", msg)
        return ctx, ev, False, msg
    except (requests.RequestException, ValueError, TypeError) as e:
        _brave_log.error("Brave 请求异常: %s", e)
        return ctx, ev, False, _friendly_brave_network_error(e)

    if not rows:
        _brave_log.warning("Brave 无可用摘要条目（可能无结果或字段不匹配），query=%r", (query or "")[:120])
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
                "metadata": {"url": url, "source": "brave_web"},
            }
        )
        parts.append(f"[来源{idx}] 文件：网页 — {title}\n{body}")

    frag = "\n\n".join(parts)
    header = "【联网检索摘要】\n\n"
    new_ctx = f"{ctx}\n\n{header}{frag}" if ctx.strip() else f"{header}{frag}"
    return new_ctx, ev, True, None
