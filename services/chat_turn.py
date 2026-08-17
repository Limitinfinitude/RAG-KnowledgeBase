"""单次对话编排：供 Streamlit 与 FastAPI 共用，不依赖 st。"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from services.query_decompose import decompose_for_retrieval
from services.rag_prompts import get_qa_hybrid_prompt, get_qa_prompt, get_rephrase_prompt
from services.retrieval import retrieve_for_rag, retrieve_for_rag_multi
from services.ui_sink import RetrievalUISink
from utils.intent_classifier import classify_intent_lightweight
from utils.prompt_runtime import (
    format_rag_chat_short,
    format_rag_empty_kb_prompt,
    format_rag_low_score_qa_prompt,
    get_rag_static_assistant_intro,
)
from utils.rag_prompt_hardening import prepend_to_first_system, prepend_to_text_prompt
from utils.token_tracker import track_token_usage

def _retrieve_rag_decomposed(
    *,
    vector_db: Any,
    standalone_q: str,
    llm: Any,
    selected_kb: str,
    retrieval_k: int,
    search_mode: str,
    enable_reranker: bool,
    reranker: Any,
    sink: RetrievalUISink,
) -> Any:
    """单句或多子问：多子问时分别召回再合并，整句重排。"""
    subqs = decompose_for_retrieval(standalone_q, llm)
    if len(subqs) > 1:
        return retrieve_for_rag_multi(
            vector_db=vector_db,
            queries=subqs,
            final_rerank_query=standalone_q,
            selected_kb=selected_kb,
            k=retrieval_k,
            search_mode=search_mode,
            enable_reranker=enable_reranker,
            reranker=reranker,
            sink=sink,
        )
    return retrieve_for_rag(
        vector_db=vector_db,
        query=subqs[0],
        selected_kb=selected_kb,
        k=retrieval_k,
        search_mode=search_mode,
        enable_reranker=enable_reranker,
        reranker=reranker,
        sink=sink,
    )


_brave_diag = logging.getLogger("rag.brave")
logger = logging.getLogger(__name__)


def augment_rag_with_web_search(
    ret: Any,
    standalone_q: str,
    enable_web_search: bool,
) -> tuple[str, List[Dict[str, Any]], bool]:
    """
    按管理端配置的供应商（博查 / Brave / 百度千帆）合并网页摘要。
    返回：(合并后的编号上下文, 合并后的 evidence_sources 原始列表, 是否包含网页摘要)
    """
    from utils.bocha_search import merge_bocha_web_into_evidence
    from utils.brave_search import merge_brave_web_into_evidence
    from utils.qianfan_web_search import merge_qianfan_web_into_evidence
    from utils.web_system_settings import (
        get_bocha_api_key_resolved,
        get_brave_api_key_resolved,
        get_qianfan_api_key_resolved,
        get_web_search_provider,
    )

    evidence_raw: List[Dict[str, Any]] = list(ret.evidence_sources or [])
    ctx = ret.numbered_context or ""
    if not enable_web_search:
        return ctx, evidence_raw, False

    provider = get_web_search_provider()
    _brave_diag.info(
        "[联网] 已开启 | 供应商=%s | 检索用语: %s",
        provider,
        (standalone_q or "")[:120],
    )

    if provider == "bocha":
        key = get_bocha_api_key_resolved()
        if not key:
            _brave_diag.warning(
                "[联网/博查] 未配置密钥（管理端或环境变量 BOCHA_API_KEY / config.BOCHA_API_KEY）"
            )
            return ctx, evidence_raw, False
        _brave_diag.info("[联网/博查] 已解析 API Key（长度 %d），请求中…", len(key))
        ctx2, evidence_raw2, has_web, err = merge_bocha_web_into_evidence(
            standalone_q, key, ctx, evidence_raw
        )
        log_tag = "bocha_web_search"
    elif provider == "baidu":
        key = get_qianfan_api_key_resolved()
        if not key:
            _brave_diag.warning(
                "[联网/百度千帆] 未配置密钥（管理端 qianfan_api_key 或 QIANFAN_API_KEY / config）"
            )
            return ctx, evidence_raw, False
        _brave_diag.info("[联网/百度千帆] 已解析 API Key（长度 %d），请求中…", len(key))
        ctx2, evidence_raw2, has_web, err = merge_qianfan_web_into_evidence(
            standalone_q, key, ctx, evidence_raw
        )
        log_tag = "qianfan_web_search"
    else:
        key = get_brave_api_key_resolved()
        if not key:
            _brave_diag.warning(
                "[联网/Brave] 未配置密钥（管理端 brave_api_key_server 或环境变量 / config）"
            )
            return ctx, evidence_raw, False
        _brave_diag.info("[联网/Brave] 已解析 API Key（长度 %d），请求中…", len(key))
        ctx2, evidence_raw2, has_web, err = merge_brave_web_into_evidence(
            standalone_q, key, ctx, evidence_raw
        )
        log_tag = "brave_web_search"

    if err:
        try:
            from utils.logger import log_error

            log_error(log_tag, err, {"q": (standalone_q or "")[:120], "provider": provider})
        except Exception:
            pass
        _brave_diag.warning("[联网] 合并失败 (%s): %s", provider, err)
    elif has_web:
        _brave_diag.info(
            "[联网] 已并入上下文 (%s)，网页摘要条数=%d",
            provider,
            len(evidence_raw2) - len(evidence_raw),
        )
    else:
        _brave_diag.warning("[联网] 未并入任何网页摘要（%s 无结果）", provider)
    return ctx2, evidence_raw2, has_web


# 兼容旧名
def augment_rag_with_brave_web(
    ret: Any,
    standalone_q: str,
    enable_web_search: bool,
    brave_api_key: Optional[str] = None,
) -> tuple[str, List[Dict[str, Any]], bool]:
    """已弃用：请使用 augment_rag_with_web_search；brave_api_key 参数已忽略。"""
    return augment_rag_with_web_search(ret, standalone_q, enable_web_search)


def _retrieval_max_score(ret: Any) -> float:
    ls = getattr(ret, "last_search_results", None) or []
    if not ls:
        return 0.0
    return max((s for _, s in ls[:5]), default=0.0)


def friendly_llm_error_text(msg: str) -> str:
    """将上游 LLM/HTTP 异常文案转为用户可读中文（含 DeepSeek 401、乱码式英文等）。"""
    low = msg.lower()
    auth_hit = "认证" in msg or any(
        x in low
        for x in (
            "401",
            "403",
            "unauthorized",
            "invalid api",
            "api key",
            "authentication",
            "鉴权",
            "governor",
            "credentials",
            "incorrect api",
            "invalid key",
            "access denied",
        )
    )
    if auth_hit:
        return (
            "大模型接口鉴权失败（与您在本站的账号登录无关）。"
            "请管理员在管理端「模型配置」或 MySQL app_settings 中核对："
            "API Key 是否有效、Base URL 是否为 https://api.deepseek.com（或服务商要求地址）、模型名是否与账户一致。"
        )
    if "429" in low or "rate limit" in low or "too many requests" in low:
        return "大模型接口请求过于频繁或额度不足，请稍后再试。"
    if "timeout" in low or "timed out" in low:
        return "大模型请求超时，请检查网络或稍后重试。"
    if len(msg) > 280:
        return "大模型调用失败，请检查网络与后台配置。"
    return f"大模型调用失败：{msg}"


def _friendly_llm_error(exc: Exception) -> str:
    return friendly_llm_error_text(str(exc))


def _api_history_to_messages(messages: List[Dict[str, Any]]) -> List[Any]:
    out: List[Any] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
    return out


def _serialize_evidence(items: List[Dict]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    for item in items:
        meta = item.get("metadata") or {}
        safe_meta = {str(k): str(v) for k, v in meta.items()}
        serialized.append(
            {
                "index": item.get("index"),
                "file": item.get("file"),
                "content": item.get("content"),
                "score": float(item["score"]) if item.get("score") is not None else None,
                "chunk_level": item.get("chunk_level"),
                "metadata": safe_meta,
            }
        )
    return serialized


_CANNOT_ANSWER_MARKERS = (
    "根据现有资料无法回答",
    "知识库中暂无",
    "无法从知识库",
    "资料中没有",
    "资料未覆盖",
    "没有找到相关",
    "未能找到相关",
    "暂无法根据",
)


def _citation_indices_from_answer(answer: str) -> List[int]:
    """从回答中提取 [来源N] / 【来源N】 等标号，按出现顺序去重。"""
    if not answer:
        return []
    seen: set[int] = set()
    out: List[int] = []
    for pattern in (r"\[来源\s*(\d+)\s*\]", r"【来源\s*(\d+)\s*】"):
        for m in re.finditer(pattern, answer):
            idx = int(m.group(1))
            if 1 <= idx <= 64 and idx not in seen:
                seen.add(idx)
                out.append(idx)
    return out


def _chars_for_overlap(s: str) -> Counter:
    c: Counter = Counter()
    for ch in s:
        if ch.isspace():
            continue
        if "\u4e00" <= ch <= "\u9fff" or ch.isalnum():
            c[ch] += 1
    return c


def _cjk_bigrams(s: str) -> Counter:
    """中文双字组，用于区分「泛泛共有字」与真正同段复述（如 灭法/剃削/金箍）。"""
    chars = [c for c in s if "\u4e00" <= c <= "\u9fff"]
    c: Counter = Counter()
    for i in range(len(chars) - 1):
        c[chars[i] + chars[i + 1]] += 1
    return c


def _cosine_counter(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    inter = sum((a & b).values())
    return inter / (sum(a.values()) ** 0.5 * sum(b.values()) ** 0.5 + 1e-9)


def _answer_chunk_alignment(answer: str, chunk: str) -> float:
    """估计回答与片段是否同根：单字余弦 + 双字余弦，弱化「三国/西游」共用常见字造成的假相关。"""
    ca = _chars_for_overlap(answer)
    cb = _chars_for_overlap(chunk or "")
    char_sim = _cosine_counter(ca, cb)
    ba = _cjk_bigrams(answer)
    bb = _cjk_bigrams(chunk or "")
    bi_sim = _cosine_counter(ba, bb)
    if not ba or not bb:
        return char_sim
    return 0.42 * char_sim + 0.58 * bi_sim


def filter_sources_for_traceability(
    answer: str,
    serialized_sources: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    溯源与回答对齐：
    - 有 [来源N] 时先取对应片段；若其整体与回答对齐度明显低于其它检索块（常见：模型一律写来源1），
      则改按「回答–片段」对齐度展示，避免三国演义排前而西游真据在后的错配。
    - 无标注时按对齐度筛选；无法回答时不展示误导性溯源。
    """
    if not serialized_sources:
        return []
    ans = (answer or "").strip()
    by_idx: Dict[int, Dict[str, Any]] = {}
    for s in serialized_sources:
        idx = s.get("index")
        try:
            idx_i = int(idx) if idx is not None else 0
        except (TypeError, ValueError):
            idx_i = 0
        if idx_i > 0:
            by_idx[idx_i] = s

    scored_all = [
        (_answer_chunk_alignment(ans, str(s.get("content") or "")), s)
        for s in serialized_sources
    ]
    scored_all.sort(key=lambda x: -x[0])
    best_align = scored_all[0][0] if scored_all else 0.0

    cited = _citation_indices_from_answer(ans)
    if cited:
        cited_items = [by_idx[i] for i in cited if i in by_idx]
        if cited_items:
            max_cited_align = max(
                _answer_chunk_alignment(ans, str(s.get("content") or "")) for s in cited_items
            )
            # 标注块与回答脱节，但检索列表里存在明显更吻合的块 → 不按错误标号展示
            if best_align >= 0.048 and best_align > max_cited_align + 0.018:
                floor = max(0.038, best_align * 0.52)
                out = [s for al, s in scored_all[:6] if al >= floor]
                return out[:3] if len(out) > 3 else out
            return cited_items

    if any(m in ans for m in _CANNOT_ANSWER_MARKERS):
        return []
    out = [s for align, s in scored_all[:3] if align >= 0.065]
    return out[:2] if len(out) > 2 else out


@dataclass
class ChatTurnResult:
    answer: str
    mode: str
    retrieval_query: str = ""
    sources: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


_RESPONSE_STYLE_HINT: Dict[str, str] = {
    "precise": "\n\n【本轮回答偏好】请简短扼要，优先结论与要点，避免重复铺垫。",
    "balanced": "\n\n【本轮回答偏好】在清晰与完整之间保持平衡。",
    "verbose": "\n\n【本轮回答偏好】在忠于文档的前提下可适当展开说明，便于理解。",
}


def _llm_model_label(llm: Any) -> str:
    for attr in ("model_name", "model"):
        v = getattr(llm, attr, None)
        if v:
            return str(v)
    return "unknown"


def _track_llm(response: Any, llm: Any, call_type: str, user_id: Optional[int]) -> None:
    track_token_usage(
        response,
        model=_llm_model_label(llm),
        call_type=call_type,
        user_id=user_id,
    )


def _append_persona_and_style_to_system_messages(
    messages: List[BaseMessage],
    style_key: str,
    persona_prompt: Optional[str],
    system_prompt_extra: Optional[str] = None,
) -> List[BaseMessage]:
    key = (style_key or "balanced").strip().lower()
    style_suffix = _RESPONSE_STYLE_HINT.get(key, _RESPONSE_STYLE_HINT["balanced"])
    persona_block = ""
    if persona_prompt and str(persona_prompt).strip():
        persona_block = (
            "\n\n【助手角色与风格（用户个性化设定）】\n" + str(persona_prompt).strip()
        )
    extra_block = ""
    if system_prompt_extra and str(system_prompt_extra).strip():
        extra_block = "\n\n【系统补充说明（管理员配置）】\n" + str(system_prompt_extra).strip()
    out: List[BaseMessage] = []
    for m in messages:
        if isinstance(m, SystemMessage):
            content = (m.content or "") + extra_block + persona_block + style_suffix
            out.append(SystemMessage(content=content))
        else:
            out.append(m)
    return out


def _delta_from_chunk(chunk: Any) -> str:
    c = getattr(chunk, "content", None)
    if c is None:
        return ""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: List[str] = []
        for p in c:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text", "")))
            elif isinstance(p, str):
                parts.append(p)
        return "".join(parts)
    return str(c) if c else ""


def _stream_llm_chunks(
    llm: Any,
    input_data: Union[str, List[BaseMessage]],
    user_id: Optional[int],
    call_type: str,
) -> Iterator[str]:
    """逐段产出模型文本；结束时尽量用最后一个 chunk 记 token。"""
    last_chunk: Any = None
    for chunk in llm.stream(input_data):
        last_chunk = chunk
        piece = _delta_from_chunk(chunk)
        if piece:
            yield piece
    if last_chunk is not None:
        try:
            track_token_usage(
                last_chunk,
                model=_llm_model_label(llm),
                call_type=call_type,
                user_id=user_id,
            )
        except Exception:
            pass


def _rephrase_standalone_sync(
    llm: Any,
    user_input: str,
    chat_history: List[BaseMessage],
    user_id: Optional[int],
) -> str:
    try:
        messages = prepend_to_first_system(
            get_rephrase_prompt().format_messages(input=user_input, chat_history=chat_history)
        )
        response = llm.invoke(messages)
        _track_llm(response, llm, "rephrase", user_id)
        response_text = response.content if hasattr(response, "content") else str(response)
        lines = response_text.strip().split("\n", 1)
        return lines[1].strip() if len(lines) > 1 else user_input
    except Exception:
        return user_input


async def iter_astream_llm_chunks(
    llm: Any,
    input_data: Union[str, List[BaseMessage]],
    user_id: Optional[int],
    call_type: str,
) -> AsyncIterator[str]:
    """异步流：与上游 SSE 对齐，尽快把 delta 交给 ASGI，减少整段缓冲。"""
    last_chunk: Any = None
    async for chunk in llm.astream(input_data):
        last_chunk = chunk
        piece = _delta_from_chunk(chunk)
        if piece:
            yield piece
        await asyncio.sleep(0)
    if last_chunk is not None:
        try:
            track_token_usage(
                last_chunk,
                model=_llm_model_label(llm),
                call_type=call_type,
                user_id=user_id,
            )
        except Exception:
            pass


async def run_chat_turn_astream(
    *,
    user_input: str,
    chat_history_messages: List[Dict[str, Any]],
    vector_db: Any,
    llm: Any,
    selected_kb: str = "全部知识库",
    search_mode: str = "vector",
    enable_reranker: bool = False,
    reranker: Any = None,
    retrieval_k: int = 10,
    response_style: str = "balanced",
    persona_prompt: Optional[str] = None,
    system_prompt_extra: Optional[str] = None,
    user_id: Optional[int] = None,
    enable_web_search: bool = False,
) -> AsyncIterator[Dict[str, Any]]:
    """供 FastAPI StreamingResponse 使用：meta → chunk* → done。"""
    chat_history = _api_history_to_messages(chat_history_messages)

    if classify_intent_lightweight(user_input) == "CHAT":
        system_keywords = ["你是谁", "你是什么", "你叫什么", "介绍", "你能做什么", "功能", "怎么使用"]
        is_system_question = any(kw in user_input for kw in system_keywords)
        if is_system_question:
            yield _yield_meta("chat", "", [], None)
            yield {"type": "chunk", "text": get_rag_static_assistant_intro()}
            yield {"type": "done"}
            return
        extra = ""
        if persona_prompt and str(persona_prompt).strip():
            extra = "\n\n【角色与风格】" + str(persona_prompt).strip()
        prompt = prepend_to_text_prompt(
            format_rag_chat_short(user_input=user_input, extra=extra)
        )
        yield _yield_meta("chat", "", [], None)
        try:
            async for piece in iter_astream_llm_chunks(llm, prompt, user_id, "chat"):
                yield {"type": "chunk", "text": piece}
        except Exception as e:
            yield {"type": "chunk", "text": _friendly_llm_error(e)}
        yield {"type": "done"}
        return

    standalone_q = user_input
    has_history = len(chat_history) > 0
    # 指代词用完整词而非单字："其"会误命中"其中/其他"等
    pronouns = ["他", "她", "它", "这个", "那个", "这些", "那些", "其他", "其它", "其中", "其实", "其余", "该文", "该书", "该方法"]
    has_pronoun = any(p in user_input for p in pronouns)
    if has_history and has_pronoun:
        standalone_q = await asyncio.to_thread(
            _rephrase_standalone_sync, llm, user_input, chat_history, user_id
        )

    try:
        ret = await asyncio.to_thread(
            lambda: _retrieve_rag_decomposed(
                vector_db=vector_db,
                standalone_q=standalone_q,
                llm=llm,
                selected_kb=selected_kb,
                retrieval_k=retrieval_k,
                search_mode=search_mode,
                enable_reranker=enable_reranker,
                reranker=reranker,
                sink=RetrievalUISink.noop(),
            )
        )
    except Exception as e:
        yield _yield_meta("error", standalone_q, [], str(e))
        yield {"type": "chunk", "text": f"检索失败：{e}"}
        yield {"type": "done"}
        return

    context_text, evidence_raw, has_web = await asyncio.to_thread(
        augment_rag_with_web_search,
        ret,
        standalone_q,
        enable_web_search,
    )
    sources = _serialize_evidence(evidence_raw)

    if not (context_text or "").strip():
        yield _yield_meta("rag_empty", standalone_q, sources, None)
        answer_buf: List[str] = []
        try:
            pextra = ""
            if persona_prompt and str(persona_prompt).strip():
                pextra = "\n同时体现以下用户设定的助手风格：" + str(persona_prompt).strip() + "\n"
            empty_prompt = prepend_to_text_prompt(
                format_rag_empty_kb_prompt(user_input=user_input, pextra=pextra)
            )
            async for piece in iter_astream_llm_chunks(llm, empty_prompt, user_id, "rag_empty"):
                answer_buf.append(piece)
                yield {"type": "chunk", "text": piece}
        except Exception as e:
            yield {"type": "chunk", "text": _friendly_llm_error(e)}
        yield _yield_meta(
            "rag_empty",
            standalone_q,
            filter_sources_for_traceability("".join(answer_buf), sources),
            None,
        )
        yield {"type": "done"}
        return

    max_score = _retrieval_max_score(ret)
    if has_web:
        max_score = max(max_score, 0.35)

    web_low = ""
    if has_web:
        web_low = (
            "\n- 资料中含「联网检索摘要」时，可与知识库片段一并使用，引用写 [来源n]；"
            "摘要非全文，勿编造其中未出现的细节。\n"
        )

    if max_score < 0.3:
        yield _yield_meta("rag_low_score", standalone_q, sources, None)
        answer_buf_ls: List[str] = []
        try:
            pextra = ""
            if persona_prompt and str(persona_prompt).strip():
                pextra = (
                    "\n【用户设定的助手风格】\n"
                    + str(persona_prompt).strip()
                    + "\n（在忠于文档的前提下体现上述风格。）\n"
                )
            low_prompt = prepend_to_text_prompt(
                format_rag_low_score_qa_prompt(
                    pextra=pextra,
                    context_text=context_text,
                    user_input=user_input,
                    web_low=web_low,
                )
            )
            async for piece in iter_astream_llm_chunks(llm, low_prompt, user_id, "rag_low_score"):
                answer_buf_ls.append(piece)
                yield {"type": "chunk", "text": piece}
        except Exception as e:
            yield {"type": "chunk", "text": _friendly_llm_error(e)}
        yield _yield_meta(
            "rag_low_score",
            standalone_q,
            filter_sources_for_traceability("".join(answer_buf_ls), sources),
            None,
        )
        yield {"type": "done"}
        return

    yield _yield_meta("rag", standalone_q, sources, None)
    answer_buf_main: List[str] = []
    try:
        tpl = get_qa_hybrid_prompt() if has_web else get_qa_prompt()
        messages = tpl.format_messages(
            context=context_text, chat_history=chat_history, input=standalone_q
        )
        messages = prepend_to_first_system(messages)
        messages = _append_persona_and_style_to_system_messages(
            messages, response_style, persona_prompt, system_prompt_extra=system_prompt_extra
        )
        async for piece in iter_astream_llm_chunks(llm, messages, user_id, "qa"):
            answer_buf_main.append(piece)
            yield {"type": "chunk", "text": piece}
    except Exception as e:
        yield {"type": "chunk", "text": _friendly_llm_error(e)}
    yield _yield_meta(
        "rag",
        standalone_q,
        filter_sources_for_traceability("".join(answer_buf_main), sources),
        None,
    )
    yield {"type": "done"}


def _yield_meta(
    mode: str,
    retrieval_query: str,
    sources: List[Dict[str, Any]],
    error: Optional[str],
) -> Dict[str, Any]:
    return {
        "type": "meta",
        "mode": mode,
        "retrieval_query": retrieval_query or "",
        "sources": sources,
        "error": error,
    }


def run_chat_turn(
    *,
    user_input: str,
    chat_history_messages: List[Dict[str, Any]],
    vector_db: Any,
    llm: Any,
    selected_kb: str = "全部知识库",
    search_mode: str = "vector",
    enable_reranker: bool = False,
    reranker: Any = None,
    retrieval_k: int = 10,
    response_style: str = "balanced",
    persona_prompt: Optional[str] = None,
    system_prompt_extra: Optional[str] = None,
    user_id: Optional[int] = None,
    enable_web_search: bool = False,
) -> ChatTurnResult:
    """
    与 page_one 主流程对齐的精简版：闲聊 / RAG 检索 + 问答。
    llm 由调用方用 services.llm_factory.build_chat_llm 构造，保证与页面一致。
    """
    chat_history = _api_history_to_messages(chat_history_messages)

    if classify_intent_lightweight(user_input) == "CHAT":
        system_keywords = ["你是谁", "你是什么", "你叫什么", "介绍", "你能做什么", "功能", "怎么使用"]
        is_system_question = any(kw in user_input for kw in system_keywords)
        if is_system_question:
            return ChatTurnResult(answer=get_rag_static_assistant_intro(), mode="chat")
        extra = ""
        if persona_prompt and str(persona_prompt).strip():
            extra = "\n\n【角色与风格】" + str(persona_prompt).strip()
        prompt = prepend_to_text_prompt(
            format_rag_chat_short(user_input=user_input, extra=extra)
        )
        try:
            response = llm.invoke(prompt)
            _track_llm(response, llm, "chat", user_id)
            text = response.content if hasattr(response, "content") else str(response)
            return ChatTurnResult(answer=text, mode="chat")
        except Exception as e:
            return ChatTurnResult(answer="", mode="error", error=_friendly_llm_error(e))

    standalone_q = user_input
    has_history = len(chat_history) > 0
    # 指代词用完整词而非单字："其"会误命中"其中/其他"等
    pronouns = ["他", "她", "它", "这个", "那个", "这些", "那些", "其他", "其它", "其中", "其实", "其余", "该文", "该书", "该方法"]
    has_pronoun = any(p in user_input for p in pronouns)
    if has_history and has_pronoun:
        try:
            messages = prepend_to_first_system(
                get_rephrase_prompt().format_messages(input=user_input, chat_history=chat_history)
            )
            response = llm.invoke(messages)
            _track_llm(response, llm, "rephrase", user_id)
            response_text = response.content if hasattr(response, "content") else str(response)
            lines = response_text.strip().split("\n", 1)
            standalone_q = lines[1].strip() if len(lines) > 1 else user_input
        except Exception as e:
            logger.warning("指代改写失败，使用原始输入: %s", e)
            standalone_q = user_input

    sink = RetrievalUISink.noop()
    try:
        ret = _retrieve_rag_decomposed(
            vector_db=vector_db,
            standalone_q=standalone_q,
            llm=llm,
            selected_kb=selected_kb,
            retrieval_k=retrieval_k,
            search_mode=search_mode,
            enable_reranker=enable_reranker,
            reranker=reranker,
            sink=sink,
        )
    except Exception as e:
        return ChatTurnResult(answer="", mode="error", retrieval_query=standalone_q, error=str(e))

    context_text, evidence_raw, has_web = augment_rag_with_web_search(
        ret, standalone_q, enable_web_search
    )
    sources = _serialize_evidence(evidence_raw)

    if not (context_text or "").strip():
        try:
            pextra = ""
            if persona_prompt and str(persona_prompt).strip():
                pextra = "\n同时体现以下用户设定的助手风格：" + str(persona_prompt).strip() + "\n"
            response = llm.invoke(
                prepend_to_text_prompt(
                    format_rag_empty_kb_prompt(user_input=user_input, pextra=pextra)
                )
            )
            _track_llm(response, llm, "rag_empty", user_id)
            text = response.content if hasattr(response, "content") else str(response)
            return ChatTurnResult(
                answer=text,
                mode="rag_empty",
                retrieval_query=standalone_q,
                sources=filter_sources_for_traceability(text, sources),
            )
        except Exception as e:
            return ChatTurnResult(
                answer="",
                mode="error",
                retrieval_query=standalone_q,
                sources=sources,
                error=_friendly_llm_error(e),
            )

    max_score = _retrieval_max_score(ret)
    if has_web:
        max_score = max(max_score, 0.35)

    web_low = ""
    if has_web:
        web_low = (
            "\n- 资料中含「联网检索摘要」时，可与知识库片段一并使用，引用写 [来源n]；"
            "摘要非全文，勿编造其中未出现的细节。\n"
        )

    if max_score < 0.3:
        try:
            pextra = ""
            if persona_prompt and str(persona_prompt).strip():
                pextra = (
                    "\n【用户设定的助手风格】\n"
                    + str(persona_prompt).strip()
                    + "\n（在忠于文档的前提下体现上述风格。）\n"
                )
            response = llm.invoke(
                prepend_to_text_prompt(
                    format_rag_low_score_qa_prompt(
                        pextra=pextra,
                        context_text=context_text,
                        user_input=user_input,
                        web_low=web_low,
                    )
                )
            )
            _track_llm(response, llm, "rag_low_score", user_id)
            text = response.content if hasattr(response, "content") else str(response)
            return ChatTurnResult(
                answer=text,
                mode="rag_low_score",
                retrieval_query=standalone_q,
                sources=filter_sources_for_traceability(text, sources),
            )
        except Exception as e:
            return ChatTurnResult(
                answer="",
                mode="error",
                retrieval_query=standalone_q,
                sources=sources,
                error=_friendly_llm_error(e),
            )

    try:
        tpl = get_qa_hybrid_prompt() if has_web else get_qa_prompt()
        messages = tpl.format_messages(
            context=context_text, chat_history=chat_history, input=standalone_q
        )
        messages = prepend_to_first_system(messages)
        messages = _append_persona_and_style_to_system_messages(
            messages, response_style, persona_prompt, system_prompt_extra=system_prompt_extra
        )
        response = llm.invoke(messages)
        _track_llm(response, llm, "qa", user_id)
        text = response.content if hasattr(response, "content") else str(response)
        return ChatTurnResult(
            answer=text,
            mode="rag",
            retrieval_query=standalone_q,
            sources=filter_sources_for_traceability(text, sources),
        )
    except Exception as e:
        return ChatTurnResult(
            answer="",
            mode="error",
            retrieval_query=standalone_q,
            sources=sources,
            error=_friendly_llm_error(e),
        )


def run_chat_turn_stream(
    *,
    user_input: str,
    chat_history_messages: List[Dict[str, Any]],
    vector_db: Any,
    llm: Any,
    selected_kb: str = "全部知识库",
    search_mode: str = "vector",
    enable_reranker: bool = False,
    reranker: Any = None,
    retrieval_k: int = 10,
    response_style: str = "balanced",
    persona_prompt: Optional[str] = None,
    system_prompt_extra: Optional[str] = None,
    user_id: Optional[int] = None,
    enable_web_search: bool = False,
) -> Iterator[Dict[str, Any]]:
    """与 run_chat_turn 同逻辑，最终以 NDJSON 事件流式输出正文（type: meta / chunk / done）。"""
    chat_history = _api_history_to_messages(chat_history_messages)

    if classify_intent_lightweight(user_input) == "CHAT":
        system_keywords = ["你是谁", "你是什么", "你叫什么", "介绍", "你能做什么", "功能", "怎么使用"]
        is_system_question = any(kw in user_input for kw in system_keywords)
        if is_system_question:
            yield _yield_meta("chat", "", [], None)
            yield {"type": "chunk", "text": get_rag_static_assistant_intro()}
            yield {"type": "done"}
            return
        extra = ""
        if persona_prompt and str(persona_prompt).strip():
            extra = "\n\n【角色与风格】" + str(persona_prompt).strip()
        prompt = prepend_to_text_prompt(
            format_rag_chat_short(user_input=user_input, extra=extra)
        )
        yield _yield_meta("chat", "", [], None)
        try:
            for piece in _stream_llm_chunks(llm, prompt, user_id, "chat"):
                yield {"type": "chunk", "text": piece}
        except Exception as e:
            yield {"type": "chunk", "text": _friendly_llm_error(e)}
        yield {"type": "done"}
        return

    standalone_q = user_input
    has_history = len(chat_history) > 0
    # 指代词用完整词而非单字："其"会误命中"其中/其他"等
    pronouns = ["他", "她", "它", "这个", "那个", "这些", "那些", "其他", "其它", "其中", "其实", "其余", "该文", "该书", "该方法"]
    has_pronoun = any(p in user_input for p in pronouns)
    if has_history and has_pronoun:
        try:
            messages = prepend_to_first_system(
                get_rephrase_prompt().format_messages(input=user_input, chat_history=chat_history)
            )
            response = llm.invoke(messages)
            _track_llm(response, llm, "rephrase", user_id)
            response_text = response.content if hasattr(response, "content") else str(response)
            lines = response_text.strip().split("\n", 1)
            standalone_q = lines[1].strip() if len(lines) > 1 else user_input
        except Exception as e:
            logger.warning("指代改写失败，使用原始输入: %s", e)
            standalone_q = user_input

    sink = RetrievalUISink.noop()
    try:
        ret = _retrieve_rag_decomposed(
            vector_db=vector_db,
            standalone_q=standalone_q,
            llm=llm,
            selected_kb=selected_kb,
            retrieval_k=retrieval_k,
            search_mode=search_mode,
            enable_reranker=enable_reranker,
            reranker=reranker,
            sink=sink,
        )
    except Exception as e:
        yield _yield_meta("error", standalone_q, [], str(e))
        yield {"type": "chunk", "text": f"检索失败：{e}"}
        yield {"type": "done"}
        return

    context_text, evidence_raw, has_web = augment_rag_with_web_search(
        ret, standalone_q, enable_web_search
    )
    sources = _serialize_evidence(evidence_raw)

    if not (context_text or "").strip():
        yield _yield_meta("rag_empty", standalone_q, sources, None)
        answer_buf_sync: List[str] = []
        try:
            pextra = ""
            if persona_prompt and str(persona_prompt).strip():
                pextra = "\n同时体现以下用户设定的助手风格：" + str(persona_prompt).strip() + "\n"
            empty_prompt = prepend_to_text_prompt(
                format_rag_empty_kb_prompt(user_input=user_input, pextra=pextra)
            )
            for piece in _stream_llm_chunks(llm, empty_prompt, user_id, "rag_empty"):
                answer_buf_sync.append(piece)
                yield {"type": "chunk", "text": piece}
        except Exception as e:
            yield {"type": "chunk", "text": _friendly_llm_error(e)}
        yield _yield_meta(
            "rag_empty",
            standalone_q,
            filter_sources_for_traceability("".join(answer_buf_sync), sources),
            None,
        )
        yield {"type": "done"}
        return

    max_score = _retrieval_max_score(ret)
    if has_web:
        max_score = max(max_score, 0.35)

    web_low = ""
    if has_web:
        web_low = (
            "\n- 资料中含「联网检索摘要」时，可与知识库片段一并使用，引用写 [来源n]；"
            "摘要非全文，勿编造其中未出现的细节。\n"
        )

    if max_score < 0.3:
        yield _yield_meta("rag_low_score", standalone_q, sources, None)
        answer_buf_lss: List[str] = []
        try:
            pextra = ""
            if persona_prompt and str(persona_prompt).strip():
                pextra = (
                    "\n【用户设定的助手风格】\n"
                    + str(persona_prompt).strip()
                    + "\n（在忠于文档的前提下体现上述风格。）\n"
                )
            low_prompt = prepend_to_text_prompt(
                format_rag_low_score_qa_prompt(
                    pextra=pextra,
                    context_text=context_text,
                    user_input=user_input,
                    web_low=web_low,
                )
            )
            for piece in _stream_llm_chunks(llm, low_prompt, user_id, "rag_low_score"):
                answer_buf_lss.append(piece)
                yield {"type": "chunk", "text": piece}
        except Exception as e:
            yield {"type": "chunk", "text": _friendly_llm_error(e)}
        yield _yield_meta(
            "rag_low_score",
            standalone_q,
            filter_sources_for_traceability("".join(answer_buf_lss), sources),
            None,
        )
        yield {"type": "done"}
        return

    yield _yield_meta("rag", standalone_q, sources, None)
    answer_buf_mains: List[str] = []
    try:
        tpl = get_qa_hybrid_prompt() if has_web else get_qa_prompt()
        messages = tpl.format_messages(
            context=context_text, chat_history=chat_history, input=standalone_q
        )
        messages = prepend_to_first_system(messages)
        messages = _append_persona_and_style_to_system_messages(
            messages, response_style, persona_prompt, system_prompt_extra=system_prompt_extra
        )
        for piece in _stream_llm_chunks(llm, messages, user_id, "qa"):
            answer_buf_mains.append(piece)
            yield {"type": "chunk", "text": piece}
    except Exception as e:
        yield {"type": "chunk", "text": _friendly_llm_error(e)}
    yield _yield_meta(
        "rag",
        standalone_q,
        filter_sources_for_traceability("".join(answer_buf_mains), sources),
        None,
    )
    yield {"type": "done"}
