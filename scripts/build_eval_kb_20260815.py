"""将评测语料入库到指定知识库用户，用于构建检索评测集。

用法（项目根目录）::

    python scripts/build_eval_kb_20260815.py --user 99 --corpus eval_corpus_v2 --reset

支持格式：document_parsers 白名单（txt/md/html/csv/docx/xlsx/pptx/pdf/图片等）。
--reset 先清空该用户知识库（FAISS + BM25 + 元数据）再整体重建。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

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


def reset_kb(user_id: int) -> None:
    """清空用户知识库（含历史版本 BM25 索引），保证评测基线干净。"""
    from utils.path_context import get_kb_dir

    kb = get_kb_dir()
    for entry in ("faiss_index", "original_files"):
        p = os.path.join(kb, entry)
        if os.path.isdir(p):
            shutil.rmtree(p)
    if os.path.isfile(os.path.join(kb, "documents_metadata.json")):
        os.remove(os.path.join(kb, "documents_metadata.json"))
    for f in os.listdir(kb):
        if f.startswith("bm25_index") or f.startswith("bm25_docs"):
            os.remove(os.path.join(kb, f))
    print(f"[reset] 已清空用户 {user_id} 知识库: {kb}")


def main() -> None:
    parser = argparse.ArgumentParser(description="构建检索评测知识库")
    parser.add_argument("--user", type=int, default=99, help="目标知识库用户 id（默认 99）")
    parser.add_argument(
        "--corpus",
        default="eval_corpus_v2",
        help="语料目录名（项目根相对路径；默认 eval_corpus_v2，旧基准用 eval_corpus）",
    )
    parser.add_argument(
        "--reset", action="store_true", help="入库前清空该用户知识库（bge-m3 与旧索引不可混用，务必重建）"
    )
    args = parser.parse_args()

    corpus_dir = os.path.join(_PROJECT_ROOT, args.corpus)

    from utils.path_context import set_user_kb_context
    from utils.db import get_vector_db
    from utils.file_loader import ingest_file
    from utils.embedding import get_embeddings

    set_user_kb_context(args.user)
    if args.reset:
        reset_kb(args.user)
    embeddings = get_embeddings()
    vdb = get_vector_db(embeddings)

    if not os.path.isdir(corpus_dir):
        print(f"[ERROR] 语料目录不存在: {corpus_dir}")
        sys.exit(1)

    files = [f for f in os.listdir(corpus_dir)
             if os.path.splitext(f)[1].lower() in _SUPPORTED_EXTS
             and not f.startswith("语料来源说明")]
    if not files:
        print("[ERROR] 语料目录为空")
        sys.exit(1)

    total = 0
    for fname in sorted(files):
        path = os.path.join(corpus_dir, fname)
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
