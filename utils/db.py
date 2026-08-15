# utils/db.py
import logging
import os
from langchain_community.vectorstores import FAISS

from utils.path_context import get_kb_dir

logger = logging.getLogger(__name__)


def get_vector_db(embeddings=None):
    """
    返回 FAISS 向量数据库实例。
    如果已有索引则加载，否则创建一个空的 FAISS 实例（允许首次启动）。
    """
    if embeddings is None:
        from utils.embedding import get_embeddings
        embeddings = get_embeddings()

    index_dir = os.path.join(get_kb_dir(), "faiss_index")
    index_file = os.path.join(index_dir, "index.faiss")

    # 如果已有索引，正常加载
    if os.path.exists(index_file):
        logger.info("[DB] 加载已有 FAISS 索引：%s", index_dir)
        return FAISS.load_local(
            folder_path=index_dir,
            embeddings=embeddings,
            allow_dangerous_deserialization=True
        )

    # 如果不存在，创建一个空的 FAISS 实例，并自动保存（为后续入库做准备）
    logger.info("[DB] 未找到索引，创建空的 FAISS 向量库：%s", index_dir)
    empty_db = FAISS.from_texts(
        texts=["初始空文档"],  # 必须至少有一个文本，否则 FAISS 会报错
        embedding=embeddings,
        metadatas=[{"source_file": "system", "note": "empty_init"}]
    )
    # 创建目录并保存
    os.makedirs(index_dir, exist_ok=True)
    empty_db.save_local(index_dir)
    return empty_db