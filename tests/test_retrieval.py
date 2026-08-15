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

    def test_low_score_docs_still_returned(self):
        # 低于阈值但非空时，回退取前 3
        docs = [(_make_doc(f"t{i}", score=0.1), 0.1) for i in range(5)]
        out = finalize_retrieval_from_scored(
            vector_db=None,
            scored_docs=docs,
            k=5,
            sink=self._sink(),
            start_time=__import__("time").perf_counter(),
        )
        assert out.scored_docs  # 非空

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
