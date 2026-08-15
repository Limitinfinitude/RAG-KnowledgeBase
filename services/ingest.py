"""知识库入库：页面与其它入口统一从 services 引用。"""
from utils.file_loader import ingest_file, MAX_FILE_SIZE_BYTES

__all__ = ["ingest_file", "MAX_FILE_SIZE_BYTES"]
