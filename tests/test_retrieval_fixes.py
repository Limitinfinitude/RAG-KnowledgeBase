"""全链路风险修复的回归测试：H1~H3 / M1~M7 / L 系列关键行为。"""
from __future__ import annotations

import threading

import pytest
from langchain_core.documents import Document

import utils.hybrid_search as hs


def _doc(text: str, source: str = "a.txt", **meta) -> Document:
    return Document(page_content=text, metadata={"source_file": source, **meta})


# ------------------- M1 + H3：RRF 内容 key 融合与证据分 -------------------

class TestRRFFusion:
    def test_same_content_different_objects_merges(self):
        # BM25 文档来自 pickle，与向量返回对象必然不同 id——同内容必须融合
        d1 = _doc("检索增强生成的三个阶段", "a.txt", chunk_level="small")
        d2 = Document(page_content="检索增强生成的三个阶段",
                      metadata={"source_file": "a.txt", "chunk_level": "small"})
        vec = [(d1, 0.7)]
        bm = [(d2, 1.0)]  # bm25 归一分
        out = hs.rrf_fusion(vec, bm)
        assert len(out) == 1  # 融合而非重复占位
        # 证据分 = max(向量相似度, bm25 归一分)
        assert out[0][1] == pytest.approx(1.0)

    def test_order_by_rrf_not_evidence(self):
        # 排序由 RRF 决定：双路靠前的低证据分文档应排在单路高分的文档之前
        d_both = _doc("双路命中", "a.txt")
        d_vec_only = _doc("仅向量高分", "b.txt")
        out = hs.rrf_fusion([(d_both, 0.55), (d_vec_only, 0.95)], [(d_both, 0.3)])
        assert out[0][0].page_content == "双路命中"

    def test_evidence_score_same_scale_as_thresholds(self):
        d = _doc("内容", "a.txt")
        out = hs.rrf_fusion([(d, 0.42)], [])
        assert 0.0 <= out[0][1] <= 1.0


# ------------------- H2：向量地板双信号判定 -------------------

class _FakeVectorDB:
    def __init__(self, l2_scores):
        # l2_scores: [(doc, L2)]
        self._results = l2_scores

    def similarity_search_with_score(self, query, k):
        return self._results[:k]


class TestHybridFloor:
    def _run(self, monkeypatch, vector_l2, bm25_results):
        monkeypatch.setattr(hs, "bm25_search", lambda *a, **k: bm25_results)
        vdb = _FakeVectorDB(vector_l2)
        return hs.hybrid_search(
            query="某专有名词XYZ", vector_db=vdb,
            bm25_index=object(), bm25_docs=[object()],
            top_k=5, selected_kb="默认知识库",
        )

    def test_vector_low_bm25_hit_still_returns(self, monkeypatch):
        # 向量全低（L2=2 → 0.33 < 0.5）但 BM25 精确命中 → 不再一票否决
        docs = [( _doc("专有名词XYZ手册", "m.txt"), 2.0)]
        out = self._run(monkeypatch, docs, [( _doc("专有名词XYZ手册", "m.txt"), 8.5)])
        assert out, "BM25 命中时不应被向量地板短路"

    def test_both_signals_dead_returns_empty(self, monkeypatch):
        # 向量低 + BM25 无命中（全 0 分）→ 负样本防线保留
        d = _doc("无关内容", "m.txt")
        out = self._run(monkeypatch, [(d, 2.0)], [(d, 0.0)])
        assert out == []

    def test_vector_healthy_no_bm25_returns(self, monkeypatch):
        d = _doc("正常内容", "m.txt")
        out = self._run(monkeypatch, [(d, 0.2)], [])
        assert out and out[0][1] > 0.5


# ------------------- M7：单字 CJK 分词 -------------------

class TestTokenizer:
    def test_single_cjk_content_word_kept(self):
        toks = hs.tokenize_chinese("灭火器的甲烷浓度")
        assert "灭" in toks or "灭火器" in toks  # 词或字至少保留其一
        assert "甲" in toks or "甲烷" in toks

    def test_single_char_stopword_dropped(self):
        toks = hs.tokenize_chinese("这是我的书")
        assert "的" not in toks
        assert "这" not in toks

    def test_pure_single_char_query_has_tokens(self):
        # 单字查询（如型号"甲"）不再得到空 token 列表
        assert hs.tokenize_chinese("甲") == ["甲"]


# ------------------- M4：意图分类 -------------------

class TestIntent:
    def test_kb_question_with_usage_phrase_is_rag(self):
        from utils.intent_classifier import classify_intent_lightweight

        assert classify_intent_lightweight("灭火器怎么使用") is None
        assert classify_intent_lightweight("怎么使用灭火器") is None
        assert classify_intent_lightweight("使用方法") is None  # 单独出现视为问产品文档

    def test_system_usage_question_is_chat(self):
        from utils.intent_classifier import classify_intent_lightweight

        assert classify_intent_lightweight("这个系统怎么使用") == "CHAT"
        assert classify_intent_lightweight("你怎么使用") == "CHAT"
        assert classify_intent_lightweight("你是谁") == "CHAT"


# ------------------- M3：rerank 失败保留原序原分 -------------------

class TestRerankFallback:
    def test_failure_keeps_original_scores(self):
        from utils.reranker import rerank_documents

        class Boom:
            def predict(self, pairs):
                raise RuntimeError("api down")

        docs = [_doc(f"文档{i}", "a.txt") for i in range(3)]
        out = rerank_documents("查询", docs, Boom(), top_k=3, fallback_scores=[0.8, 0.6, 0.4])
        assert [d.page_content for d, _ in out] == ["文档0", "文档1", "文档2"]
        assert [s for _, s in out] == [0.8, 0.6, 0.4]  # 不再伪造 1.0 递减高分

    def test_failure_without_fallback_marks_zero(self):
        from utils.reranker import rerank_documents

        class Boom:
            def predict(self, pairs):
                raise RuntimeError("api down")

        docs = [_doc("文档", "a.txt")]
        out = rerank_documents("查询", docs, Boom(), top_k=1)
        assert out[0][1] == 0.0  # 0 分 → 上层低置信分支正确触发


# ------------------- M5 + L8：finalize 去重与 k 生效 -------------------

class TestFinalize:
    def _finalize(self, docs, k):
        from services.retrieval import finalize_retrieval_from_scored
        from services.ui_sink import RetrievalUISink

        return finalize_retrieval_from_scored(
            vector_db=None, scored_docs=docs, k=k,
            sink=RetrievalUISink.noop(), start_time=0.0,
        )

    def test_duplicate_parent_chunks_deduped(self):
        # 多个 small 子块扩展到同一父块的场景：同内容去重后不再重复占位
        body = "这是一段完整的父块内容，以句号结尾。" * 5
        d1 = Document(page_content=body, metadata={"source_file": "a.txt", "chunk_level": "medium"})
        d2 = Document(page_content=body, metadata={"source_file": "a.txt", "chunk_level": "medium"})
        out = self._finalize([(d1, 0.9), (d2, 0.85)], k=5)
        assert len(out.evidence_sources) == 1

    def test_k_respected_beyond_context_top_k(self):
        # k=8 时给足 8 个不同来源（旧行为钉死 CONTEXT_TOP_K=5）
        docs = [(_doc(f"第{i}个来源的完整内容，以句号结尾。" * 3, f"f{i}.txt"), 0.9) for i in range(8)]
        out = self._finalize(docs, k=8)
        assert len(out.evidence_sources) == 8


# ------------------- H1：BM25 预热线程上下文与最新快照 -------------------

class TestBM25Prewarm:
    def test_prewarm_binds_user_context_and_reloads_from_disk(self, monkeypatch, tmp_path):
        import utils.path_context as pc
        import web_app.backend.ingest_queue as iq

        # 调度时的上下文目录（模拟中间件已绑定）
        t = pc._kb_dir_var.set(str(tmp_path))

        calls = {"set_ctx": 0, "load_disk": [], "rebuild": 0}

        monkeypatch.setattr(iq, "set_user_kb_context",
                            lambda uid: calls.__setitem__("set_ctx", calls["set_ctx"] + 1) or (1, 2))
        monkeypatch.setattr(iq, "reset_kb_context", lambda a, b: None)
        monkeypatch.setattr(iq, "_load_vdb_from_disk",
                            lambda kb_dir: calls["load_disk"].append(kb_dir) or object())
        monkeypatch.setattr(iq.threading, "Thread",
                            lambda *a, **k: _SyncThread(k["target"]))
        import utils.hybrid_search as hsm
        monkeypatch.setattr(hsm, "rebuild_bm25_index", lambda vdb: calls.__setitem__("rebuild", calls["rebuild"] + 1))

        try:
            iq._invalidate_and_prewarm_bm25(42)
        finally:
            pc._kb_dir_var.reset(t)

        assert calls["set_ctx"] == 1            # 线程内显式绑定用户上下文
        assert calls["load_disk"] == [str(tmp_path)]  # 用调度时捕获的目录（非默认 Streamlit 目录）
        assert calls["rebuild"] == 1            # 从磁盘重载的最新 vdb 重建


class _SyncThread:
    """测试替身：把后台线程改成同步执行。"""

    def __init__(self, target):
        self._target = target
        self._target()

    def start(self):
        pass

    def is_alive(self):
        return False


# ------------------- BM25 词覆盖率门控（2026-08-17 评测发现） -------------------

class TestBM25CoverageGate:
    def test_weak_overlap_rejected(self):
        # 「黑洞的信息悖论」只靠「信息」一词命中提示词文档 → 必须被门控拦截
        d = _doc("提示词工程中信息的组织方式", "p.md")
        gated = hs._bm25_coverage_gate(hs.tokenize_chinese("黑洞的信息悖论怎么理解"), [(d, 9.0)])
        assert gated == []

    def test_single_char_only_match_rejected(self):
        # 「潜水证」的「证」撞上「借阅证」——单字巧合不算命中
        d = _doc("读者证挂失补办流程说明", "lib.txt")
        gated = hs._bm25_coverage_gate(hs.tokenize_chinese("潜水证怎么考"), [(d, 7.0)])
        assert gated == []

    def test_full_overlap_kept(self):
        d = _doc("图书逾期费每册每天一角", "lib.txt")
        toks = hs.tokenize_chinese("图书逾期多少钱")
        gated = hs._bm25_coverage_gate(toks, [(d, 6.0)])
        assert len(gated) == 1

    def test_empty_query_tokens_returns_empty(self):
        assert hs._bm25_coverage_gate([], [(_doc("x", "a"), 1.0)]) == []
