# utils/document_deleter.py
"""
文档删除：从 FAISS 中移除指定 source_file 的全部向量块。

旧实现用 similarity_search("", k=30000) + FAISS.from_texts 全量重嵌入，大库会极慢且占满 CPU/内存，
且 k=30000 会漏删。现优先用 LangChain FAISS.delete（faiss remove_ids），失败时再回退为「仅 reconstruct +
from_embeddings」，避免调用 embedding API。
"""
import logging
import os
import shutil
from typing import List, Tuple

logger = logging.getLogger(__name__)

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from services.vector_store import load_embeddings_only
from utils.document_preview import ORIGINAL_FILES_SUBDIR
from utils.logger import log_error, log_file_delete
from utils.metadata_manager import delete_document_metadata
from utils.path_context import get_kb_dir


def _docstore_ids_for_file(vector_db, file_name: str) -> List[str]:
    """遍历索引映射，收集 metadata.source_file == file_name 的 docstore id。"""
    out: List[str] = []
    for _idx, doc_id in sorted(vector_db.index_to_docstore_id.items()):
        doc = vector_db.docstore.search(doc_id)
        if isinstance(doc, Document) and doc.metadata.get("source_file") == file_name:
            out.append(doc_id)
    return out


def _write_empty_system_index(embeddings, index_dir: str) -> None:
    if os.path.exists(index_dir):
        shutil.rmtree(index_dir)
    empty_db = FAISS.from_texts(
        texts=["初始空文档"],
        embedding=embeddings,
        metadatas=[{"source_file": "system", "note": "empty_init"}],
    )
    os.makedirs(index_dir, exist_ok=True)
    empty_db.save_local(index_dir)


def _rebuild_drop_file_no_reembed(
    vector_db,
    file_name: str,
    embeddings,
    index_dir: str,
) -> Tuple[bool, int]:
    """
    旧版 faiss 或不支持 remove_ids 时的回退：用 reconstruct 取出向量，from_embeddings 重建，不调用 embed。
    语义与旧实现一致：重建时丢弃 source_file 为 system/None 的块（与原 similarity_search 过滤一致）。
    """
    deleted_count = 0
    keep_rows: List[Tuple[str, List[float], dict]] = []

    for i, doc_id in sorted(vector_db.index_to_docstore_id.items()):
        doc = vector_db.docstore.search(doc_id)
        if not isinstance(doc, Document):
            continue
        sf = doc.metadata.get("source_file")
        if sf == file_name:
            deleted_count += 1
            continue
        if sf in ("system", None):
            continue
        vec = vector_db.index.reconstruct(int(i))
        keep_rows.append((doc.page_content, vec.astype("float32").tolist(), doc.metadata))

    if deleted_count == 0:
        return False, 0

    if not keep_rows:
        _write_empty_system_index(embeddings, index_dir)
        return True, deleted_count

    pairs = [(t, v) for t, v, _m in keep_rows]
    metas = [m for _t, _v, m in keep_rows]
    new_db = FAISS.from_embeddings(
        text_embeddings=pairs,
        embedding=embeddings,
        metadatas=metas,
        normalize_L2=vector_db._normalize_L2,
        distance_strategy=vector_db.distance_strategy,
    )
    os.makedirs(index_dir, exist_ok=True)
    new_db.save_local(index_dir)
    return True, deleted_count


def delete_document_from_vector_db(file_name: str, vector_db, embeddings=None):
    """
    从向量库中删除指定文档的全部 chunks，并更新元数据、可选原文文件。

    :return: (成功标志, 删除的 chunk 数)
    """
    if embeddings is None:
        embeddings = load_embeddings_only()

    index_dir = os.path.join(get_kb_dir(), "faiss_index")
    ids_to_delete = _docstore_ids_for_file(vector_db, file_name)
    deleted_count = len(ids_to_delete)

    if deleted_count == 0:
        return False, 0

    try:
        vector_db.delete(ids_to_delete)
        if vector_db.index.ntotal == 0:
            _write_empty_system_index(embeddings, index_dir)
        else:
            os.makedirs(index_dir, exist_ok=True)
            vector_db.save_local(index_dir)
    except Exception as e:
        err = f"FAISS.delete 失败，回退无重嵌入重建: {e}"
        logger.warning("%s", err)
        try:
            from utils.db import get_vector_db

            vector_db = get_vector_db(embeddings)
            ok, deleted_count = _rebuild_drop_file_no_reembed(
                vector_db, file_name, embeddings, index_dir
            )
            if not ok:
                return False, 0
        except Exception as e2:
            log_error(
                "document_delete",
                f"删除文档失败: {e2}",
                {"file_name": file_name},
            )
            import traceback

            traceback.print_exc()
            return False, 0

    try:
        delete_document_metadata(file_name)
    except Exception as e:
        logger.warning("删除元数据失败: %s", e)

    try:
        obase = os.path.basename((file_name or "").replace("\\", "/"))
        opath = os.path.join(get_kb_dir(), ORIGINAL_FILES_SUBDIR, obase)
        if obase and os.path.isfile(opath):
            os.unlink(opath)
    except OSError:
        pass

    try:
        log_file_delete(file_name=file_name, chunks_deleted=deleted_count)
    except Exception as e:
        logger.warning("记录删除日志失败: %s", e)

    return True, deleted_count
