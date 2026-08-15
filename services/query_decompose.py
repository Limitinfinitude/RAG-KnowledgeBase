"""将用户一句多问拆成多条检索子查询（启发式 + 可选 LLM），供 RAG / 即时文档多路召回。"""
from __future__ import annotations

import re
from typing import Any, List, Optional

_MAX_SUB = 5


def _dedupe_preserve(xs: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in xs:
        t = x.strip()
        if len(t) < 2:
            continue
        key = t.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out[:_MAX_SUB]


def decompose_queries_heuristic(query: str) -> List[str]:
    """按标点、分号、换行等拆分；尽量得到多条独立问句。"""
    q = (query or "").strip()
    if not q:
        return []

    # 多行：每行可视为一问
    lines = [ln.strip() for ln in re.split(r"[\r\n]+", q) if ln.strip()]
    if len(lines) > 1:
        return _dedupe_preserve(lines)

    # 中文问号 / 英文问号（避免拆「吗？」中间 - 按问号断句）
    parts = re.split(r"(?<=[？?])\s*", q)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) > 1:
        return _dedupe_preserve(parts)

    # 分号
    parts2 = re.split(r"[；;]\s*", q)
    parts2 = [p.strip() for p in parts2 if p.strip()]
    if len(parts2) > 1:
        return _dedupe_preserve(parts2)

    # 「还有/另外/以及」引导的第二问（轻量）
    m = re.split(r"(?:还有|另外|同时|此外|以及)(?=[^，。；]{2,})", q)
    if len(m) > 1:
        return _dedupe_preserve([x.strip() for x in m if x.strip()])

    return [q]


_MULTI_HINT = re.compile(
    r"(分别|各自|各是什么|分别是|哪些问题|哪几个|哪几类|几个方面|两个|三个|四个|五个|几个)"
)


def _should_try_llm_decompose(query: str) -> bool:
    if len(query.strip()) < 18:
        return False
    qm = query.count("？") + query.count("?")
    if qm >= 2:
        return True
    if _MULTI_HINT.search(query):
        return True
    return False


def decompose_queries_llm(query: str, llm: Any) -> List[str]:
    """用同一聊天模型拆子问句；失败则回退为整句。"""
    q = (query or "").strip()
    if not q:
        return []
    from utils.prompt_runtime import get_query_decompose_system
    from utils.rag_prompt_hardening import prepend_to_text_prompt

    sys_msg = prepend_to_text_prompt(get_query_decompose_system())
    try:
        from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415

        msgs = [
            SystemMessage(content=sys_msg),
            HumanMessage(content=q),
        ]
        resp = llm.bind(max_tokens=256).invoke(msgs)
        text = (getattr(resp, "content", None) or str(resp) or "").strip()
        lines = [ln.strip() for ln in re.split(r"[\r\n]+", text) if ln.strip()]
        lines = [re.sub(r"^[\d.\)、\s]+", "", ln) for ln in lines]
        lines = _dedupe_preserve(lines)
        if not lines:
            return [q]
        if len(lines) == 1 and len(lines[0]) > len(q) * 2:
            return [q]
        return lines[:_MAX_SUB]
    except Exception:
        return [q]


def decompose_for_retrieval(query: str, llm: Optional[Any] = None) -> List[str]:
    """
    对外入口：先启发式；若仍为一整句且像多意图，再用 LLM 细拆（与主对话共用模型）。
    """
    q = (query or "").strip()
    if not q:
        return []
    h = decompose_queries_heuristic(q)
    if len(h) >= 2:
        return h
    if llm is not None and _should_try_llm_decompose(q):
        m = decompose_queries_llm(q, llm)
        if len(m) >= 2:
            return m
    return [h[0]] if h else [q]
