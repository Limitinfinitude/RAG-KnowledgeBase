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
import io
import json
import math
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# 评测集：query -> 相关文档文件名（按相关度降序，越靠前越相关）
# 空列表 = 负样本
# 语料：AI Agent 书 5 章 + RAG 教程 + 提示工程指南 + 论文/白皮书/表格/小说（多格式同域）
EVAL_SET: List[Tuple[str, List[str]]] = [
    # ========== 睡眠科学（md） ==========
    ("睡眠周期REM和NREM的区别", ["睡眠科学与健康指南_20260817.md"]),
    ("深睡眠集中在什么时候", ["睡眠科学与健康指南_20260817.md"]),
    ("蓝光为什么影响入睡", ["睡眠科学与健康指南_20260817.md"]),
    ("成年人每天需要睡多久", ["睡眠科学与健康指南_20260817.md"]),
    ("失眠认知行为疗法CBT-I包括什么", ["睡眠科学与健康指南_20260817.md"]),
    ("睡眠呼吸暂停怎么诊断和治疗", ["睡眠科学与健康指南_20260817.md"]),
    ("NASA研究里小睡多久提升警觉性", ["睡眠科学与健康指南_20260817.md"]),
    ("咖啡因半衰期多久下午还能喝咖啡吗", ["睡眠科学与健康指南_20260817.md"]),
    ("卧室温度多少度适合睡觉", ["睡眠科学与健康指南_20260817.md"]),
    ("酒精对睡眠结构的影响", ["睡眠科学与健康指南_20260817.md"]),
    ("打鼾响还呼吸暂停要紧吗", ["睡眠科学与健康指南_20260817.md"]),
    # ========== 运动训练（md） ==========
    ("最大心率怎么估算", ["运动训练基础手册_20260817.md"]),
    ("什么是渐进超负荷原则", ["运动训练基础手册_20260817.md"]),
    ("80/20 耐力训练法则", ["运动训练基础手册_20260817.md"]),
    ("增肌每天需要多少蛋白质", ["运动训练基础手册_20260817.md"]),
    ("过度训练的警示信号有哪些", ["运动训练基础手册_20260817.md"]),
    ("跑步每周跑量增幅原则", ["运动训练基础手册_20260817.md"]),
    ("证据可靠的运动补剂有哪些", ["运动训练基础手册_20260817.md"]),
    ("深蹲硬拉时如何保护腰部", ["运动训练基础手册_20260817.md"]),
    ("WHO 每周运动量建议", ["运动训练基础手册_20260817.md"]),
    ("超量补偿是什么意思", ["运动训练基础手册_20260817.md"]),
    # ========== 个人理财（md） ==========
    ("72法则是怎么算的", ["个人理财入门读本_20260817.md"]),
    ("应急基金应该存多少", ["个人理财入门读本_20260817.md"]),
    ("什么是资产配置再平衡", ["个人理财入门读本_20260817.md"]),
    ("指数基金为什么费率低", ["个人理财入门读本_20260817.md"]),
    ("雪崩法和雪球法还债哪个好", ["个人理财入门读本_20260817.md"]),
    ("家庭保险配置顺序", ["个人理财入门读本_20260817.md"]),
    ("处置效应是什么行为偏差", ["个人理财入门读本_20260817.md"]),
    ("重疾险保额买多少合适", ["个人理财入门读本_20260817.md"]),
    ("为什么保本高收益不可信", ["个人理财入门读本_20260817.md"]),
    # ========== 高速铁路（html） ==========
    ("中国第一条350公里高铁是哪条", ["中国高速铁路发展资料_20260817.html"]),
    ("复兴号什么时候首发的", ["中国高速铁路发展资料_20260817.html"]),
    ("CR450 设计时速多少", ["中国高速铁路发展资料_20260817.html"]),
    ("CTCS-3 列控系统用什么通信", ["中国高速铁路发展资料_20260817.html"]),
    ("雅万高铁有什么意义", ["中国高速铁路发展资料_20260817.html"]),
    ("京沪高铁有多长客流多少", ["中国高速铁路发展资料_20260817.html"]),
    ("八纵八横什么时候建成", ["中国高速铁路发展资料_20260817.html"]),
    ("高铁对中小城市的虹吸效应", ["中国高速铁路发展资料_20260817.html"]),
    ("无砟轨道有什么优缺点", ["中国高速铁路发展资料_20260817.html"]),
    # ========== 图书馆规则（txt） ==========
    ("图书馆一次能借几本书", ["城市图书馆借阅与服务规则_20260817.txt"]),
    ("图书逾期一天多少钱", ["城市图书馆借阅与服务规则_20260817.txt"]),
    ("图书馆哪天上午闭馆", ["城市图书馆借阅与服务规则_20260817.txt"]),
    ("读者证丢了怎么补办", ["城市图书馆借阅与服务规则_20260817.txt"]),
    ("馆际互借多久到要花多少钱", ["城市图书馆借阅与服务规则_20260817.txt"]),
    ("图书馆座位怎么预约占座怎么办", ["城市图书馆借阅与服务规则_20260817.txt"]),
    ("古籍善本可以外借吗", ["城市图书馆借阅与服务规则_20260817.txt"]),
    ("数字资源批量下载什么后果", ["城市图书馆借阅与服务规则_20260817.txt"]),
    # ========== 咖啡冲煮（csv） ==========
    ("手冲V60 粉水比和研磨度", ["咖啡冲煮参数手册_20260817.csv"]),
    ("法压壶怎么泡咖啡", ["咖啡冲煮参数手册_20260817.csv"]),
    ("冷萃咖啡泡多久比例多少", ["咖啡冲煮参数手册_20260817.csv"]),
    ("土耳其咖啡要磨多细", ["咖啡冲煮参数手册_20260817.csv"]),
    ("意式浓缩的萃取时间和压力", ["咖啡冲煮参数手册_20260817.csv"]),
    ("爱乐压适合什么豆子", ["咖啡冲煮参数手册_20260817.csv"]),
    ("摩卡壶下壶水位有什么讲究", ["咖啡冲煮参数手册_20260817.csv"]),
    # ========== 智能音箱（pptx） ==========
    ("灵犀X1音箱定价多少", ["智能音箱新品发布要点_20260817.pptx"]),
    ("智能音箱有几个麦克风阵列", ["智能音箱新品发布要点_20260817.pptx"]),
    ("音箱支持哪些方言识别", ["智能音箱新品发布要点_20260817.pptx"]),
    ("智能家居兼容什么协议", ["智能音箱新品发布要点_20260817.pptx"]),
    ("音箱的隐私设计有哪些", ["智能音箱新品发布要点_20260817.pptx"]),
    ("音箱什么时候上市首发", ["智能音箱新品发布要点_20260817.pptx"]),
    # ========== 唐宋诗词（md） ==========
    ("但愿人长久千里共婵娟是谁写的", ["唐宋诗词名篇赏析_20260817.md"]),
    ("将进酒表达了什么情感", ["唐宋诗词名篇赏析_20260817.md"]),
    ("水调歌头这首词怀念谁", ["唐宋诗词名篇赏析_20260817.md"]),
    ("春望反映了什么历史事件", ["唐宋诗词名篇赏析_20260817.md"]),
    ("声声慢开篇十四个叠字赏析", ["唐宋诗词名篇赏析_20260817.md"]),
    ("苏辛并称指哪两位词人", ["唐宋诗词名篇赏析_20260817.md"]),
    ("大珠小珠落玉盘描写的是什么", ["唐宋诗词名篇赏析_20260817.md"]),
    # ========== 家庭急救（md） ==========
    ("烫伤处理五步口诀是什么", ["家庭急救常识手册_20260817.md"]),
    ("心肺复苏按压深度和频率", ["家庭急救常识手册_20260817.md"]),
    ("AED 电极片贴在什么位置", ["家庭急救常识手册_20260817.md"]),
    ("海姆立克急救法怎么做", ["家庭急救常识手册_20260817.md"]),
    ("鼻子出血正确处理方法", ["家庭急救常识手册_20260817.md"]),
    ("热射病现场怎么降温", ["家庭急救常识手册_20260817.md"]),
    ("低血糖意识不清还能喂糖吗", ["家庭急救常识手册_20260817.md"]),
    ("一氧化碳中毒要注意什么", ["家庭急救常识手册_20260817.md"]),
    ("止血带使用注意事项", ["家庭急救常识手册_20260817.md"]),
    # ========== 软件测试（md） ==========
    ("测试金字塔的比例分配", ["软件测试基础实践指南_20260817.md"]),
    ("单元测试FIRST原则", ["软件测试基础实践指南_20260817.md"]),
    ("mock和stub有什么区别", ["软件测试基础实践指南_20260817.md"]),
    ("行覆盖率有什么问题", ["软件测试基础实践指南_20260817.md"]),
    ("契约测试解决什么问题", ["软件测试基础实践指南_20260817.md"]),
    ("混沌工程和测试的区别", ["软件测试基础实践指南_20260817.md"]),
    ("修完bug怎么防止回归", ["软件测试基础实践指南_20260817.md"]),
    # ========== 跨域双相关 ==========
    ("睡眠如何影响肌肉恢复", ["运动训练基础手册_20260817.md", "睡眠科学与健康指南_20260817.md"]),
    ("咖啡因对睡眠的影响", ["睡眠科学与健康指南_20260817.md"]),
    # ========== 陷阱负样本：跨域词共现但语料无此内容 ==========
    ("图书馆有咖啡的书吗", []),
    ("高铁上能办借阅证吗", []),
    ("运动手环记录睡眠准吗", []),
    ("理财经理建议我买高铁股票", []),
    ("心肺复苏的唐诗描写", []),
    ("唐诗里的咖啡豆", []),
    # ========== 纯负样本（跨域，语料完全无对应内容） ==========
    ("红烧肉怎么做", []),
    ("世界杯决赛的比赛规则", []),
    ("如何办理房产过户手续", []),
    ("黑洞的信息悖论怎么理解", []),
    ("如何注册一家公司", []),
    ("量子纠缠是怎么回事", []),
    ("潜水证OW和AOW的区别", []),
    ("区块链智能合约怎么开发", []),
    ("宠物狗疫苗接种时间表", []),
    ("宋代官窑瓷器的鉴定方法", []),
    ("吉他入门先学和弦还是音阶", []),
    ("在职研究生报考条件", []),
    ("日本抹茶道的历史", []),
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


def _load_eval_set(which: str, source: Optional[str], limit: Optional[int]):
    """加载评测集：v2 = EVAL_SET_V2.json（824 条，2026-08-19）；legacy = 旧 104 条常量。"""
    if which == "legacy":
        items = []
        for q, r in EVAL_SET:
            items.append({"query": q, "relevant_files": list(r), "kind": "positive" if r else "negative",
                          "source": "legacy", "answer_gt": None, "passage_gt": None})
        return items
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "EVAL_SET_V2.json")
    with io.open(p, encoding="utf-8") as f:
        items = json.load(f)
    if source:
        items = [it for it in items if it.get("source") == source]
    if limit:
        items = items[:limit]
    return items


def _run_search(vector_db, query: str, k: int, search_mode: str) -> Tuple[List[str], Optional[float]]:
    """返回 (命中文件列表, top-1 分数)。负样本误召回判定用「是否有结果」，
    分数用于正/负样本的分数分布对比（标定 ABSOLUTE_MIN_SCORE 的依据）。"""
    if search_mode == "prod":
        # 生产全管线口径：查询分类 → hybrid → 重排 → 父块扩展 → 截断（与 /api/chat 完全同路径）
        from services.retrieval import retrieve_for_rag
        from services.ui_sink import RetrievalUISink
        from utils.reranker import get_cached_reranker

        ret = retrieve_for_rag(
            vector_db=vector_db, query=query, selected_kb="全部知识库", k=k,
            search_mode="hybrid", enable_reranker=True,
            reranker=get_cached_reranker(), sink=RetrievalUISink.noop(),
        )
        files = list(dict.fromkeys(
            str(it.get("file") or "") for it in ret.evidence_sources if it.get("file")
        ))
        top1 = ret.scored_docs[0][1] if ret.scored_docs else None
        return files, top1

    if search_mode == "rerank":
        # 生产管线形态：hybrid 宽召回 → CrossEncoder 概率重排（负样本的主防线）
        from utils.hybrid_search import load_bm25_index, rebuild_bm25_index, hybrid_search
        from utils.reranker import get_cached_reranker, rerank_documents

        bm25_index, bm25_docs = load_bm25_index()
        if bm25_index is None or bm25_docs is None:
            bm25_index, bm25_docs = rebuild_bm25_index(vector_db)
        recall_k = max(k * 4, 20)
        results = hybrid_search(
            query=query, vector_db=vector_db, bm25_index=bm25_index,
            bm25_docs=bm25_docs, top_k=recall_k, selected_kb="全部知识库",
        ) if bm25_index and bm25_docs else []
        if not results:
            results = [(d, 1 / (1 + s2)) for d, s2 in vector_db.similarity_search_with_score(query, k=recall_k)]
        doc_objs = [d for d, _ in results]
        if not doc_objs:
            return [], None
        scored = rerank_documents(
            query=query, documents=doc_objs,
            reranker=get_cached_reranker(), top_k=k, reranker_type="cloud_or_local",
        )
        if not scored:
            return [], None
        # 与生产 finalize 一致：重排概率低于 SIMILARITY_THRESHOLD 的结果丢弃
        from config import SIMILARITY_THRESHOLD

        passed = [(d, sc) for d, sc in scored if sc >= SIMILARITY_THRESHOLD]
        if not passed:
            return [], None
        files = list(dict.fromkeys(
            d.metadata.get("source_file", "") for d, _ in passed if d.metadata.get("source_file")
        ))
        return files, passed[0][1]

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

    # 向量模式应用「绝对下限」防线（与管线 vector 分支一致）；
    # 混合模式由 hybrid_search 内部做双信号判定（向量地板 + BM25 命中）
    if search_mode == "vector":
        from config import ABSOLUTE_MIN_SCORE

        if results and max(s for _, s in results) < ABSOLUTE_MIN_SCORE:
            return [], None

    # 去重保序：同一文件的多个 chunk 只计一次（否则 5 个同文件 chunk 会占满 top-k
    # 并把 DCG 推到 >1，多相关文档的 Recall 也被虚假压低——2026-08-17 评测发现）
    files = list(dict.fromkeys(
        doc.metadata.get("source_file", "") for doc, _ in results if doc.metadata.get("source_file")
    ))
    top1 = results[0][1] if results else None
    return files, top1


def _load_vector_db(user_id: int):
    from utils.path_context import set_user_kb_context
    from utils.db import get_vector_db

    set_user_kb_context(user_id)
    return get_vector_db()


def _fmt(v: Optional[float]) -> str:
    return "  n/a" if v is None else f"{v:.3f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="检索质量离线评测（Recall/nDCG/MRR + 负样本误召回惩罚）")
    parser.add_argument("--user", type=int, default=99, help="知识库用户 id（默认 99 评测库）")
    parser.add_argument("--k", type=int, default=5, help="k 值（默认 5，同时输出 Recall@3）")
    parser.add_argument("--set", dest="eval_set", choices=["v2", "legacy"], default="v2",
                        help="评测集：v2 = EVAL_SET_V2.json（默认），legacy = 旧 104 条")
    parser.add_argument("--source", default=None, help="仅评测 v2 中该来源（如 cmrc2018 / dureader_retrieval）")
    parser.add_argument("--limit", type=int, default=None, help="截取前 N 条（调试用）")
    parser.add_argument("--mode", choices=["vector", "hybrid", "rerank", "prod", "both", "all"], default="both")
    parser.add_argument("--verbose-fail", action="store_true", help="逐条打印未命中的正样本与误召回的负样本")
    args = parser.parse_args()

    items = _load_eval_set(args.eval_set, args.source, args.limit)
    pos_set = [(it["query"], it["relevant_files"]) for it in items if it["kind"] == "positive"]
    neg_set = [(it["query"], it["relevant_files"]) for it in items if it["kind"] == "negative"]
    src_of = {it["query"]: it.get("source", "?") for it in items}
    print(
        f"\n=== 检索质量评测：用户 {args.user}，k={args.k}，集合={args.eval_set}"
        f"{'/' + args.source if args.source else ''}，"
        f"样本 {len(items)} 条（正 {len(pos_set)} / 负 {len(neg_set)}）===\n"
    )

    vector_db = _load_vector_db(args.user)

    _MODE_PRESETS = {"both": ["vector", "hybrid"], "all": ["vector", "hybrid", "rerank", "prod"]}
    modes = _MODE_PRESETS.get(args.mode, [args.mode])
    summary: Dict[str, Dict[str, float]] = {}
    score_dist: Dict[str, Dict[str, List[Optional[float]]]] = {}

    for mode in modes:
        print(f"--- 检索模式：{mode} ---")
        by_source: Dict[str, Dict[str, List[float]]] = {}
        recalls, recalls3, ndcgs, mrrs = [], [], [], []
        pos_top1: List[float] = []
        neg_top1: List[float] = []
        false_recall_hits = 0

        for query, relevant in pos_set:
            files, top1 = _run_search(vector_db, query, args.k, mode)
            r = _recall_at_k(files, relevant, args.k)
            r3 = _recall_at_k(files, relevant, 3)
            n = _ndcg_at_k(files, relevant, args.k)
            m = _mrr(files, relevant)
            recalls.append(r)
            recalls3.append(r3)
            ndcgs.append(n)
            mrrs.append(m)
            by_source.setdefault(src_of.get(query, "?"), {}).setdefault("recall", []).append(r)
            if top1 is not None:
                pos_top1.append(top1)
            if args.verbose_fail and r < 1.0:
                print(f"  ❌ R={r:.2f} {query}  top3={[f for f in files[:3] if f]}")
                print(f"     期望={relevant}")

        for query, _r in neg_set:
            files, top1 = _run_search(vector_db, query, args.k, mode)
            if files:
                false_recall_hits += 1
                if top1 is not None:
                    neg_top1.append(top1)
                if args.verbose_fail:
                    print(f"  ⚠️【负样本·误召回】{query}  top1={files[0]} ({_fmt(top1)})")

        avg_r = sum(recalls) / len(recalls) if recalls else 0.0
        avg_r3 = sum(recalls3) / len(recalls3) if recalls3 else 0.0
        avg_n = sum(ndcgs) / len(ndcgs) if ndcgs else 0.0
        avg_m = sum(mrrs) / len(mrrs) if mrrs else 0.0
        false_recall = false_recall_hits / len(neg_set) if neg_set else 0.0
        denom = avg_r + (1 - false_recall)
        balanced = 2 * avg_r * (1 - false_recall) / denom if denom > 0 else 0.0

        summary[mode] = {
            "recall": avg_r, "recall3": avg_r3, "ndcg": avg_n, "mrr": avg_m,
            "false_recall": false_recall, "balanced": balanced,
        }
        score_dist[mode] = {"pos": pos_top1, "neg": neg_top1}

        print(
            f"  >>> Recall@{args.k}={avg_r:.4f} | Recall@3={avg_r3:.4f} | nDCG@{args.k}={avg_n:.4f} | MRR={avg_m:.4f}\n"
            f"  >>> FalseRecall@{args.k}={false_recall:.2%}（{false_recall_hits}/{len(neg_set)} 误召回）"
            f" | Balanced={balanced:.4f}\n"
        )
        if args.eval_set == "v2" and not args.source:
            print("  —— 分来源 Recall@" + str(args.k) + " ——")
            for s in sorted(by_source):
                rs = by_source[s]["recall"]
                print(f"     {s:<22s} n={len(rs):<4d} R={sum(rs)/len(rs):.4f}")
            print()

    print("=== Top-1 分数分布（阈值标定参考：正样本下界 vs 负样本上界的间隔）===")
    for mode in modes:
        pos = score_dist[mode]["pos"]
        neg = score_dist[mode]["neg"]
        if pos:
            print(f"  [{mode}] 正样本 top1: min={min(pos):.3f} p25={sorted(pos)[len(pos)//4]:.3f} "
                  f"median={sorted(pos)[len(pos)//2]:.3f} max={max(pos):.3f}")
        if neg:
            print(f"  [{mode}] 负样本误召回 top1: min={min(neg):.3f} max={max(neg):.3f}（{len(neg)} 条误召回样本）")
        else:
            print(f"  [{mode}] 负样本误召回: 无（全部正确拦截）")

    if len(modes) == 2 and "vector" in summary and "hybrid" in summary:
        print("\n=== 模式对比 ===")
        for metric in ("recall", "recall3", "ndcg", "mrr", "false_recall", "balanced"):
            v = summary["vector"][metric]
            h = summary["hybrid"][metric]
            print(f"  {metric.upper():13s} 向量={v:.4f}  混合={h:.4f}  Δ={'+' if h>=v else ''}{h-v:.4f}")

    print("\n=== 评测完成 ===\n")


if __name__ == "__main__":
    main()
