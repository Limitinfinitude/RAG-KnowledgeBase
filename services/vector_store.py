from typing import Tuple, Any

from utils.embedding import get_embeddings
from utils.db import get_vector_db


def load_embeddings_only() -> Any:
    """仅加载嵌入模型（删除重建索引等场景）。"""
    return get_embeddings()


def load_embeddings_and_vector_db() -> Tuple[Any, Any]:
    """加载嵌入模型与 FAISS 向量库（供页面 cache_resource 包装）。"""
    embeddings = get_embeddings()
    vector_db = get_vector_db(embeddings)
    return vector_db, embeddings
