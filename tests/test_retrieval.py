"""测试检索管线的纯函数：文档合并键、质量过滤、上下文截断。"""
import pytest

from services.retrieval import (
    SIMILARITY_THRESHOLD,
    _merge_doc_key,
    finalize_retrieval_from_scored,
)
from services.ui_sink import RetrievalUISink


class _FakeDoc:
    def __init__(self, page_content="", metadata=None):
        self.page_content = page_content
        self.metadata = metadata or {}


def _make_doc(text, source="a.txt", score=0.8):
    return _FakeDoc(text, {"source_file": source})


class TestMergeDocKey:
    def test_key_contains_source(self):
        doc = _make_doc("hello", source="a.txt")
        assert "a.txt" in _merge_doc_key(doc)

    def test_key_deterministic(self):
        doc = _make_doc("hello", source="a.txt")
        assert _merge_doc_key(doc) == _merge_doc_key(_make_doc("hello", source="a.txt"))

    def test_key_differs_by_content(self):
        k1 = _merge_doc_key(_make_doc("hello"))
        k2 = _merge_doc_key(_make_doc("world"))
        assert k1 != k2

    def test_handles_missing_metadata(self):
        doc = _FakeDoc("x", None)
        key = _merge_doc_key(doc)
        assert isinstance(key, str)


class TestFinalizeRetrieval:
    def _sink(self):
        return RetrievalUISink.noop()

    def test_empty_input_returns_empty(self):
        out = finalize_retrieval_from_scored(
            vector_db=None,
            scored_docs=[],
            k=5,
            sink=self._sink(),
            start_time=__import__("time").perf_counter(),
        )
        assert out.numbered_context == ""
        assert out.evidence_sources == []
        assert out.scored_docs == []

    def test_all_below_absolute_floor_returns_empty(self):
        # 全部分数低于 ABSOLUTE_MIN_SCORE（0.5）→ 视为无相关内容
        from services.retrieval import filter_by_absolute_floor

        docs = [(_make_doc(f"t{i}", score=0.1), 0.1) for i in range(5)]
        assert filter_by_absolute_floor(docs) == []

    def test_negative_like_scores_return_empty(self):
        # 负样本实测分数区间（0.41~0.47）：高于 SIMILARITY_THRESHOLD 但低于绝对下限
        from services.retrieval import filter_by_absolute_floor

        docs = [(_make_doc(f"t{i}", score=0.45), 0.45) for i in range(3)]
        assert filter_by_absolute_floor(docs) == []

    def test_positive_like_scores_pass_floor(self):
        # 正样本实测分数区间（0.62~0.68）：高于绝对下限，正常放行
        from services.retrieval import filter_by_absolute_floor

        docs = [(_make_doc(f"内容{i}", source=f"f{i}.txt", score=0.65), 0.65) for i in range(3)]
        assert filter_by_absolute_floor(docs) == docs

    def test_empty_input_passes_floor(self):
        from services.retrieval import filter_by_absolute_floor

        assert filter_by_absolute_floor([]) == []

    def test_high_score_docs_generate_numbered_context(self):
        docs = [(_make_doc(f"内容{i}", source=f"f{i}.txt", score=0.9), 0.9) for i in range(3)]
        out = finalize_retrieval_from_scored(
            vector_db=None,
            scored_docs=docs,
            k=5,
            sink=self._sink(),
            start_time=__import__("time").perf_counter(),
        )
        assert "[来源1]" in out.numbered_context
        assert len(out.evidence_sources) == 3

    def test_context_truncation_bounded_by_max_length(self):
        # 用超长文本验证 max_context_length 截断逻辑不越界
        long_text = "A" * 5000
        docs = [(_make_doc(long_text, score=0.9), 0.9)]
        out = finalize_retrieval_from_scored(
            vector_db=None,
            scored_docs=docs,
            k=5,
            sink=self._sink(),
            start_time=__import__("time").perf_counter(),
        )
        # 上下文被截断到 max_context_length 附近
        assert len(out.numbered_context) <= 5000 + 100
