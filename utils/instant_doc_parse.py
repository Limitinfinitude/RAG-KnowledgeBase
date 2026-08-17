"""即时文档：从上传字节解析纯文本，供 Web API 使用（不入库、不经向量库）。

解析统一走 utils/document_parsers，支持的扩展名与知识库上传保持一致。
"""
from __future__ import annotations

import os
import tempfile

from utils.document_parsers import SUPPORTED_EXTENSIONS, parse_file_to_documents

INSTANT_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
INSTANT_MAX_TEXT_CHARS = 100_000
INSTANT_ALLOWED_EXT = {"." + e for e in SUPPORTED_EXTENSIONS}


def parse_upload_bytes(filename: str, data: bytes) -> str:
    """
    解析上传文件为单一字符串。超长文本在调用方截断并报错。
    支持格式与知识库上传一致（pdf / docx / pptx / txt / md / csv / html / xlsx / xls）。
    """
    raw = filename or "unnamed"
    ext = os.path.splitext(raw.replace("\\", "/"))[1].lower()
    if ext == ".doc":
        raise ValueError("不支持老版 .doc 格式，请用 Word/WPS 另存为 .docx 后再上传")
    if ext not in INSTANT_ALLOWED_EXT:
        raise ValueError(f"不支持的格式，仅允许：{', '.join(sorted(INSTANT_ALLOWED_EXT))}")
    if len(data) > INSTANT_MAX_UPLOAD_BYTES:
        raise ValueError(f"文件超过 {INSTANT_MAX_UPLOAD_BYTES // (1024 * 1024)}MB 限制")

    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext, mode="wb") as tmp:
            tmp.write(data)
            temp_path = tmp.name

        docs = parse_file_to_documents(temp_path, raw)
        text = "\n\n".join(d.page_content for d in docs if d.page_content).strip()
        if not text:
            raise ValueError("未能从文件中提取文本")
        if len(text) > INSTANT_MAX_TEXT_CHARS:
            raise ValueError(f"提取的正文超过 {INSTANT_MAX_TEXT_CHARS:,} 个字符，请缩短或拆分文档")
        return text
    finally:
        if temp_path and os.path.isfile(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
