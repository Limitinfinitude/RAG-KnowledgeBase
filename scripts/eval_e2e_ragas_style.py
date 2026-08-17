"""端到端评测（RAGAS 风格，LLM-as-judge）：faithfulness / answer relevancy / context precision / 拒答正确性。

用法（项目根目录）::

    python scripts/eval_e2e_ragas_style.py --user 99 --sample 24

说明：
- 采用 RAGAS 的指标方法论（主张支持率、答案相关度、上下文有用度），但用项目自身的
  LLM（deepseek 等 OpenAI 兼容）作 judge，不引入 ragas 库——其依赖锁与本项目
  langchain 1.x 冲突，强行安装会破坏环境。
- 管线为生产形态：hybrid 召回 → CrossEncoder 重排 → 父块扩展/裁剪（MAX_CONTEXT_LENGTH
  生效）→ LLM 生成 → judge 打分。正样本评三指标；负样本评「拒答正确性」
  （正确行为：声明资料中无相关内容，而非编造）。
- 抽样策略：分层抽样正样本（按目标文件均匀）+ 全部陷阱负样本的前若干条。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from typing import Dict, List, Tuple

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.eval_retrieval import EVAL_SET


def _retrieve_context(vector_db, query: str, k: int, reranker) -> Tuple[str, List[str]]:
    """生产形态检索：hybrid + 重排 + finalize（与 /api/chat 一致）。"""
    from services.retrieval import retrieve_for_rag
    from services.ui_sink import RetrievalUISink

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
    return ret.numbered_context, files


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


def main() -> None:
    parser = argparse.ArgumentParser(description="端到端 RAGAS 风格评测")
    parser.add_argument("--user", type=int, default=99)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--sample", type=int, default=24, help="正样本抽样数（负样本另计）")
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
    positives = [(q, r) for q, r in EVAL_SET if r]
    traps = [q for q, r in EVAL_SET if not r][:6]
    # 分层：按首个相关文件分组均匀抽
    by_file: Dict[str, List] = {}
    for q, r in positives:
        by_file.setdefault(r[0], []).append((q, r))
    sampled: List = []
    keys = sorted(by_file)
    while len(sampled) < min(args.sample, len(positives)):
        for key in keys:
            if by_file[key] and len(sampled) < args.sample:
                sampled.append(by_file[key].pop(rng.randrange(len(by_file[key]))))

    print(f"\n=== 端到端评测（RAGAS 风格）：正样本 {len(sampled)} + 陷阱负样本 {len(traps)} ===\n")

    faith_scores, relev_scores, ctx_scores = [], [], []
    faith_rows = []
    t0 = time.time()
    for i, (query, relevant) in enumerate(sampled, 1):
        try:
            context, files = _retrieve_context(vector_db, query, args.k, reranker)
            answer = _generate_answer(llm, query, context)
            sup, tot = _parse_faith(_judge(llm, _FAITH_PROMPT.format(context=context[:6000], answer=answer[:2000])))
            relev = _parse_int(_judge(llm, _RELEV_PROMPT.format(question=query, answer=answer[:1500])))
            ctx = _parse_int(_judge(llm, _CTX_PROMPT.format(question=query, context=context[:4000])))
            if tot > 0 and sup >= 0:
                faith_scores.append(sup / tot)
                faith_rows.append((query, sup, tot, files, relevant))
            relev_scores.append(max(0, min(10, relev)) / 10 if relev >= 0 else None)
            ctx_scores.append(max(0, min(10, ctx)) / 10 if ctx >= 0 else None)
            mark = "✅" if files and relevant[0] in files else "❌"
            print(f"  [{i}/{len(sampled)}] {mark} {query}")
            print(f"      faith={sup}/{tot} relev={relev}/10 ctx={ctx}/10 来源命中={[f for f in files[:3]]}")
        except Exception as e:
            print(f"  [{i}/{len(sampled)}] ⚠️ 失败: {query} -> {e}")

    refusal_scores = []
    for query in traps:
        try:
            context, files = _retrieve_context(vector_db, query, args.k, reranker)
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
    print(f"  拒答正确性（负样本）:       {_avg(refusal_scores):.3f}")
    low = [(q, s, t) for q, s, t, *_ in faith_rows if t > 0 and s / t < 0.8]
    if low:
        print("\n  忠实度低于 0.8 的样本：")
        for q, s, t in low:
            print(f"    - {q} ({s}/{t})")


if __name__ == "__main__":
    main()
