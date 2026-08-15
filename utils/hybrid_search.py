# utils/hybrid_search.py
"""
混合检索模块：BM25关键词检索 + 向量检索 + RRF融合
解决向量检索在专有名词、产品型号等场景下的局限性
"""
import logging
import os
import pickle
from typing import List, Tuple, Dict, Optional
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi
import jieba
from utils.path_context import get_kb_dir

logger = logging.getLogger(__name__)


def _bm25_index_file() -> str:
    return os.path.join(get_kb_dir(), "bm25_index.pkl")


def _bm25_docs_file() -> str:
    return os.path.join(get_kb_dir(), "bm25_docs.pkl")


def invalidate_bm25_index() -> None:
    """标记当前知识库的 BM25 索引为失效（入库/删除后调用）。

    删除已持久化的 bm25_index.pkl / bm25_docs.pkl，使下次混合检索时自动重建，
    避免「旧索引 + 新文档」导致的一致性偏移问题。
    """
    for p in (_bm25_index_file(), _bm25_docs_file()):
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            logger.warning("失效 BM25 索引失败: %s", p)


def tokenize_chinese(text: str) -> List[str]:
    """
    中文分词（用于BM25）
    """
    # 使用jieba分词
    words = jieba.cut(text)
    return [w for w in words if w.strip() and len(w.strip()) > 1]


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
    :return: 融合后的结果 [(doc, rrf_score), ...]
    """
    # 创建文档到RRF分数的映射
    doc_rrf_scores = {}
    
    # 处理向量检索结果
    for rank, (doc, score) in enumerate(vector_results, 1):
        doc_id = id(doc)  # 使用文档对象ID作为唯一标识
        if doc_id not in doc_rrf_scores:
            doc_rrf_scores[doc_id] = {
                'doc': doc,
                'rrf_score': 0.0,
                'vector_rank': rank,
                'bm25_rank': None
            }
        doc_rrf_scores[doc_id]['rrf_score'] += 1.0 / (k + rank)
        doc_rrf_scores[doc_id]['vector_rank'] = rank
    
    # 处理BM25检索结果
    for rank, (doc, score) in enumerate(bm25_results, 1):
        doc_id = id(doc)
        if doc_id not in doc_rrf_scores:
            doc_rrf_scores[doc_id] = {
                'doc': doc,
                'rrf_score': 0.0,
                'vector_rank': None,
                'bm25_rank': rank
            }
        doc_rrf_scores[doc_id]['rrf_score'] += 1.0 / (k + rank)
        doc_rrf_scores[doc_id]['bm25_rank'] = rank
    
    # 按RRF分数排序
    fused_results = sorted(
        doc_rrf_scores.values(),
        key=lambda x: x['rrf_score'],
        reverse=True
    )
    
    # 转换为标准格式
    return [(item['doc'], item['rrf_score']) for item in fused_results]


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
    
    # 2. BM25检索
    bm25_results = []
    if bm25_index and bm25_docs:
        try:
            bm25_results = bm25_search(query, bm25_index, bm25_docs, top_k=top_k * 2)
            # 归一化BM25分数到0-1范围（全局归一化）
            if bm25_results:
                max_score = max(score for _, score in bm25_results)
                if max_score > 0:
                    bm25_results = [
                        (doc, score / max_score) for doc, score in bm25_results
                    ]
        except Exception as e:
            logger.warning("[Hybrid] BM25检索失败: %s", e)
    
    # 3. 分数归一化（按知识库分组归一化，解决分数膨胀问题）
    if selected_kb == "全部知识库" and (vector_results or bm25_results):
        from utils.score_normalization import normalize_hybrid_search_scores
        try:
            vector_results, bm25_results = normalize_hybrid_search_scores(
                vector_results, bm25_results, selected_kb
            )
        except Exception as e:
            logger.warning("[Hybrid] 分数归一化失败: %s，使用原始分数", e)
    
    # 4. RRF融合
    if vector_results and bm25_results:
        # 使用RRF融合
        fused_results = rrf_fusion(vector_results, bm25_results, k=60)
        results = fused_results[:top_k]
    elif vector_results:
        # 只有向量检索结果
        results = vector_results[:top_k]
    elif bm25_results:
        # 只有BM25检索结果
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

