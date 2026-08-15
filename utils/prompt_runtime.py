"""从 MySQL prompt_templates 取正文；无行/停用则回退 prompt_template_defaults。占位符用简单替换，避免 context 中含花括号时 .format 报错。"""
from __future__ import annotations

from typing import Dict

from utils.prompt_template_defaults import (
    FALLBACK_ANTI_INJECTION_PREFIX,
    FALLBACK_CONVERSATION_TITLE_SYSTEM,
    FALLBACK_INSTANT_CHAT_SHORT,
    FALLBACK_INSTANT_DOC_SYSTEM,
    FALLBACK_INSTANT_INTRO,
    FALLBACK_INSTANT_WEB_ONLY_SYSTEM,
    FALLBACK_QUERY_CLASSIFIER_SYSTEM,
    FALLBACK_QUERY_DECOMPOSE_SYSTEM,
    FALLBACK_RAG_CHAT_SHORT,
    FALLBACK_RAG_EMPTY_KB_REPLY,
    FALLBACK_RAG_LOW_SCORE_QA,
    FALLBACK_RAG_STATIC_ASSISTANT_INTRO,
)
from utils.prompt_template_store import get_builtin_prompt_body_cached


def _body_or_fallback(slug: str, fallback: str) -> str:
    raw = get_builtin_prompt_body_cached(slug)
    if raw is None:
        return fallback
    t = (raw or "").strip()
    return t if t else fallback


def _apply_fields(tpl: str, mapping: Dict[str, str]) -> str:
    out = tpl
    for k, v in mapping.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def get_anti_injection_prefix() -> str:
    return _body_or_fallback("anti_injection_prefix", FALLBACK_ANTI_INJECTION_PREFIX)


def get_rag_static_assistant_intro() -> str:
    return _body_or_fallback("rag_static_assistant_intro", FALLBACK_RAG_STATIC_ASSISTANT_INTRO)


def format_rag_empty_kb_prompt(*, user_input: str, pextra: str = "") -> str:
    tpl = _body_or_fallback("rag_empty_kb_reply", FALLBACK_RAG_EMPTY_KB_REPLY)
    return _apply_fields(tpl, {"user_input": user_input, "pextra": pextra or ""})


def format_rag_chat_short(*, user_input: str, extra: str = "") -> str:
    tpl = _body_or_fallback("rag_chat_short", FALLBACK_RAG_CHAT_SHORT)
    return _apply_fields(tpl, {"user_input": user_input, "extra": extra or ""})


def format_rag_low_score_qa_prompt(
    *, pextra: str, context_text: str, user_input: str, web_low: str
) -> str:
    tpl = _body_or_fallback("rag_low_score_qa", FALLBACK_RAG_LOW_SCORE_QA)
    return _apply_fields(
        tpl,
        {
            "pextra": pextra or "",
            "context_text": context_text,
            "user_input": user_input,
            "web_low": web_low or "",
        },
    )


def get_instant_intro() -> str:
    return _body_or_fallback("instant_intro", FALLBACK_INSTANT_INTRO)


def format_instant_chat_short(*, user_input: str, extra: str = "") -> str:
    tpl = _body_or_fallback("instant_chat_short", FALLBACK_INSTANT_CHAT_SHORT)
    return _apply_fields(tpl, {"user_input": user_input, "extra": extra or ""})


def format_instant_doc_system(
    *, file_name: str, body: str, user_input: str, web_block: str = ""
) -> str:
    web = (web_block or "").strip()
    web_part = ("\n\n" + web) if web else ""
    tpl = _body_or_fallback("instant_doc_system", FALLBACK_INSTANT_DOC_SYSTEM)
    return _apply_fields(
        tpl,
        {
            "file_name": file_name,
            "body": body,
            "web_part": web_part,
            "user_input": user_input,
        },
    )


def format_instant_web_only_system(*, web_block: str, user_input: str) -> str:
    tpl = _body_or_fallback("instant_web_only_system", FALLBACK_INSTANT_WEB_ONLY_SYSTEM)
    w = (web_block or "").strip()
    return _apply_fields(tpl, {"web_block": w, "user_input": user_input})


def get_conversation_title_system() -> str:
    return _body_or_fallback("conversation_title_system", FALLBACK_CONVERSATION_TITLE_SYSTEM)


def get_query_decompose_system() -> str:
    return _body_or_fallback("query_decompose_system", FALLBACK_QUERY_DECOMPOSE_SYSTEM)


def get_query_classifier_system() -> str:
    return _body_or_fallback("query_classifier_system", FALLBACK_QUERY_CLASSIFIER_SYSTEM)
