"""将 eval_corpus/ 下的评测文档入库到指定知识库用户，用于构建检索评测集。

用法（项目根目录）::

    python scripts/build_eval_kb_20260815.py --user 98

支持格式：txt / md / pdf / docx / xlsx（二进制格式按原始字节读取，走项目内置解析）。
"""
from __future__ import annotations

import argparse
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

CORPUS_DIR = os.path.join(_PROJECT_ROOT, "eval_corpus")

_TEXT_EXTS = {".txt", ".md"}
# 支持格式与上传白名单一致（document_parsers 注册表）
from utils.document_parsers import SUPPORTED_EXTENSIONS as _SUPPORTED_EXTS
_SUPPORTED_EXTS = {"." + e for e in _SUPPORTED_EXTS}


class _BytesUploadFile:
    """最小文件包装：满足 ingest_file 的 .name/.getbuffer 接口。"""

    def __init__(self, name: str, raw: bytes):
        self.name = name
        self._raw = raw

    def getbuffer(self):
        return self._raw


def main() -> None:
    parser = argparse.ArgumentParser(description="构建检索评测知识库")
    parser.add_argument("--user", type=int, default=98, help="目标知识库用户 id（默认 98）")
    args = parser.parse_args()

    from utils.path_context import set_user_kb_context
    from utils.db import get_vector_db
    from utils.file_loader import ingest_file
    from utils.embedding import get_embeddings

    set_user_kb_context(args.user)
    embeddings = get_embeddings()
    vdb = get_vector_db(embeddings)

    if not os.path.isdir(CORPUS_DIR):
        print(f"[ERROR] 语料目录不存在: {CORPUS_DIR}")
        sys.exit(1)

    files = [f for f in os.listdir(CORPUS_DIR)
             if os.path.splitext(f)[1].lower() in _SUPPORTED_EXTS
             and not f.startswith("语料来源说明")]
    if not files:
        print("[ERROR] 语料目录为空")
        sys.exit(1)

    total = 0
    for fname in sorted(files):
        path = os.path.join(CORPUS_DIR, fname)
        ext = os.path.splitext(fname)[1].lower()
        # 文本格式按 UTF-8 读；二进制格式（pdf/docx/xlsx）按原始字节读
        if ext in _TEXT_EXTS:
            with open(path, "rb") as f:
                raw = f.read()
        else:
            with open(path, "rb") as f:
                raw = f.read()
        wrapped = _BytesUploadFile(fname, raw)
        try:
            n = ingest_file(wrapped, vdb, category="评测语料", description="检索评测语料")
            total += n
            print(f"入库 {fname}: {n} 块")
        except Exception as e:
            print(f"[WARN] 入库 {fname} 失败: {e}")

    print(f"\n完成，共入库 {total} 块到用户 {args.user} 知识库。")


if __name__ == "__main__":
    main()
