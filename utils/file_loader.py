# utils/file_loader.py
import logging
import os
import tempfile
import traceback
from utils.document_parsers import parse_file_to_documents
from utils.path_context import get_kb_dir
from utils.document_preview import persist_original_from_temp
from utils.metadata_manager import MAX_FILE_SIZE_BYTES, add_document_metadata, update_chunks_count
from utils.logger import log_file_upload, log_error

logger = logging.getLogger(__name__)

__all__ = ["ingest_file", "MAX_FILE_SIZE_BYTES"]


def _finalize_ingest_metadata(
    uploaded_file,
    file_ext: str,
    category: str,
    description: str,
    chunks_count: int,
) -> None:
    if chunks_count <= 0:
        return
    file_size = len(uploaded_file.getbuffer())
    add_document_metadata(
        file_name=uploaded_file.name,
        file_size=file_size,
        file_type=file_ext.lstrip("."),
        category=category,
        description=description,
    )
    update_chunks_count(uploaded_file.name, chunks_count)
    try:
        log_file_upload(
            file_name=uploaded_file.name,
            file_size=file_size,
            chunks=chunks_count,
            category=category,
        )
    except Exception as e:
        logger.warning("记录上传日志失败: %s", e)


def ingest_file(uploaded_file, vector_db, category: str = "默认知识库", description: str = ""):
    """
    处理上传的文件并入库。
    大文件走流式：分段读入、单层 medium 切分、分批写入向量库，降低内存峰值。
    """
    from utils import ingest_streaming as ins

    temp_path = None
    try:
        file_size = len(uploaded_file.getbuffer())
        if file_size > MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"文件大小 {file_size / (1024*1024):.2f}MB 超过限制 {MAX_FILE_SIZE_BYTES / (1024*1024)}MB"
            )

        file_ext = os.path.splitext(uploaded_file.name)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext, mode="wb") as tmp:
            tmp.write(uploaded_file.getbuffer())
            temp_path = tmp.name

        persist_original_from_temp(temp_path, uploaded_file.name)

        on_disk = os.path.getsize(temp_path)
        use_stream = ins.should_use_streaming_ingest(on_disk)
        cat = category.strip() or "默认知识库"
        desc = description or ""

        # ---------- 流式入库（大文件）----------
        if use_stream and file_ext in (".txt", ".md"):
            enc = ins.detect_text_file_encoding(temp_path)
            sample = ins.read_text_head(temp_path, enc, 18000)
            summary = ins.make_rule_summary_from_sample(
                sample, uploaded_file.name, file_ext.lstrip(".")
            )
            n = ins.run_streaming_ingest(
                ins.iter_segments_text_file(temp_path, enc),
                uploaded_file.name,
                file_ext.lstrip("."),
                vector_db,
                on_disk,
                summary,
            )
            logger.info("[Ingest/stream] txt/md 入库 %d 块，文件：%s", n, uploaded_file.name)
            _finalize_ingest_metadata(uploaded_file, file_ext, cat, desc, n)
            return n

        if use_stream and file_ext == ".pdf":
            if ins.pdf_has_extractable_text(temp_path):
                sample = ins.read_pdf_text_sample(temp_path)
                summary = ins.make_rule_summary_from_sample(sample, uploaded_file.name, "pdf")
                n = ins.run_streaming_ingest(
                    ins.iter_segments_pdf_text(temp_path),
                    uploaded_file.name,
                    "pdf",
                    vector_db,
                    on_disk,
                    summary,
                )
            else:
                n = ins.run_streaming_ingest(
                    ins.iter_segments_pdf_ocr(temp_path),
                    uploaded_file.name,
                    "pdf",
                    vector_db,
                    on_disk,
                    None,
                )
            logger.info("[Ingest/stream] PDF 入库 %d 块，文件：%s", n, uploaded_file.name)
            _finalize_ingest_metadata(uploaded_file, file_ext, cat, desc, n)
            return n

        if use_stream and file_ext == ".docx":
            sample = ins.read_docx_sample(temp_path)
            summary = ins.make_rule_summary_from_sample(sample, uploaded_file.name, "docx")
            n = ins.run_streaming_ingest(
                ins.iter_segments_docx(temp_path),
                uploaded_file.name,
                "docx",
                vector_db,
                on_disk,
                summary,
            )
            logger.info("[Ingest/stream] DOCX 入库 %d 块，文件：%s", n, uploaded_file.name)
            _finalize_ingest_metadata(uploaded_file, file_ext, cat, desc, n)
            return n

        # ---------- 原有路径（较小文件）：全文进内存 + 多层级 smart chunk ----------
        docs = parse_file_to_documents(temp_path, uploaded_file.name)

        from utils.smart_chunker import smart_chunk_document

        full_text = "\n\n".join([doc.page_content for doc in docs])
        text_length = len(full_text)
        if text_length < 5000:
            length_factor = 0.8
        elif text_length > 50000:
            length_factor = 1.2
        else:
            length_factor = 1.0

        chunks, chunk_stats = smart_chunk_document(
            text=full_text,
            source_file=uploaded_file.name,
            file_type=file_ext.lstrip("."),
            use_llm_summary=False,
            doc_length_factor=length_factor,
        )

        logger.info("[SmartChunker] 分块统计: %s", chunk_stats)

        for chunk in chunks:
            if "source_file" not in chunk.metadata:
                chunk.metadata["source_file"] = uploaded_file.name
            if "file_type" not in chunk.metadata:
                chunk.metadata["file_type"] = file_ext.lstrip(".")

        if chunks:
            index_dir = os.path.join(get_kb_dir(), "faiss_index")
            os.makedirs(index_dir, exist_ok=True)
            bs = ins.EMBED_ADD_BATCH_SIZE
            from utils.faiss_write_lock import faiss_write_lock

            with faiss_write_lock():
                for i in range(0, len(chunks), bs):
                    vector_db.add_documents(chunks[i : i + bs])
                vector_db.save_local(index_dir)
            logger.info("成功入库 %d 个文本块，文件：%s", len(chunks), uploaded_file.name)
            _finalize_ingest_metadata(uploaded_file, file_ext, cat, desc, len(chunks))

        return len(chunks)

    except Exception as e:
        error_msg = f"文件处理失败 {uploaded_file.name}: {str(e)}"
        logger.exception(error_msg)
        log_error("file_processing", error_msg, {"file_name": uploaded_file.name})
        raise

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception as e:
                logger.warning("删除临时文件失败 %s: %s", temp_path, e)
