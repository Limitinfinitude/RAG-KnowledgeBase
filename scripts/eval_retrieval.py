"""检索质量离线评测：Recall@k + nDCG@k，向量/混合对比。

用法（项目根目录）::

    python scripts/eval_retrieval.py --user 99 --k 5 --mode both

说明：
- 通过 path_context 绑定指定用户的 knowledge_db。
- 评测集为「查询 → 相关文档文件名（可多个，按相关度降序）」的标注。
- 相关文档为空列表 = 负样本（期望检索不到该语义，用于测误召回）。
- 输出 Recall@k、nDCG@k、MRR，支持向量 / 混合两种模式对比。
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from typing import List, Dict, Tuple

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# 评测集：query -> 相关文档文件名（按相关度降序，越靠前越相关）
# 空列表 = 负样本
# 语料：AI Agent 书（chapter1-5），主题同域、词汇大量重叠，考验细粒度区分
EVAL_SET: List[Tuple[str, List[str]]] = [
    # —— 各章独有内容（每 query 唯一归属）——
    ("ReAct 循环是什么", ["chapter1_Agent入门_20260815.md"]),
    ("Harness 工程五个功能的核心原则", ["chapter1_Agent入门_20260815.md"]),
    ("工作流模式与自主 Agent 模式如何选择", ["chapter1_Agent入门_20260815.md"]),
    ("KV Cache 的原理与约束", ["chapter2_上下文工程_20260815.md"]),
    ("消息的四种角色", ["chapter2_上下文工程_20260815.md"]),
    ("系统提示词的组织方式", ["chapter2_上下文工程_20260815.md"]),
    ("用户记忆的四种存储格式", ["chapter3_用户记忆与知识库_20260815.md"]),
    ("记忆的层次结构", ["chapter3_用户记忆与知识库_20260815.md"]),
    ("RAPTOR 与 GraphRAG 的区别", ["chapter3_用户记忆与知识库_20260815.md"]),
    ("MCP 协议如何统一工具生态", ["chapter4_工具_20260815.md"]),
    ("工具的分类有哪几类", ["chapter4_工具_20260815.md"]),
    ("事件驱动的异步 Agent 架构", ["chapter4_工具_20260815.md"]),
    ("Coding Agent 的整体流程", ["chapter5_CodingAgent与通用Agent_20260815.md"]),
    ("代码作为通用 Agent 元能力的六个方向", ["chapter5_CodingAgent与通用Agent_20260815.md"]),
    # —— 词汇陷阱：关键词跨章出现，考察能否定位到正确章节 ——
    ("为什么说上下文是 Agent 的眼睛", ["chapter1_Agent入门_20260815.md"]),
    ("什么是上下文工程", ["chapter2_上下文工程_20260815.md"]),
    ("用户记忆和知识库有什么区别", ["chapter3_用户记忆与知识库_20260815.md"]),
    ("工具粒度如何权衡", ["chapter4_工具_20260815.md"]),
    # —— 多相关样本：主题跨章 ——
    ("如何防止 Agent 陷入无限循环", [
        "chapter1_Agent入门_20260815.md",
        "chapter2_上下文工程_20260815.md",
    ]),
    # —— 负样本（书中无对应内容，期望不召回）——
    ("红烧肉怎么做", []),
    ("世界杯决赛的比赛规则", []),
    ("如何办理房产过户手续", []),
]


def _recall_at_k(retrieved: List[str], relevant: List[str], k: int) -> float:
    if not relevant:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for f in relevant if f in top_k)
    return hits / len(relevant)


def _dcg_at_k(retrieved: List[str], relevant: List[str], k: int) -> float:
    """DCG：相关文档按其位置（idcg 用标注顺序）计入折扣增益。"""
    dcg = 0.0
    for i, f in enumerate(retrieved[:k], start=1):
        if f in relevant:
            dcg += 1.0 / math.log2(i + 1)
    return dcg


def _ideal_dcg_at_k(relevant: List[str], k: int) -> float:
    n = min(len(relevant), k)
    return sum(1.0 / math.log2(i + 1) for i in range(1, n + 1))


def _ndcg_at_k(retrieved: List[str], relevant: List[str], k: int) -> float:
    ideal = _ideal_dcg_at_k(relevant, k)
    if ideal == 0:
        return 0.0
    return _dcg_at_k(retrieved, relevant, k) / ideal


def _mrr(retrieved: List[str], relevant: List[str]) -> float:
    for i, f in enumerate(retrieved, start=1):
        if f in relevant:
            return 1.0 / i
    return 0.0


def _run_search(vector_db, query: str, k: int, search_mode: str):
    if search_mode == "hybrid":
        from utils.hybrid_search import load_bm25_index, hybrid_search, rebuild_bm25_index

        bm25_index, bm25_docs = load_bm25_index()
        if bm25_index is None or bm25_docs is None:
            bm25_index, bm25_docs = rebuild_bm25_index(vector_db)
        if bm25_index and bm25_docs:
            results = hybrid_search(
                query=query, vector_db=vector_db, bm25_index=bm25_index,
                bm25_docs=bm25_docs, top_k=k, selected_kb="全部知识库",
            )
        else:
            results = vector_db.similarity_search_with_score(query, k=k)
            results = [(doc, 1 / (1 + score)) for doc, score in results]
    else:
        results = vector_db.similarity_search_with_score(query, k=k)
        results = [(doc, 1 / (1 + score)) for doc, score in results]

    files = [doc.metadata.get("source_file", "") for doc, _ in results]
    return files


def _load_vector_db(user_id: int):
    from utils.path_context import set_user_kb_context
    from utils.db import get_vector_db

    set_user_kb_context(user_id)
    return get_vector_db()


def main() -> None:
    parser = argparse.ArgumentParser(description="检索质量离线评测（Recall@k / nDCG@k / MRR）")
    parser.add_argument("--user", type=int, default=98, help="知识库用户 id（默认 98 书本章节评测集）")
    parser.add_argument("--k", type=int, default=5, help="k 值（默认 5）")
    parser.add_argument("--mode", choices=["vector", "hybrid", "both"], default="both")
    args = parser.parse_args()

    print(f"\n=== 检索质量评测：用户 {args.user}，k={args.k}，样本 {len(EVAL_SET)} 条 ===\n")

    vector_db = _load_vector_db(args.user)

    modes = [args.mode] if args.mode != "both" else ["vector", "hybrid"]
    summary: Dict[str, Dict[str, float]] = {}

    for mode in modes:
        print(f"--- 检索模式：{mode} ---")
        recalls, ndcgs, mrrs = [], [], []
        for query, relevant in EVAL_SET:
            is_neg = not relevant
            files = _run_search(vector_db, query, args.k, mode)
            r = _recall_at_k(files, relevant, args.k)
            n = _ndcg_at_k(files, relevant, args.k)
            m = _mrr(files, relevant)
            recalls.append(r)
            ndcgs.append(n)
            mrrs.append(m)
            tag = "【负样本】" if is_neg else ""
            hit = "✅" if (r > 0 and not is_neg) else ("⚠️(应无命中)" if is_neg and files else "➖")
            print(f"  {hit} {tag}{query}")
            print(f"     Recall@{args.k}={r:.2f} nDCG@{args.k}={n:.2f} MRR={m:.2f} 命中={[f for f in files[:3] if f]}")

        avg_r = sum(recalls) / len(recalls)
        avg_n = sum(ndcgs) / len(ndcgs)
        avg_m = sum(mrrs) / len(mrrs)
        summary[mode] = {"recall": avg_r, "ndcg": avg_n, "mrr": avg_m}
        print(f"  >>> 平均 Recall@{args.k}={avg_r:.4f} | nDCG@{args.k}={avg_n:.4f} | MRR={avg_m:.4f}\n")

    if len(modes) == 2:
        print("=== 模式对比 ===")
        for metric in ("recall", "ndcg", "mrr"):
            v = summary["vector"][metric]
            h = summary["hybrid"][metric]
            print(f"  {metric.upper():8s} 向量={v:.4f}  混合={h:.4f}")

    print("\n=== 评测完成 ===\n")


if __name__ == "__main__":
    main()
