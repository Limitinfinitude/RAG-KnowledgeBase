"""检索质量离线评测：计算向量检索与混合检索的 Recall@k。

用法（项目根目录）::

    python scripts/eval_retrieval.py --user 1 --k 5

说明：
- 通过 path_context 绑定指定用户的 knowledge_db（默认用户 1）。
- 评测集为「查询 → 相关文档文件名」的标注列表，见 EVAL_SET。
- 输出向量 / 混合两种模式在各 k 下的 Recall@k 对比，供调参对比。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List, Tuple

# 项目根目录加入 sys.path，确保可 import 项目模块
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# 评测集：query -> 相关文档文件名集合（用户 1 知识库：刑法、劳动合同法、西游记、三国演义）
# 只保留在对应知识库中真实存在、且归属明确的标注。
EVAL_SET: List[Tuple[str, List[str]]] = [
    ("盗窃罪的量刑标准是什么", ["中华人民共和国刑法_20201226.docx"]),
    ("故意伤害罪如何处罚", ["中华人民共和国刑法_20201226.docx"]),
    ("劳动合同试用期最长多久", ["中华人民共和国劳动合同法_20121228.docx"]),
    ("解除劳动合同需要什么程序", ["中华人民共和国劳动合同法_20121228.docx"]),
    ("孙悟空大闹天宫的情节", ["西游记.txt"]),
    ("唐僧师徒取经路上遇到哪些妖怪", ["西游记.txt"]),
    ("关羽过五关斩六将", ["三国演义.txt"]),
    ("诸葛亮草船借箭的故事", ["三国演义.txt"]),
]


def _recall_at_k(retrieved_files: List[str], relevant: List[str], k: int) -> float:
    """计算 Recall@k：前 k 个检索结果中命中相关文档的比例。"""
    if not relevant:
        return 0.0
    top_k = retrieved_files[:k]
    hits = sum(1 for f in relevant if f in top_k)
    return hits / len(relevant)


def _run_search(vector_db, query: str, k: int, search_mode: str):
    """执行一次检索，返回 (doc_file_names, scores)。"""
    if search_mode == "hybrid":
        from utils.hybrid_search import load_bm25_index, hybrid_search, rebuild_bm25_index

        bm25_index, bm25_docs = load_bm25_index()
        if bm25_index is None or bm25_docs is None:
            bm25_index, bm25_docs = rebuild_bm25_index(vector_db)
        if bm25_index and bm25_docs:
            results = hybrid_search(
                query=query,
                vector_db=vector_db,
                bm25_index=bm25_index,
                bm25_docs=bm25_docs,
                top_k=k,
                selected_kb="全部知识库",
            )
        else:
            results = vector_db.similarity_search_with_score(query, k=k)
            results = [(doc, 1 / (1 + score)) for doc, score in results]
    else:
        results = vector_db.similarity_search_with_score(query, k=k)
        results = [(doc, 1 / (1 + score)) for doc, score in results]

    files = [doc.metadata.get("source_file", "") for doc, _ in results]
    scores = [round(s, 4) for _, s in results]
    return files, scores


def _load_vector_db(user_id: int):
    """加载指定用户的向量库（绑定 path_context）。"""
    from utils.path_context import set_user_kb_context
    from utils.db import get_vector_db

    set_user_kb_context(user_id)
    return get_vector_db()


def main() -> None:
    parser = argparse.ArgumentParser(description="检索质量离线评测（Recall@k）")
    parser.add_argument("--user", type=int, default=1, help="知识库所属用户 id（默认 1）")
    parser.add_argument("--k", type=int, default=5, help="Recall@k 的 k 值（默认 5）")
    parser.add_argument("--mode", choices=["vector", "hybrid", "both"], default="both",
                        help="评测的检索模式（默认 both）")
    args = parser.parse_args()

    print(f"\n=== 检索质量评测：用户 {args.user} 知识库，k={args.k} ===\n")

    try:
        vector_db = _load_vector_db(args.user)
    except Exception as e:
        print(f"[ERROR] 加载向量库失败：{e}")
        print("请确认知识库存在且依赖已安装（faiss-cpu、sentence-transformers 等）。")
        sys.exit(1)

    modes = [args.mode] if args.mode != "both" else ["vector", "hybrid"]

    for mode in modes:
        print(f"--- 检索模式：{mode} ---")
        total = 0.0
        rows = []
        for query, relevant in EVAL_SET:
            t0 = time.perf_counter()
            try:
                files, scores = _run_search(vector_db, query, args.k, mode)
            except Exception as e:
                print(f"  [ERROR] query「{query}」检索失败：{e}")
                continue
            elapsed = (time.perf_counter() - t0) * 1000
            recall = _recall_at_k(files, relevant, args.k)
            total += recall
            rows.append((query, files[:args.k], scores, recall, elapsed))

        # 打印每个 query 的详细结果
        for query, files, scores, recall, elapsed in rows:
            hit = "✅" if recall > 0 else "❌"
            print(f"  {hit} {query}")
            print(f"     Recall@{args.k}={recall:.2f} | 命中: {[f for f in files if f]} | 耗时 {elapsed:.0f}ms")

        avg = total / len(rows) if rows else 0.0
        print(f"  >>> 平均 Recall@{args.k} = {avg:.4f}\n")

    print("=== 评测完成 ===\n")


if __name__ == "__main__":
    main()
