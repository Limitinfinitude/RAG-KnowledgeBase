# -*- coding: utf-8 -*-
"""端到端 RAGAS 风格评测（2026-08-19 v2）。

指标：
  - Faithfulness：回答论断被检索资料支持的比例（LLM judge）
  - Answer Relevancy：回答切题度 0-10
  - Context Precision：检索资料对问题的有用度 0-10
  - Answer Correctness：与人工/权威 ground truth 答案的要点覆盖 0-10（仅有 answer_gt 的样本）
  - Context Recall：ground truth 要点被检索上下文覆盖 0-10（仅有 answer_gt 的样本）
  - 拒答正确性：负样本回答是否承认无资料 0-10
  - 延迟：检索 / 生成 p50、p90（毫秒）

抽样：v2 集合按来源分层抽正样本（--sample，默认 80），负样本取陷阱类（--negative-n，默认 20）。
用法：conda run -n rag_demo python -X utf8 scripts/eval_e2e_ragas_style.py --sample 80
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys
import time
from typing import Dict, List, Tuple

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _load_items(which: str) -> List[dict]:
    if which == "legacy":
        from scripts.eval_retrieval import EVAL_SET

        return [
            {"query": q, "relevant_files": list(r), "kind": "positive" if r else "negative",
             "source": "legacy", "answer_gt": None, "passage_gt": None}
            for q, r in EVAL_SET
        ]
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "EVAL_SET_V2.json")
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def _retrieve_context(vector_db, query: str, k: int, reranker) -> Tuple[str, List[str], float]:
    """生产形态检索：hybrid + 重排 + finalize（与 /api/chat 一致）。返回 (上下文, 文件, 耗时秒)。"""
    from services.retrieval import retrieve_for_rag
    from services.ui_sink import RetrievalUISink

    t0 = time.perf_counter()
    ret = retrieve_for_rag(
        vector_db=vector_db,
        query=query,
        selected_kb="全部知识库",
        k=k,
        search_mode="hybrid",
        enable_reranker=True,
        reranker=reranker,
        sink=RetrievalUISink.noop(),
    )
    files = [item["file"] for item in ret.evidence_sources]
    return ret.numbered_context, files, time.perf_counter() - t0


_QA_PROMPT = """你是知识库问答助手。仅依据下面的编号资料回答问题；资料中没有的内容不要编造，宁可说明资料中无相关内容。回答末尾标注引用的来源编号（如 [来源1]）。

资料：
{context}

问题：{question}

回答："""


def _generate_answer(llm, query: str, context: str) -> str:
    if not context.strip():
        return "（未检索到相关资料，无法回答）"
    msg = _QA_PROMPT.format(context=context, question=query)
    resp = llm.invoke(msg)
    return (resp.content or "").strip()


def _judge(llm, prompt: str) -> str:
    resp = llm.invoke(prompt)
    return (resp.content or "").strip()


_FAITH_PROMPT = """判断下面的回答中有多少论断被资料支持。

资料：
{context}

回答：{answer}

只输出 JSON：{{"supported": 被支持的论断数, "total": 论断总数}}（total 为 0 时 supported 填 0）"""

_RELEV_PROMPT = """评估回答对问题的相关度。

问题：{question}
回答：{answer}

只输出 0-10 的整数：10=完全切题且信息充分，5=部分切题，0=答非所问或无信息。只输出数字。"""

_CTX_PROMPT = """评估下面资料对回答问题的有用度。

问题：{question}
资料（截断）：{context}

只输出 0-10 的整数：10=资料直接包含答案，5=部分相关，0=完全无关。只输出数字。"""

_CORRECT_PROMPT = """对照标准答案评估模型回答的正确性。

问题：{question}
标准答案：{gt}
模型回答：{answer}

评分标准：10=要点全部正确且无错误信息，7-9=主要要点正确但欠完整或含冗余，4-6=部分正确部分缺失或含不准表述，1-3=大部分错误，0=完全错误。只输出 0-10 的整数。"""

_CTXRECALL_PROMPT = """评估检索资料是否覆盖了标准答案的要点（Context Recall）。

问题：{question}
标准答案要点：{gt}
检索资料（截断）：{context}

评分标准：10=答案所有要点都能在资料中找到，5=覆盖一半左右，0=资料完全不包含答案要点。只输出 0-10 的整数。"""

_REFUSAL_PROMPT = """知识库中并没有与问题对应的资料。评估这个回答是否正确地承认了「资料中无相关内容」而非编造答案。

问题：{question}
回答：{answer}

只输出 0-10 的整数：9-10=明确承认无资料，0-4=编造了答案，5-8=模糊。只输出数字。"""


def _parse_int(text: str, default: int = -1) -> int:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else default


def _parse_faith(text: str) -> Tuple[int, int]:
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        obj = json.loads(text[start:end])
        return int(obj.get("supported", 0)), int(obj.get("total", 0))
    except Exception:
        return -1, -1


def _pct(xs: List[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


def main() -> None:
    parser = argparse.ArgumentParser(description="端到端 RAGAS 风格评测（v2）")
    parser.add_argument("--user", type=int, default=99)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--set", dest="eval_set", choices=["v2", "legacy"], default="v2")
    parser.add_argument("--sample", type=int, default=80, help="正样本抽样数（按来源分层）")
    parser.add_argument("--negative-n", type=int, default=20, help="陷阱负样本数")
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()

    from utils.path_context import set_user_kb_context
    from utils.db import get_vector_db
    from utils.reranker import get_cached_reranker
    from services.llm_factory import build_chat_llm

    set_user_kb_context(args.user)
    vector_db = get_vector_db()
    reranker = get_cached_reranker()
    llm = build_chat_llm(0.0)

    rng = random.Random(args.seed)
    items = _load_items(args.eval_set)
    positives = [it for it in items if it["kind"] == "positive"]
    negatives = [it for it in items if it["kind"] == "negative" and it.get("subtype") == "trap"]
    if len(negatives) < args.negative_n:  # legacy 集没有 subtype 标注，退回全部负样本
        negatives = [it for it in items if it["kind"] == "negative"]

    # 按来源分层均匀抽样（覆盖五个来源，含无 answer_gt 的来源也参与分层）
    by_src: Dict[str, List[dict]] = {}
    for it in positives:
        by_src.setdefault(it.get("source", "?"), []).append(it)
    for lst in by_src.values():
        rng.shuffle(lst)
    sampled: List[dict] = []
    keys = sorted(by_src)
    while len(sampled) < min(args.sample, len(positives)):
        progressed = False
        for key in keys:
            if by_src[key] and len(sampled) < args.sample:
                sampled.append(by_src[key].pop())
                progressed = True
        if not progressed:
            break
    traps = [it["query"] for it in rng.sample(negatives, min(args.negative_n, len(negatives)))]

    print(f"\n=== 端到端评测（RAGAS 风格 v2）：集合={args.eval_set} 正 {len(sampled)} + 陷阱负 {len(traps)} ===\n")

    faith_scores, relev_scores, ctx_scores = [], [], []
    correct_scores, ctx_recall_scores = [], []
    faith_rows = []
    lat_ret_ms: List[float] = []
    lat_gen_ms: List[float] = []
    t0 = time.time()
    for i, it in enumerate(sampled, 1):
        query, relevant, gt = it["query"], it["relevant_files"], it.get("answer_gt")
        try:
            context, files, dt_ret = _retrieve_context(vector_db, query, args.k, reranker)
            t1 = time.perf_counter()
            answer = _generate_answer(llm, query, context)
            dt_gen = time.perf_counter() - t1
            lat_ret_ms.append(dt_ret * 1000)
            lat_gen_ms.append(dt_gen * 1000)
            sup, tot = _parse_faith(_judge(llm, _FAITH_PROMPT.format(context=context[:6000], answer=answer[:2000])))
            relev = _parse_int(_judge(llm, _RELEV_PROMPT.format(question=query, answer=answer[:1500])))
            ctx = _parse_int(_judge(llm, _CTX_PROMPT.format(question=query, context=context[:4000])))
            if tot > 0 and sup >= 0:
                faith_scores.append(sup / tot)
                faith_rows.append((query, sup, tot))
            relev_scores.append(max(0, min(10, relev)) / 10 if relev >= 0 else None)
            ctx_scores.append(max(0, min(10, ctx)) / 10 if ctx >= 0 else None)
            corr = crec = -1
            if gt:
                corr = _parse_int(_judge(llm, _CORRECT_PROMPT.format(
                    question=query, gt=gt[:500], answer=answer[:1500])))
                crec = _parse_int(_judge(llm, _CTXRECALL_PROMPT.format(
                    question=query, gt=gt[:500], context=context[:4000])))
                if corr >= 0:
                    correct_scores.append(corr / 10)
                if crec >= 0:
                    ctx_recall_scores.append(crec / 10)
            mark = "✅" if files and relevant and relevant[0] in files else "❌"
            extra = f" corr={corr}/10 crec={crec}/10" if gt else ""
            print(f"  [{i}/{len(sampled)}] {mark} {query}")
            print(f"      faith={sup}/{tot} relev={relev}/10 ctx={ctx}/10{extra} "
                  f"ret={dt_ret*1000:.0f}ms gen={dt_gen*1000:.0f}ms 来源命中={[f for f in files[:3]]}")
        except Exception as e:
            print(f"  [{i}/{len(sampled)}] ⚠️ 失败: {query} -> {e}")

    refusal_scores = []
    for query in traps:
        try:
            context, files, dt_ret = _retrieve_context(vector_db, query, args.k, reranker)
            answer = _generate_answer(llm, query, context)
            score = _parse_int(_judge(llm, _REFUSAL_PROMPT.format(question=query, answer=answer[:1500])))
            refusal_scores.append(max(0, min(10, score)) / 10 if score >= 0 else None)
            print(f"  [负] {query} -> 拒答分 {score}/10（召回 {len(files)} 条）")
        except Exception as e:
            print(f"  [负] ⚠️ 失败: {query} -> {e}")

    def _avg(xs):
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else float("nan")

    print(f"\n=== 汇总（耗时 {time.time()-t0:.0f}s）===")
    print(f"  Faithfulness（主张支持率）: {_avg(faith_scores):.3f}")
    print(f"  Answer Relevancy:          {_avg(relev_scores):.3f}")
    print(f"  Context Precision(有用度): {_avg(ctx_scores):.3f}")
    print(f"  Answer Correctness(对GT):  {_avg(correct_scores):.3f}（n={len(correct_scores)}）")
    print(f"  Context Recall(GT覆盖):    {_avg(ctx_recall_scores):.3f}（n={len(ctx_recall_scores)}）")
    print(f"  拒答正确性（负样本）:       {_avg(refusal_scores):.3f}")
    print(f"  延迟: 检索 p50={_pct(lat_ret_ms,0.5):.0f}ms p90={_pct(lat_ret_ms,0.9):.0f}ms | "
          f"生成 p50={_pct(lat_gen_ms,0.5):.0f}ms p90={_pct(lat_gen_ms,0.9):.0f}ms")
    low = [(q, s, t) for q, s, t in faith_rows if t > 0 and s / t < 0.8]
    if low:
        print("\n  忠实度低于 0.8 的样本：")
        for q, s, t in low:
            print(f"    - {q} ({s}/{t})")


if __name__ == "__main__":
    main()
