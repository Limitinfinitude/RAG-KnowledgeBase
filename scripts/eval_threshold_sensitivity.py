# -*- coding: utf-8 -*-
"""重排阈值敏感性分析：每查询只调一次云端重排，离线重放多个 SIMILARITY_THRESHOLD。

对每个评测查询：hybrid 宽召回 → 重排取全量分数 → 记录 max 分。
正样本存活率 = max≥阈值的正样本占比；负样本泄漏率 = max≥阈值的负样本占比。
Balanced = 2*存活*(1-泄漏)/(存活+1-泄漏)。
用法：conda run -n rag_demo python -X utf8 scripts/eval_threshold_sensitivity.py
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.eval_retrieval import _load_eval_set, _load_vector_db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, default=99)
    ap.add_argument("--set", dest="eval_set", choices=["v2", "legacy"], default="v2")
    ap.add_argument("--thresholds", default="0.2,0.25,0.3,0.35,0.4,0.5")
    args = ap.parse_args()
    ths = [float(x) for x in args.thresholds.split(",")]

    items = _load_eval_set(args.eval_set, None, None)
    pos = [it["query"] for it in items if it["kind"] == "positive"]
    neg = [it["query"] for it in items if it["kind"] == "negative"]

    from utils.hybrid_search import load_bm25_index, rebuild_bm25_index, hybrid_search
    from utils.reranker import get_cached_reranker, rerank_documents

    vector_db = _load_vector_db(args.user)
    bm25_index, bm25_docs = load_bm25_index()
    if bm25_index is None or bm25_docs is None:
        bm25_index, bm25_docs = rebuild_bm25_index(vector_db)
    reranker = get_cached_reranker()

    def max_score(query: str) -> float:
        results = hybrid_search(
            query=query, vector_db=vector_db, bm25_index=bm25_index,
            bm25_docs=bm25_docs, top_k=24, selected_kb="全部知识库",
        ) if bm25_index and bm25_docs else []
        if not results:
            results = [(d, 1 / (1 + s)) for d, s in vector_db.similarity_search_with_score(query, k=24)]
        if not results:
            return 0.0
        scored = rerank_documents(
            query=query, documents=[d for d, _ in results],
            reranker=reranker, top_k=10, reranker_type="cloud_or_local",
        )
        return max((sc for _, sc in scored), default=0.0)

    print(f"重放阈值分析：正 {len(pos)} / 负 {len(neg)}，阈值 {ths}")
    pos_scores, neg_scores = [], []
    for i, q in enumerate(pos, 1):
        pos_scores.append(max_score(q))
        if i % 50 == 0:
            print(f"  正样本 {i}/{len(pos)}")
    for i, q in enumerate(neg, 1):
        neg_scores.append(max_score(q))
        if i % 20 == 0:
            print(f"  负样本 {i}/{len(neg)}")

    print("\n阈值    正样本存活   负样本泄漏   Balanced")
    for th in ths:
        surv = sum(1 for s in pos_scores if s >= th) / len(pos_scores)
        leak = sum(1 for s in neg_scores if s >= th) / len(neg_scores)
        denom = surv + (1 - leak)
        bal = 2 * surv * (1 - leak) / denom if denom > 0 else 0.0
        print(f"{th:.2f}    {surv:>8.2%}   {leak:>8.2%}   {bal:.4f}")
    ps = sorted(pos_scores)
    ns = sorted(neg_scores)
    print(f"\n正样本 max 分数: p5={ps[int(0.05*len(ps))]:.3f} p25={ps[len(ps)//4]:.3f} "
          f"median={ps[len(ps)//2]:.3f} p75={ps[int(0.75*len(ps))]:.3f}")
    print(f"负样本 max 分数: p75={ns[int(0.75*len(ns))]:.3f} p95={ns[int(0.95*len(ns))]:.3f} "
          f"max={ns[-1]:.3f}")


if __name__ == "__main__":
    main()
