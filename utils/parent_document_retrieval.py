# utils/parent_document_retrieval.py
"""
Parent-Document Retrieval（检索与读取分离）
解决颗粒度悖论：检索时用精确的小chunk，读取时扩展为完整的上下文
"""
from typing import List, Tuple, Optional
from langchain_core.documents import Document


def expand_chunk_to_parent(
    chunk: Document,
    vector_db,
    expand_to_level: str = "medium"
) -> Optional[Document]:
    """
    将检索到的小chunk扩展为其父级chunk
    
    :param chunk: 检索到的chunk（通常是small）
    :param vector_db: 向量数据库
    :param expand_to_level: 扩展到的层级（medium 或 large）
    :return: 父级chunk，如果找不到则返回None
    """
    source_file = chunk.metadata.get("source_file")
    chunk_level = chunk.metadata.get("chunk_level", "medium")
    
    if not source_file or source_file in ["system", None]:
        return None
    
    # 如果已经是目标层级或更高层级，不需要扩展
    level_hierarchy = {"small": 0, "medium": 1, "large": 2, "summary": 3}
    if level_hierarchy.get(chunk_level, 1) >= level_hierarchy.get(expand_to_level, 1):
        return None
    
    try:
        # 从向量数据库中查找同一文件的父级chunk
        # 使用chunk的部分内容作为查询
        query_text = chunk.page_content[:200]  # 使用chunk的前200字作为查询
        
        # 检索更多结果以找到父级chunk（FAISS不支持filter，需要手动过滤）
        candidates = vector_db.similarity_search_with_score(query_text, k=100)
        
        # 查找匹配的父级chunk
        for candidate_doc, score in candidates:
            candidate_file = candidate_doc.metadata.get("source_file")
            candidate_level = candidate_doc.metadata.get("chunk_level", "medium")
            
            # 检查是否是同一文件且是目标层级的chunk
            if candidate_file == source_file and candidate_level == expand_to_level:
                # 检查父级chunk是否包含当前chunk的内容
                chunk_start = chunk.page_content[:100]
                if chunk_start in candidate_doc.page_content:
                    return candidate_doc
        
        return None
    except Exception as e:
        print(f"[ParentDoc] 扩展chunk失败: {e}")
        return None


def expand_chunk_with_neighbors(
    chunk: Document,
    vector_db,
    neighbor_count: int = 1
) -> List[Document]:
    """
    扩展chunk，包含其前后相邻的chunk
    
    :param chunk: 检索到的chunk
    :param vector_db: 向量数据库
    :param neighbor_count: 前后各取几个相邻chunk
    :return: 扩展后的chunk列表 [前chunk, 当前chunk, 后chunk]
    """
    source_file = chunk.metadata.get("source_file")
    chunk_level = chunk.metadata.get("chunk_level", "medium")
    chunk_index = chunk.metadata.get("chunk_index")
    total_chunks = chunk.metadata.get("total_chunks", 0)
    
    if not source_file or source_file in ["system", None]:
        return [chunk]
    
    if chunk_index is None:
        return [chunk]
    
    expanded_chunks = []
    
    try:
        # 使用chunk内容作为查询，找到同一文件同一层级的chunk
        query_text = chunk.page_content[:200]
        candidates = vector_db.similarity_search_with_score(query_text, k=200)  # 检索更多候选
        
        # 构建索引映射：chunk_index -> Document（只保留同一文件同一层级的）
        chunk_map = {}
        for candidate_doc, _ in candidates:
            candidate_file = candidate_doc.metadata.get("source_file")
            candidate_level = candidate_doc.metadata.get("chunk_level", "medium")
            idx = candidate_doc.metadata.get("chunk_index")
            
            if (candidate_file == source_file and 
                candidate_level == chunk_level and 
                idx is not None):
                chunk_map[idx] = candidate_doc
        
        # 确保当前chunk在映射中
        chunk_map[chunk_index] = chunk
        
        # 收集相邻chunk
        for i in range(max(0, chunk_index - neighbor_count), 
                      min(total_chunks, chunk_index + neighbor_count + 1)):
            if i in chunk_map:
                expanded_chunks.append(chunk_map[i])
        
        # 按索引排序
        expanded_chunks.sort(key=lambda d: d.metadata.get("chunk_index", 0))
        
        # 去重
        seen = set()
        result = []
        for doc in expanded_chunks:
            doc_id = id(doc)
            if doc_id not in seen:
                seen.add(doc_id)
                result.append(doc)
        
        return result if result else [chunk]
        
    except Exception as e:
        print(f"[ParentDoc] 扩展相邻chunk失败: {e}")
        return [chunk]


def expand_retrieved_chunks(
    retrieved_chunks: List[Tuple[Document, float]],
    vector_db,
    expansion_strategy: str = "parent",
    expand_to_level: str = "medium"
) -> List[Tuple[Document, float]]:
    """
    扩展检索到的chunks，解决颗粒度悖论
    
    :param retrieved_chunks: 检索结果 [(doc, score), ...]
    :param vector_db: 向量数据库
    :param expansion_strategy: 扩展策略
        - "parent": 扩展到父级chunk（推荐）
        - "neighbors": 扩展到相邻chunk
        - "both": 先尝试父级，失败则使用相邻
        - "none": 不扩展
    :param expand_to_level: 扩展到哪个层级（仅用于parent策略）
    :return: 扩展后的chunks [(doc, score), ...]
    """
    if expansion_strategy == "none":
        return retrieved_chunks
    
    expanded_results = []
    
    for chunk, score in retrieved_chunks:
        chunk_level = chunk.metadata.get("chunk_level", "medium")
        
        # 决定扩展策略
        if expansion_strategy == "parent" or expansion_strategy == "both":
            # 尝试扩展到父级
            parent_chunk = expand_chunk_to_parent(chunk, vector_db, expand_to_level)
            if parent_chunk:
                # 使用父级chunk，保持原始分数
                expanded_results.append((parent_chunk, score))
                continue
        
        if expansion_strategy == "neighbors" or (expansion_strategy == "both" and not parent_chunk):
            # 使用相邻chunk
            neighbor_chunks = expand_chunk_with_neighbors(chunk, vector_db, neighbor_count=1)
            # 合并相邻chunk的内容
            if len(neighbor_chunks) > 1:
                # 合并多个chunk的内容
                combined_content = "\n\n".join([c.page_content for c in neighbor_chunks])
                # 创建合并后的文档
                combined_doc = Document(
                    page_content=combined_content,
                    metadata={
                        **chunk.metadata,
                        "expanded_from": chunk_level,
                        "expansion_type": "neighbors",
                        "neighbor_count": len(neighbor_chunks)
                    }
                )
                expanded_results.append((combined_doc, score))
            else:
                expanded_results.append((chunk, score))
        else:
            # 不扩展或扩展失败，使用原始chunk
            expanded_results.append((chunk, score))
    
    return expanded_results


def should_expand_chunk(chunk: Document) -> bool:
    """
    判断是否应该扩展chunk
    
    :param chunk: chunk文档
    :return: 是否应该扩展
    """
    chunk_level = chunk.metadata.get("chunk_level", "medium")
    
    # 小chunk通常需要扩展
    if chunk_level == "small":
        return True
    
    # 检查chunk是否在中间断开（简单启发式：检查开头和结尾）
    content = chunk.page_content
    if len(content) < 100:
        return True  # 太短的chunk可能需要扩展
    
    # 检查是否以完整句子结尾
    if not content.rstrip().endswith(('。', '！', '？', '.', '!', '?')):
        return True  # 可能被截断
    
    return False

