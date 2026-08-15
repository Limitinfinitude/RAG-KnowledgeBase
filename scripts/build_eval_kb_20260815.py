"""将 eval_corpus/ 下的评测文档入库到指定知识库用户，用于构建检索评测集。

用法（项目根目录）::

    python scripts/build_eval_kb_20260815.py --user 99

默认将 eval_corpus/ 下所有 .txt/.md 入库到 --user 用户的知识库。
"""
from __future__ import annotations

import argparse
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

CORPUS_DIR = os.path.join(_PROJECT_ROOT, "eval_corpus")


def main() -> None:
    parser = argparse.ArgumentParser(description="构建检索评测知识库")
    parser.add_argument("--user", type=int, default=99, help="目标知识库用户 id（默认 99）")
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

    files = [f for f in os.listdir(CORPUS_DIR) if f.lower().endswith((".txt", ".md"))]
    if not files:
        print("[ERROR] 语料目录为空")
        sys.exit(1)

    from io import BytesIO

    total = 0
    for fname in sorted(files):
        path = os.path.join(CORPUS_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            data = f.read()
        buf = BytesIO(data.encode("utf-8"))
        # 用一个简单的文件对象包装，满足 ingest_file 的 .name/.getbuffer 接口
        class _F:
            def __init__(self, name, raw):
                self.name = name
                self._raw = raw

            def getbuffer(self):
                return self._raw

        wrapped = _F(fname, data.encode("utf-8"))
        n = ingest_file(wrapped, vdb, category="评测语料", description="检索评测语料")
        total += n
        print(f"入库 {fname}: {n} 块")

    print(f"\n完成，共入库 {total} 块到用户 {args.user} 知识库。")


if __name__ == "__main__":
    main()
