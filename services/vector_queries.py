"""与向量库相关的只读查询（无 Streamlit）。"""
from typing import Any, List


def list_indexed_source_files(
    vector_db: Any,
    k: int = 10000,
    *,
    exclude: frozenset = frozenset({"system"}),
) -> List[str]:
    """
    通过空查询拉取一批文档，汇总 source_file（用于侧边栏「检索范围」等）。
    """
    try:
        dummy_results = vector_db.similarity_search("", k=k)
        names = {
            doc.metadata.get("source_file", "未知")
            for doc in dummy_results
            if doc.metadata.get("source_file") not in exclude
            and doc.metadata.get("note") != "empty_init"
        }
        return sorted(names)
    except Exception:
        return []
