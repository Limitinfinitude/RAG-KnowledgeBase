"""非 Streamlit 入口上传适配：为 ingest_file 提供与 UploadedFile 兼容的接口。"""
from __future__ import annotations


class BytesUploadFile:
    """模拟 Streamlit UploadedFile（name + getbuffer）。"""

    __slots__ = ("name", "_data")

    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getbuffer(self):
        return memoryview(self._data)
