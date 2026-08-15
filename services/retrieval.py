from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from utils.metadata_manager import get_all_documents, get_documents_by_category
from utils.reranker import rerank_documents
from services.ui_sink import RetrievalUISink
from config import (
    SIMILARITY_THRESHOLD,
    ABSOLUTE_MIN_SCORE,
    MAX_CONTEXT_LENGTH,
    CONTEXT_TOP_K,
    LOW_QUALITY_FALLBACK_K,
)


@dataclass
class RetrievalResult:
    scored_docs: List[Tuple[Any, float]] = field(default_factory=list)
    numbered_context: str = ""
    evidence_sources: List[Dict] = field(default_factory=list)
    last_search_results: List[Tuple[Any, float]] = field(default_factory=list)


def _merge_doc_key(doc: Any) -> str:
    meta = getattr(doc, "metadata", None) or {}
    src = str(meta.get("source_file") or "")
    body = (getattr(doc, "page_content", None) or "")[:320]
    digest = hashlib.md5(body.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{src}\x1f{digest}"


def filter_by_absolute_floor(
    scored_docs: List[Tuple[Any, float]],
) -> List[Tuple[Any, float]]:
    """负样本防线：仅适用于「相似度尺度」的分数（向量检索的 1/(1+L2) 转换分）。

    当最高分都低于 ABSOLUTE_MIN_SCORE 时返回空列表，避免对无关查询硬凑低分结果。
    注意：RRF 融合分数（量级 ~0.01-0.1）与重排 sigmoid 分数（0-1）不适用此防线，
    故只在向量检索分支调用本函数。
    """
    if not scored_docs:
        return scored_docs
    best_score = max(score for _, score in scored_docs)
    if best_score < ABSOLUTE_MIN_SCORE:
        return []
    return scored_docs


def finalize_retrieval_from_scored(
    *,
    vector_db: Any,
    scored_docs: List[Tuple[Any, float]],
    k: int,
    sink: RetrievalUISink,
    start_time: float,
) -> RetrievalResult:
    """对已得到的 (doc, score) 做质量过滤、父块扩展与上下文拼装。"""
    out = RetrievalResult()
    if not scored_docs:
        elapsed = time.perf_counter() - start_time
        sink.caption(f"检索耗时: {elapsed:.2f} 秒（未找到相关文档）")
        return out

    high_quality_docs = [(doc, score) for doc, score in scored_docs if score >= SIMILARITY_THRESHOLD]
    if not high_quality_docs and scored_docs:
        high_quality_docs = scored_docs[: min(LOW_QUALITY_FALLBACK_K, len(scored_docs))]

    out.last_search_results = high_quality_docs

    from utils.parent_document_retrieval import expand_retrieved_chunks, should_expand_chunk

    expanded_docs: List[Tuple[Any, float]] = []
    for doc, score in high_quality_docs:
        if should_expand_chunk(doc):
            expanded_chunks = expand_retrieved_chunks(
                [(doc, score)],
                vector_db,
                expansion_strategy="parent",
                expand_to_level="medium",
            )
            expanded_docs.extend(expanded_chunks)
        else:
            expanded_docs.append((doc, score))

    if expanded_docs:
        high_quality_docs = expanded_docs[:CONTEXT_TOP_K]
        sink.caption("📖 已扩展上下文（Parent-Document Retrieval）")

    context_docs = high_quality_docs[:CONTEXT_TOP_K]
    context_parts: List[str] = []
    numbered_context_parts: List[Dict] = []
    total_length = 0
    max_context_length = MAX_CONTEXT_LENGTH

    for idx, (doc, score) in enumerate(context_docs, 1):
        doc_text = doc.page_content
        source_file = doc.metadata.get("source_file", "未知")
        chunk_level = doc.metadata.get("chunk_level", "medium")

        if total_length + len(doc_text) > max_context_length:
            remaining = max_context_length - total_length
            if remaining > 100:
                truncated_text = doc_text[:remaining] + "..."
                context_parts.append(truncated_text)
                numbered_context_parts.append(
                    {
                        "index": idx,
                        "file": source_file,
                        "content": truncated_text,
                        "full_content": doc_text,
                        "score": score,
                        "chunk_level": chunk_level,
                        "metadata": doc.metadata,
                    }
                )
            break

        context_parts.append(doc_text)
        numbered_context_parts.append(
            {
                "index": idx,
                "file": source_file,
                "content": doc_text,
                "full_content": doc_text,
                "score": score,
                "chunk_level": chunk_level,
                "metadata": doc.metadata,
            }
        )
        total_length += len(doc_text)

    numbered_context = "\n\n".join(
        [f"[来源{item['index']}] 文件：{item['file']}\n{item['content']}" for item in numbered_context_parts]
    )

    out.evidence_sources = numbered_context_parts
    out.scored_docs = high_quality_docs
    out.numbered_context = numbered_context

    elapsed = time.perf_counter() - start_time
    sink.caption(f"检索耗时: {elapsed:.2f} 秒（{len(high_quality_docs)} 个相关文档）")
    return out


def retrieve_for_rag(
    *,
    vector_db: Any,
    query: str,
    selected_kb: str,
    k: int,
    search_mode: str,
    enable_reranker: bool,
    reranker: Any,
    sink: RetrievalUISink,
) -> RetrievalResult:
    """
    执行 RAG 检索：混合/向量检索、过滤、重排、父块扩展、上下文拼装。
    不读写 Streamlit session；结果中的列表供页面写入 st.session_state。
    """
    start_time = time.perf_counter()
    out = RetrievalResult()

    from utils.improved_query_classifier import (
        classify_query_type_hybrid,
        get_chunk_level_for_query_improved,
        get_retrieval_params_for_query,
    )

    query_type, confidence = classify_query_type_hybrid(query, use_llm=False)
    preferred_levels = get_chunk_level_for_query_improved(query_type)

    type_names = {
        "precise": "精确",
        "concept": "概念",
        "summary": "总结",
        "comparison": "比较",
        "conditional": "条件",
        "reasoning": "推理",
    }
    sink.caption(f"查询类型：{type_names.get(query_type, query_type)}（置信度：{confidence:.1%}）")

    kb_doc_count = 0
    if selected_kb != "全部知识库":
        try:
            kb_documents = get_documents_by_category(selected_kb)
            kb_doc_count = len(kb_documents)
        except Exception:
            pass

    retrieval_params = get_retrieval_params_for_query(
        query_type=query_type,
        query_length=len(query),
        kb_doc_count=kb_doc_count,
    )
    fetch_k = retrieval_params["fetch_k"]

    docs_with_scores: List[Tuple[Any, float]] = []

    try:
        if search_mode == "hybrid":
            from utils.hybrid_search import load_bm25_index, hybrid_search, rebuild_bm25_index

            bm25_index, bm25_docs = load_bm25_index()
            if bm25_index is None or bm25_docs is None:
                with sink.spinner("🔨 正在构建BM25索引（首次使用需要一些时间）..."):
                    bm25_index, bm25_docs = rebuild_bm25_index(vector_db)

            if bm25_index and bm25_docs:
                docs_with_scores = hybrid_search(
                    query=query,
                    vector_db=vector_db,
                    bm25_index=bm25_index,
                    bm25_docs=bm25_docs,
                    top_k=fetch_k,
                    selected_kb=selected_kb,
                )
                sink.caption("🔀 使用混合检索（BM25 + 向量 + RRF）")
            else:
                sink.warning("⚠️ BM25索引构建失败，回退到向量检索")
                docs_with_scores = vector_db.similarity_search_with_score(query, k=fetch_k)
                docs_with_scores = [(doc, 1 / (1 + score)) for doc, score in docs_with_scores]
        else:
            docs_with_scores = vector_db.similarity_search_with_score(query, k=fetch_k)
            docs_with_scores = [(doc, 1 / (1 + score)) for doc, score in docs_with_scores]
            sink.caption("🔍 使用向量检索")

        if search_mode == "vector":
            # 负样本防线：向量相似度最高分低于绝对下限 → 无相关内容
            docs_with_scores = filter_by_absolute_floor(docs_with_scores)
            if not docs_with_scores:
                elapsed = time.perf_counter() - start_time
                sink.caption(f"检索耗时: {elapsed:.2f} 秒（未找到相关内容）")
                return out

        from utils.score_normalization import normalize_scores_by_kb

        if selected_kb == "全部知识库" and len(docs_with_scores) > 5:
            docs_with_scores = normalize_scores_by_kb(
                docs_with_scores,
                selected_kb=selected_kb,
                normalization_method="min_max",
            )
            sink.caption("📊 已应用分数归一化（Min-Max Scaling）")
    except Exception as e:
        sink.error(f"检索出错: {str(e)}")
        return out

    kb_file_names: Optional[set] = None
    if selected_kb != "全部知识库":
        kb_documents = get_documents_by_category(selected_kb)
        kb_file_names = set(doc.get("file_name") for doc in kb_documents)
        if not kb_file_names:
            elapsed = time.perf_counter() - start_time
            sink.caption(f"检索耗时: {elapsed:.2f} 秒（知识库为空）")
            return out
    else:
        all_active = get_all_documents(include_deleted=False)
        names = {str(d.get("file_name")) for d in all_active if d.get("file_name")}
        if names:
            kb_file_names = names

    preferred_docs: List[Tuple[Any, float, str]] = []
    fallback_docs: List[Tuple[Any, float, str]] = []

    for doc, score in docs_with_scores:
        source_file = doc.metadata.get("source_file")

        if source_file in ["system", None] or doc.metadata.get("note") == "empty_init":
            continue

        if kb_file_names and source_file not in kb_file_names:
            continue

        if search_mode == "hybrid":
            similarity = score
        else:
            similarity = score

        chunk_level = doc.metadata.get("chunk_level", "medium")

        if chunk_level in preferred_levels:
            preferred_docs.append((doc, similarity, chunk_level))
        else:
            fallback_docs.append((doc, similarity, chunk_level))

        if len(preferred_docs) >= k * 2:
            break

    filtered_docs: List[Tuple[Any, float]] = []
    for doc, sim, _level in preferred_docs:
        filtered_docs.append((doc, sim))

    if len(filtered_docs) < k:
        for doc, sim, _level in fallback_docs:
            filtered_docs.append((doc, sim))
            if len(filtered_docs) >= k:
                break

    initial_docs = [doc for doc, _ in filtered_docs[:k]]
    initial_scores = [score for _, score in filtered_docs[:k]]

    if not initial_docs:
        elapsed = time.perf_counter() - start_time
        sink.caption(f"检索耗时: {elapsed:.2f} 秒（未找到相关文档）")
        return out

    if enable_reranker and reranker is not None:
        scored_docs = rerank_documents(
            query=query,
            documents=initial_docs,
            reranker=reranker,
            top_k=k,
            reranker_type="local",
        )
    else:
        scored_docs = list(zip(initial_docs, initial_scores))

    return finalize_retrieval_from_scored(
        vector_db=vector_db,
        scored_docs=scored_docs,
        k=k,
        sink=sink,
        start_time=start_time,
    )


def retrieve_for_rag_multi(
    *,
    vector_db: Any,
    queries: List[str],
    final_rerank_query: str,
    selected_kb: str,
    k: int,
    search_mode: str,
    enable_reranker: bool,
    reranker: Any,
    sink: RetrievalUISink,
) -> RetrievalResult:
    """
    多子查询检索：各子问分别召回，按块去重合并后，用「整句用户问题」做一次重排序（若开启）。
    适用于一句多问、子问题语义差异大的场景。
    """
    start_time = time.perf_counter()
    queries = [q.strip() for q in queries if q.strip()][:5]
    if not queries:
        return RetrievalResult()
    if len(queries) == 1:
        return retrieve_for_rag(
            vector_db=vector_db,
            query=queries[0],
            selected_kb=selected_kb,
            k=k,
            search_mode=search_mode,
            enable_reranker=enable_reranker,
            reranker=reranker,
            sink=sink,
        )

    n = len(queries)
    k_sub = max(5, min(k + 4, (k * 4) // n + n + 3))
    sink.caption(f"🔀 多子查询检索（{n} 条）→ 合并去重 → 整句重排")

    merged: Dict[str, Tuple[Any, float]] = {}
    for subq in queries:
        sub = retrieve_for_rag(
            vector_db=vector_db,
            query=subq,
            selected_kb=selected_kb,
            k=k_sub,
            search_mode=search_mode,
            enable_reranker=False,
            reranker=None,
            sink=RetrievalUISink.noop(),
        )
        for doc, sc in sub.scored_docs:
            key = _merge_doc_key(doc)
            old = merged.get(key)
            if old is None or sc > old[1]:
                merged[key] = (doc, sc)

    pool = sorted(merged.values(), key=lambda x: x[1], reverse=True)
    pool = pool[: max(k * 3, 24)]
    docs_only = [d for d, _ in pool]

    if enable_reranker and reranker is not None and docs_only:
        scored_docs = rerank_documents(
            query=final_rerank_query,
            documents=docs_only,
            reranker=reranker,
            top_k=k,
            reranker_type="local",
        )
    else:
        scored_docs = pool[:k]

    return finalize_retrieval_from_scored(
        vector_db=vector_db,
        scored_docs=scored_docs,
        k=k,
        sink=sink,
        start_time=start_time,
    )
