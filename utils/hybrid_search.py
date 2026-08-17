# utils/hybrid_search.py
"""
混合检索模块：BM25关键词检索 + 向量检索 + RRF融合
解决向量检索在专有名词、产品型号等场景下的局限性

分数语义（重要）：返回的 score 是「证据分」0-1（max(向量相似度, BM25 归一分)），
与 config 的 SIMILARITY_THRESHOLD / ABSOLUTE_MIN_SCORE 同尺度可比；
RRF 只决定排序，不直接作为分数（RRF 原始量级 ~0.01，与绝对阈值比较无意义）。
"""
import hashlib
import logging
import os
import pickle
from typing import List, Tuple, Dict, Optional
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi
import jieba
from utils.path_context import get_kb_dir

logger = logging.getLogger(__name__)

# 分词器版本：升版后索引文件名变化，旧 pickle 自动失效重建（改 tokenize 规则必须升版）
_BM25_TOKENIZER_VERSION = 3

# 单字 CJK 保留白名单除外的高频虚词（单字保留是为了单字查询/型号的 BM25 召回）
_BM25_SINGLE_CHAR_STOP = set(
    "的了是在和与及或就也都还把被让给跟比这那位吗呢吧啊嘛么"
)

# 多字疑问/功能虚词：从 BM25 token 中剔除（会稀释查询词覆盖率、引入跨域巧合命中）
_BM25_MULTI_CHAR_STOP = {"怎么", "如何", "为什么", "什么", "哪些", "哪个"}


def _bm25_index_file() -> str:
    return os.path.join(get_kb_dir(), f"bm25_index.v{_BM25_TOKENIZER_VERSION}.pkl")


def _bm25_docs_file() -> str:
    return os.path.join(get_kb_dir(), f"bm25_docs.v{_BM25_TOKENIZER_VERSION}.pkl")


def _legacy_bm25_files() -> List[str]:
    kb = get_kb_dir()
    return [
        os.path.join(kb, "bm25_index.pkl"),
        os.path.join(kb, "bm25_docs.pkl"),
    ] + [
        os.path.join(kb, f"bm25_index.v{v}.pkl") for v in range(1, _BM25_TOKENIZER_VERSION)
    ] + [
        os.path.join(kb, f"bm25_docs.v{v}.pkl") for v in range(1, _BM25_TOKENIZER_VERSION)
    ]


def invalidate_bm25_index() -> None:
    """标记当前知识库的 BM25 索引为失效（入库/删除后调用）。

    删除已持久化的索引文件（含历史版本），使下次混合检索时自动重建，
    避免「旧索引 + 新文档」导致的一致性偏移问题。
    """
    for p in (_bm25_index_file(), _bm25_docs_file(), *_legacy_bm25_files()):
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            logger.warning("失效 BM25 索引失败: %s", p)


def _fusion_key(doc: Document) -> str:
    """跨来源稳定标识：source_file + 内容哈希。

    不能用 id(doc)：BM25 文档来自 pickle 反序列化，与向量检索返回的 docstore
    对象必然不同 id，同块两路永远无法融合。
    """
    meta = getattr(doc, "metadata", None) or {}
    src = str(meta.get("source_file") or "")
    body = (getattr(doc, "page_content", None) or "")[:320]
    digest = hashlib.md5(body.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{src}\x1f{digest}"


def tokenize_chinese(text: str) -> List[str]:
    """
    中文分词（用于BM25）。保留单字 CJK token（非虚词），避免单字查询/型号无关键词可用。
    """
    words = jieba.cut(text)
    out: List[str] = []
    for w in words:
        w = w.strip()
        if not w:
            continue
        if len(w) == 1:
            if "\u4e00" <= w <= "\u9fff" and w not in _BM25_SINGLE_CHAR_STOP:
                out.append(w)
            continue
        if w in _BM25_MULTI_CHAR_STOP:
            continue
        out.append(w)
    return out


def build_bm25_index(documents: List[Document]) -> Optional[BM25Okapi]:
    """
    构建BM25索引
    :param documents: 文档列表
    :return: BM25索引对象
    """
    if not documents:
        return None
    
    # 提取文档内容并分词
    tokenized_docs = []
    for doc in documents:
        content = doc.page_content if hasattr(doc, 'page_content') else str(doc)
        tokens = tokenize_chinese(content)
        tokenized_docs.append(tokens)
    
    if not tokenized_docs:
        return None
    
    # 构建BM25索引
    bm25 = BM25Okapi(tokenized_docs)
    return bm25


def save_bm25_index(bm25_index: BM25Okapi, documents: List[Document]):
    """
    保存BM25索引和文档
    """
    try:
        kb = get_kb_dir()
        os.makedirs(kb, exist_ok=True)
        idx_f, docs_f = _bm25_index_file(), _bm25_docs_file()
        with open(idx_f, "wb") as f:
            pickle.dump(bm25_index, f)
        with open(docs_f, "wb") as f:
            pickle.dump(documents, f)
        logger.info("[BM25] 索引已保存到: %s", idx_f)
    except Exception as e:
        logger.warning("[BM25] 保存索引失败: %s", e)


def load_bm25_index() -> Tuple[Optional[BM25Okapi], Optional[List[Document]]]:
    """
    加载BM25索引和文档
    """
    try:
        idx_f, docs_f = _bm25_index_file(), _bm25_docs_file()
        if os.path.exists(idx_f) and os.path.exists(docs_f):
            with open(idx_f, "rb") as f:
                bm25_index = pickle.load(f)
            with open(docs_f, "rb") as f:
                documents = pickle.load(f)
            logger.info("[BM25] 索引已加载: %d 个文档", len(documents))
            return bm25_index, documents
    except Exception as e:
        logger.warning("[BM25] 加载索引失败: %s", e)
    return None, None


def bm25_search(
    query: str,
    bm25_index: BM25Okapi,
    documents: List[Document],
    top_k: int = 10
) -> List[Tuple[Document, float]]:
    """
    BM25关键词检索
    :param query: 查询文本
    :param bm25_index: BM25索引
    :param documents: 文档列表
    :param top_k: 返回前k个结果
    :return: [(Document, score), ...]
    """
    if not bm25_index or not documents:
        return []
    
    # 分词查询
    query_tokens = tokenize_chinese(query)
    if not query_tokens:
        return []
    
    # BM25检索
    scores = bm25_index.get_scores(query_tokens)
    
    # 排序并返回top_k
    doc_scores = list(zip(documents, scores))
    doc_scores.sort(key=lambda x: x[1], reverse=True)
    
    return doc_scores[:top_k]


def rrf_fusion(
    vector_results: List[Tuple[Document, float]],
    bm25_results: List[Tuple[Document, float]],
    k: int = 60  # RRF参数
) -> List[Tuple[Document, float]]:
    """
    RRF (Reciprocal Rank Fusion) 融合算法
    融合向量检索和BM25检索的结果

    :param vector_results: 向量检索结果 [(doc, score), ...]
    :param bm25_results: BM25检索结果 [(doc, score), ...]
    :param k: RRF参数，通常为60
    :return: 融合后的结果 [(doc, 证据分), ...]，按 RRF 排序；
             证据分 = max(该文档的向量相似度, BM25 归一分)，与绝对阈值同尺度
    """
    doc_rrf_scores: Dict[str, Dict] = {}
    vector_evidence: Dict[str, float] = {}
    bm25_evidence: Dict[str, float] = {}

    for rank, (doc, score) in enumerate(vector_results, 1):
        doc_id = _fusion_key(doc)
        vector_evidence[doc_id] = max(vector_evidence.get(doc_id, 0.0), float(score))
        if doc_id not in doc_rrf_scores:
            doc_rrf_scores[doc_id] = {"doc": doc, "rrf_score": 0.0}
        doc_rrf_scores[doc_id]["rrf_score"] += 1.0 / (k + rank)

    for rank, (doc, score) in enumerate(bm25_results, 1):
        doc_id = _fusion_key(doc)
        bm25_evidence[doc_id] = max(bm25_evidence.get(doc_id, 0.0), float(score))
        if doc_id not in doc_rrf_scores:
            doc_rrf_scores[doc_id] = {"doc": doc, "rrf_score": 0.0}
        doc_rrf_scores[doc_id]["rrf_score"] += 1.0 / (k + rank)

    fused_results = sorted(doc_rrf_scores.values(), key=lambda x: x["rrf_score"], reverse=True)

    out: List[Tuple[Document, float]] = []
    for item in fused_results:
        doc_id = _fusion_key(item["doc"])
        evidence = max(vector_evidence.get(doc_id, 0.0), bm25_evidence.get(doc_id, 0.0))
        out.append((item["doc"], evidence))
    return out


def _bm25_coverage_gate(
    query_toks: List[str],
    bm25_results: List[Tuple[Document, float]],
    min_coverage: float = 0.5,
) -> List[Tuple[Document, float]]:
    """BM25 命中的查询词覆盖率门控。

    背景（2026-08-17 评测）：103 条评测集中负样本误召回 88% 来自弱词重叠——
    「黑洞的信息悖论」仅靠「信息」一词命中提示词文档并取得 BM25 最高分，
    经归一化后 evidence=1.0 直接穿透负样本防线。
    规则：文档须覆盖查询分词的至少 min_coverage 比例，且命中词中至少一个为多字词
    （排除单字巧合，如「潜水证」的「证」撞上「借阅证」）。
    """
    if not bm25_results:
        return []
    if not query_toks:
        return []
    out: List[Tuple[Document, float]] = []
    for doc, score in bm25_results:
        # 子串匹配而非 token 相等：分词边界不一致（查询「逾期」vs 文档 token「逾期费」）
        # 会让真实命中漏检，用原文包含判断对此鲁棒
        text = doc.page_content or ""
        matched = [t for t in query_toks if t in text]
        if not matched:
            continue
        if len(matched) / len(query_toks) < min_coverage:
            continue
        if not any(len(t) >= 2 for t in matched):
            continue
        out.append((doc, score))
    return out


def hybrid_search(
    query: str,
    vector_db,
    bm25_index: Optional[BM25Okapi],
    bm25_docs: Optional[List[Document]],
    top_k: int = 10,
    vector_weight: float = 0.5,
    bm25_weight: float = 0.5,
    selected_kb: str = "全部知识库"
) -> List[Tuple[Document, float]]:
    """
    混合检索：向量检索 + BM25检索 + RRF融合（支持分数归一化）
    
    :param query: 查询文本
    :param vector_db: 向量数据库（FAISS）
    :param bm25_index: BM25索引
    :param bm25_docs: BM25文档列表
    :param top_k: 返回结果数量
    :param vector_weight: 向量检索权重（0-1）
    :param bm25_weight: BM25检索权重（0-1）
    :param selected_kb: 选择的知识库（用于分数归一化）
    :return: 融合后的检索结果 [(doc, score), ...]
    """
    results = []

    # 1. 向量检索
    try:
        vector_results = vector_db.similarity_search_with_score(query, k=top_k * 2)
        # 转换L2距离为相似度
        vector_results = [
            (doc, 1 / (1 + score)) for doc, score in vector_results
        ]
    except Exception as e:
        logger.warning("[Hybrid] 向量检索失败: %s", e)
        vector_results = []

    # 2. BM25检索（先于负样本判定：BM25 精确命中时不应被向量地板一票否决）
    bm25_results = []
    bm25_max_raw = 0.0
    if bm25_index and bm25_docs:
        try:
            raw_results = bm25_search(query, bm25_index, bm25_docs, top_k=top_k * 2)
            # 词覆盖率门控：剔除仅靠个别公共词的弱命中（负样本误召回主因）
            bm25_results = _bm25_coverage_gate(tokenize_chinese(query), raw_results)
            if bm25_results:
                bm25_max_raw = max(score for _, score in bm25_results)
                # 归一化BM25分数到0-1范围（作为证据分；排序由 RRF 决定）
                if bm25_max_raw > 0:
                    bm25_results = [
                        (doc, score / bm25_max_raw) for doc, score in bm25_results
                    ]
                else:
                    bm25_results = []
        except Exception as e:
            logger.warning("[Hybrid] BM25检索失败: %s", e)
            bm25_results = []

    # 3. 负样本防线：向量与 BM25 双信号都无命中才判「无相关内容」。
    #    （向量最高分低于地板但 BM25 有精确命中 = 专有名词/型号场景，是混合检索的目标场景）
    if vector_results:
        from config import ABSOLUTE_MIN_SCORE

        vector_max = max(s for _, s in vector_results)
        if vector_max < ABSOLUTE_MIN_SCORE and bm25_max_raw <= 1e-9:
            logger.info(
                "[Hybrid] 向量相似度过低（<%.2f）且 BM25 无命中，视为无相关内容", ABSOLUTE_MIN_SCORE
            )
            return []
        if vector_max < ABSOLUTE_MIN_SCORE:
            logger.info(
                "[Hybrid] 向量相似度过低（<%.2f），但 BM25 有命中，继续融合", ABSOLUTE_MIN_SCORE
            )

    # 4. 分数归一化（按知识库分组归一化，解决分数膨胀问题）
    if selected_kb == "全部知识库" and (vector_results or bm25_results):
        from utils.score_normalization import normalize_hybrid_search_scores
        try:
            vector_results, bm25_results = normalize_hybrid_search_scores(
                vector_results, bm25_results, selected_kb
            )
        except Exception as e:
            logger.warning("[Hybrid] 分数归一化失败: %s，使用原始分数", e)

    # 5. RRF融合（排序）+ 证据分（0-1，与阈值同尺度）
    if vector_results and bm25_results:
        fused_results = rrf_fusion(vector_results, bm25_results, k=60)
        results = fused_results[:top_k]
    elif vector_results:
        results = vector_results[:top_k]
    elif bm25_results:
        results = bm25_results[:top_k]

    return results


def rebuild_bm25_index(vector_db) -> Tuple[Optional[BM25Okapi], Optional[List[Document]]]:
    """
    从向量数据库重建BM25索引
    """
    try:
        # 获取所有文档（使用空查询获取所有文档）
        all_docs = vector_db.similarity_search("", k=100000)
        
        # 过滤掉系统文档
        valid_docs = [
            doc for doc in all_docs
            if doc.metadata.get("source_file") not in ["system", None]
            and doc.metadata.get("note") != "empty_init"
        ]
        
        if not valid_docs:
            logger.warning("[BM25] 没有有效文档，无法构建索引")
            return None, None
        
        logger.info("[BM25] 开始构建索引，文档数: %d", len(valid_docs))
        bm25_index = build_bm25_index(valid_docs)
        
        if bm25_index:
            save_bm25_index(bm25_index, valid_docs)
            logger.info("[BM25] 索引构建完成")
            return bm25_index, valid_docs
        else:
            logger.warning("[BM25] 索引构建失败")
            return None, None
            
    except Exception as e:
        logger.warning("[BM25] 重建索引失败: %s", e)
        return None, None

