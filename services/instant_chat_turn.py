"""即时文档对话：基于上传文档全文（超长则截断），不访问向量库；开启联网时可返回网页摘要溯源列表。"""
from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from services.chat_turn import (
    _append_persona_and_style_to_system_messages,
    _api_history_to_messages,
    _friendly_llm_error,
    _serialize_evidence,
    iter_astream_llm_chunks,
)
from utils.prompt_runtime import (
    format_instant_chat_short,
    format_instant_doc_system,
    format_instant_web_only_system,
    get_instant_intro,
)
from utils.rag_prompt_hardening import prepend_to_first_system, prepend_to_text_prompt
from services.instant_web_context import fetch_instant_web_with_evidence
from utils.intent_classifier import classify_intent_lightweight


def _yield_meta(
    mode: str,
    retrieval_query: str,
    error: Optional[str],
    sources: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "type": "meta",
        "mode": mode,
        "retrieval_query": retrieval_query or "",
        "sources": list(sources or []),
        "error": error,
    }


async def run_instant_chat_turn_astream(
    *,
    user_input: str,
    chat_history_messages: List[Dict[str, Any]],
    document_text: str,
    document_file_name: str,
    llm: Any,
    response_style: str = "balanced",
    persona_prompt: Optional[str] = None,
    system_prompt_extra: Optional[str] = None,
    user_id: Optional[int] = None,
    context_max_chars: int = 100_000,
    enable_web_search: bool = False,
) -> AsyncIterator[Dict[str, Any]]:
    doc = (document_text or "").strip()
    fname = (document_file_name or "文档").strip() or "文档"
    chat_history = _api_history_to_messages(chat_history_messages)

    if classify_intent_lightweight(user_input) == "CHAT":
        sys_kw = ["你是谁", "你是什么", "你叫什么", "介绍", "你能做什么", "功能", "怎么使用", "即时"]
        if any(kw in user_input for kw in sys_kw):
            yield _yield_meta("instant_chat", "", None)
            yield {"type": "chunk", "text": get_instant_intro()}
            yield {"type": "done"}
            return
        extra = ""
        if persona_prompt and str(persona_prompt).strip():
            extra = "\n\n【角色与风格】" + str(persona_prompt).strip()
        prompt = prepend_to_text_prompt(
            format_instant_chat_short(user_input=user_input, extra=extra)
        )
        yield _yield_meta("instant_chat", "", None)
        try:
            async for piece in iter_astream_llm_chunks(llm, prompt, user_id, "instant_chat"):
                yield {"type": "chunk", "text": piece}
        except Exception as e:
            yield {"type": "chunk", "text": _friendly_llm_error(e)}
        yield {"type": "done"}
        return

    if not doc:
        if not enable_web_search:
            yield _yield_meta("instant_no_doc", user_input, None)
            msg = "请先在输入框左侧点击加号上传文档（≤5MB，正文≤10万字符），或开启「联网」后针对公开信息提问。"
            yield {"type": "chunk", "text": msg}
            yield {"type": "done"}
            return
        web_text, has_web, web_err, web_ev = fetch_instant_web_with_evidence(user_input)
        if not has_web:
            yield _yield_meta("instant_no_doc", user_input, web_err)
            hint = web_err or "联网检索未返回摘要，请检查管理端搜索密钥或稍后再试。"
            yield {"type": "chunk", "text": hint}
            yield {"type": "done"}
            return
        web_sources = _serialize_evidence(web_ev)
        sys_base = format_instant_web_only_system(web_block=web_text, user_input=user_input)
        messages = prepend_to_first_system(
            [
                SystemMessage(content=sys_base),
                *chat_history,
                HumanMessage(content=user_input),
            ]
        )
        messages = _append_persona_and_style_to_system_messages(
            list(messages),
            response_style,
            persona_prompt,
            system_prompt_extra=system_prompt_extra,
        )
        yield _yield_meta("instant_web", user_input, web_err, sources=web_sources)
        try:
            async for piece in iter_astream_llm_chunks(llm, messages, user_id, "instant_web"):
                yield {"type": "chunk", "text": piece}
        except Exception as e:
            yield {"type": "chunk", "text": _friendly_llm_error(e)}
        yield {"type": "done"}
        return

    cap = max(4_000, min(int(context_max_chars), 100_000))
    body = doc if len(doc) <= cap else doc[:cap]

    web_append = ""
    web_err_meta: Optional[str] = None
    web_ev_doc: List[Dict[str, Any]] = []
    if enable_web_search:
        wtext, has_w, werr, ev_part = fetch_instant_web_with_evidence(user_input)
        web_err_meta = werr
        if has_w:
            web_append = wtext
            web_ev_doc = ev_part
        elif werr:
            web_err_meta = werr

    sys_base = format_instant_doc_system(
        file_name=fname, body=body, user_input=user_input, web_block=web_append
    )

    messages = prepend_to_first_system(
        [
            SystemMessage(content=sys_base),
            *chat_history,
            HumanMessage(content=user_input),
        ]
    )
    messages = _append_persona_and_style_to_system_messages(
        list(messages),
        response_style,
        persona_prompt,
        system_prompt_extra=system_prompt_extra,
    )

    doc_sources = _serialize_evidence(web_ev_doc) if web_ev_doc else []
    yield _yield_meta("instant_doc", user_input, web_err_meta, sources=doc_sources)
    try:
        async for piece in iter_astream_llm_chunks(llm, messages, user_id, "instant_doc"):
            yield {"type": "chunk", "text": piece}
    except Exception as e:
        yield {"type": "chunk", "text": _friendly_llm_error(e)}
    yield {"type": "done"}


def run_instant_chat_turn(
    *,
    user_input: str,
    chat_history_messages: List[Dict[str, Any]],
    document_text: str,
    document_file_name: str,
    llm: Any,
    response_style: str = "balanced",
    persona_prompt: Optional[str] = None,
    system_prompt_extra: Optional[str] = None,
    user_id: Optional[int] = None,
    context_max_chars: int = 100_000,
    enable_web_search: bool = False,
) -> tuple[str, str, str, List[Dict[str, Any]], Optional[str]]:
    """同步非流式：返回 (answer, mode, retrieval_query, sources, error)；联网时 sources 为网页摘要条目。"""
    from services.chat_turn import _track_llm  # noqa: PLC0415

    doc = (document_text or "").strip()
    fname = (document_file_name or "文档").strip() or "文档"
    chat_history = _api_history_to_messages(chat_history_messages)

    if classify_intent_lightweight(user_input) == "CHAT":
        sys_kw = ["你是谁", "你是什么", "你叫什么", "介绍", "你能做什么", "功能", "怎么使用", "即时"]
        if any(kw in user_input for kw in sys_kw):
            return get_instant_intro(), "instant_chat", "", [], None
        extra = ""
        if persona_prompt and str(persona_prompt).strip():
            extra = "\n\n【角色与风格】" + str(persona_prompt).strip()
        prompt = prepend_to_text_prompt(
            format_instant_chat_short(user_input=user_input, extra=extra)
        )
        try:
            response = llm.invoke(prompt)
            _track_llm(response, llm, "instant_chat", user_id)
            text = response.content if hasattr(response, "content") else str(response)
            return text, "instant_chat", "", [], None
        except Exception as e:
            return "", "error", "", [], _friendly_llm_error(e)

    if not doc:
        if not enable_web_search:
            return (
                "请先在输入框左侧点击加号上传文档，或开启「联网」后提问。",
                "instant_no_doc",
                user_input,
                [],
                None,
            )
        web_text, has_web, web_err, web_ev = fetch_instant_web_with_evidence(user_input)
        if not has_web:
            return (
                (web_err or "联网检索未返回摘要，请检查管理端搜索密钥。"),
                "instant_no_doc",
                user_input,
                [],
                web_err,
            )
        web_sources = _serialize_evidence(web_ev)
        sys_base = format_instant_web_only_system(web_block=web_text, user_input=user_input)
        messages = prepend_to_first_system(
            [
                SystemMessage(content=sys_base),
                *chat_history,
                HumanMessage(content=user_input),
            ]
        )
        messages = _append_persona_and_style_to_system_messages(
            messages,
            response_style,
            persona_prompt,
            system_prompt_extra=system_prompt_extra,
        )
        try:
            response = llm.invoke(messages)
            _track_llm(response, llm, "instant_web", user_id)
            text = response.content if hasattr(response, "content") else str(response)
            return text, "instant_web", user_input, web_sources, web_err
        except Exception as e:
            return "", "error", user_input, [], _friendly_llm_error(e)

    cap = max(4_000, min(int(context_max_chars), 100_000))
    body = doc if len(doc) <= cap else doc[:cap]

    web_append = ""
    web_err_meta: Optional[str] = None
    web_ev_doc: List[Dict[str, Any]] = []
    if enable_web_search:
        wtext, has_w, werr, ev_part = fetch_instant_web_with_evidence(user_input)
        if has_w:
            web_append = wtext
            web_ev_doc = ev_part
        if werr:
            web_err_meta = werr

    sys_base = format_instant_doc_system(
        file_name=fname, body=body, user_input=user_input, web_block=web_append
    )

    messages = prepend_to_first_system(
        [
            SystemMessage(content=sys_base),
            *chat_history,
            HumanMessage(content=user_input),
        ]
    )
    messages = _append_persona_and_style_to_system_messages(
        messages,
        response_style,
        persona_prompt,
        system_prompt_extra=system_prompt_extra,
    )
    doc_sources = _serialize_evidence(web_ev_doc) if web_ev_doc else []
    try:
        response = llm.invoke(messages)
        _track_llm(response, llm, "instant_doc", user_id)
        text = response.content if hasattr(response, "content") else str(response)
        return text, "instant_doc", user_input, doc_sources, web_err_meta
    except Exception as e:
        return "", "error", user_input, [], _friendly_llm_error(e)
