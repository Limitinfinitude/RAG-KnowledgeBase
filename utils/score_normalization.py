# utils/score_normalization.py
"""
分数归一化模块：解决多知识库下的"分数膨胀"问题
使用Min-Max Scaling将不同知识库的分数映射到同一区间
"""
from typing import List, Tuple, Dict, Optional
from langchain_core.documents import Document
from utils.metadata_manager import get_documents_by_category


def min_max_normalize(
    scores: List[float],
    min_val: Optional[float] = None,
    max_val: Optional[float] = None
) -> List[float]:
    """
    Min-Max归一化：将分数映射到[0, 1]区间
    
    :param scores: 原始分数列表
    :param min_val: 最小值（如果为None，则使用scores的最小值）
    :param max_val: 最大值（如果为None，则使用scores的最大值）
    :return: 归一化后的分数列表
    """
    if not scores:
        return []
    
    if min_val is None:
        min_val = min(scores)
    if max_val is None:
        max_val = max(scores)
    
    # 如果所有分数相同，返回0.5（中间值）
    if max_val == min_val:
        return [0.5] * len(scores)
    
    # Min-Max归一化公式：x' = (x - min) / (max - min)
    normalized = [(score - min_val) / (max_val - min_val) for score in scores]
    
    return normalized


def group_docs_by_knowledge_base(
    docs_with_scores: List[Tuple[Document, float]],
    selected_kb: str = "全部知识库"
) -> Dict[str, List[Tuple[Document, float]]]:
    """
    按知识库分组文档
    
    :param docs_with_scores: 文档和分数列表
    :param selected_kb: 选择的知识库（"全部知识库"或具体知识库名）
    :return: {知识库名: [(doc, score), ...]}
    """
    kb_groups = {}
    
    if selected_kb == "全部知识库":
        # 需要按文件所属的知识库分组
        try:
            from utils.metadata_manager import get_categories, get_documents_by_category
            
            # 获取所有知识库
            all_categories = get_categories()
            
            # 为每个知识库创建文件集合
            kb_file_map = {}
            for category in all_categories:
                kb_docs = get_documents_by_category(category)
                kb_file_map[category] = set(doc.get("file_name") for doc in kb_docs)
            
            # 分组文档
            for doc, score in docs_with_scores:
                source_file = doc.metadata.get("source_file")
                if not source_file or source_file in ["system", None]:
                    continue
                
                # 查找文档所属的知识库
                found_kb = None
                for kb_name, file_set in kb_file_map.items():
                    if source_file in file_set:
                        found_kb = kb_name
                        break
                
                # 如果找不到，归入"未知知识库"
                if found_kb is None:
                    found_kb = "未知知识库"
                
                if found_kb not in kb_groups:
                    kb_groups[found_kb] = []
                kb_groups[found_kb].append((doc, score))
        except Exception as e:
            print(f"[ScoreNorm] 分组失败: {e}，使用单一分组")
            # 失败时，所有文档归为一组
            kb_groups["全部"] = docs_with_scores
    else:
        # 单一知识库，直接分组
        kb_groups[selected_kb] = docs_with_scores
    
    return kb_groups


def normalize_scores_by_kb(
    docs_with_scores: List[Tuple[Document, float]],
    selected_kb: str = "全部知识库",
    normalization_method: str = "min_max"
) -> List[Tuple[Document, float]]:
    """
    按知识库归一化分数，解决分数膨胀问题
    
    :param docs_with_scores: 文档和分数列表
    :param selected_kb: 选择的知识库
    :param normalization_method: 归一化方法（"min_max" 或 "z_score"）
    :return: 归一化后的文档和分数列表
    """
    if not docs_with_scores:
        return []
    
    # 如果只有一个知识库或文档很少，不需要归一化
    if selected_kb != "全部知识库" or len(docs_with_scores) < 5:
        return docs_with_scores
    
    # 按知识库分组
    kb_groups = group_docs_by_knowledge_base(docs_with_scores, selected_kb)
    
    # 如果只有一个组，不需要归一化
    if len(kb_groups) <= 1:
        return docs_with_scores
    
    # 对每个知识库的分数进行归一化
    normalized_results = []
    
    for kb_name, kb_docs in kb_groups.items():
        if not kb_docs:
            continue
        
        # 提取分数
        scores = [score for _, score in kb_docs]
        
        # 归一化
        if normalization_method == "min_max":
            normalized_scores = min_max_normalize(scores)
        else:
            # 默认使用min_max
            normalized_scores = min_max_normalize(scores)
        
        # 重新组合
        for (doc, _), norm_score in zip(kb_docs, normalized_scores):
            normalized_results.append((doc, norm_score))
    
    return normalized_results


def normalize_hybrid_search_scores(
    vector_results: List[Tuple[Document, float]],
    bm25_results: List[Tuple[Document, float]],
    selected_kb: str = "全部知识库"
) -> Tuple[List[Tuple[Document, float]], List[Tuple[Document, float]]]:
    """
    归一化混合检索的分数（向量检索和BM25检索分别归一化）
    
    :param vector_results: 向量检索结果
    :param bm25_results: BM25检索结果
    :param selected_kb: 选择的知识库
    :return: (归一化后的向量结果, 归一化后的BM25结果)
    """
    # 分别归一化向量检索和BM25检索的分数
    normalized_vector = normalize_scores_by_kb(vector_results, selected_kb)
    normalized_bm25 = normalize_scores_by_kb(bm25_results, selected_kb)
    
    return normalized_vector, normalized_bm25


def adaptive_score_fusion(
    vector_results: List[Tuple[Document, float]],
    bm25_results: List[Tuple[Document, float]],
    selected_kb: str = "全部知识库",
    vector_weight: float = 0.5,
    bm25_weight: float = 0.5
) -> List[Tuple[Document, float]]:
    """
    自适应分数融合：先归一化，再融合
    
    :param vector_results: 向量检索结果
    :param bm25_results: BM25检索结果
    :param selected_kb: 选择的知识库
    :param vector_weight: 向量检索权重
    :param bm25_weight: BM25检索权重
    :return: 融合后的结果
    """
    # 1. 归一化分数
    norm_vector, norm_bm25 = normalize_hybrid_search_scores(
        vector_results, bm25_results, selected_kb
    )
    
    # 2. 创建文档到分数的映射
    doc_scores = {}
    
    # 处理向量检索结果
    for doc, score in norm_vector:
        doc_id = id(doc)
        if doc_id not in doc_scores:
            doc_scores[doc_id] = {"doc": doc, "vector_score": 0.0, "bm25_score": 0.0}
        doc_scores[doc_id]["vector_score"] = score
    
    # 处理BM25检索结果
    for doc, score in norm_bm25:
        doc_id = id(doc)
        if doc_id not in doc_scores:
            doc_scores[doc_id] = {"doc": doc, "vector_score": 0.0, "bm25_score": 0.0}
        doc_scores[doc_id]["bm25_score"] = score
    
    # 3. 加权融合
    fused_results = []
    for doc_id, scores in doc_scores.items():
        fused_score = (
            scores["vector_score"] * vector_weight +
            scores["bm25_score"] * bm25_weight
        )
        fused_results.append((scores["doc"], fused_score))
    
    # 4. 按融合分数排序
    fused_results.sort(key=lambda x: x[1], reverse=True)
    
    return fused_results

