"""测试查询类型分类器（规则分支 + 口语映射 + 参数调整）。"""
import pytest

from utils.improved_query_classifier import (
    classify_query_type_rule_based,
    get_chunk_level_for_query_improved,
    get_retrieval_params_for_query,
)


class TestClassifyQueryTypeRuleBased:
    @pytest.mark.parametrize(
        "query,expected",
        [
            ("请总结一下这篇文档的主要内容", "summary"),
            ("这本书讲了什么", "summary"),
            ("A 和 B 有什么区别", "comparison"),
            ("哪些条件满足要求", "conditional"),
            ("为什么会出现这个现象", "reasoning"),
            ("什么是 RAG", "concept"),
            ("张三是谁", "precise"),
            ("这个函数怎么写", "concept"),
        ],
    )
    def test_classification(self, query, expected):
        assert classify_query_type_rule_based(query) == expected

    def test_oral_mapping_zha(self):
        # 口语「咋」应映射为「如何」→ 归入概念类
        assert classify_query_type_rule_based("咋用这个") == "concept"

    def test_oral_mapping_sha(self):
        # 口语「啥」映射为「什么」
        assert classify_query_type_rule_based("啥是RAG") == "concept"

    def test_unknown_defaults_to_concept(self):
        assert classify_query_type_rule_based("今天") == "concept"


class TestChunkLevelMapping:
    def test_precise_prefers_small(self):
        assert get_chunk_level_for_query_improved("precise") == ["small", "medium"]

    def test_summary_prefers_summary_chunk(self):
        assert get_chunk_level_for_query_improved("summary") == ["summary", "large"]

    def test_unknown_type_defaults(self):
        assert get_chunk_level_for_query_improved("unknown") == ["medium", "large"]


class TestRetrievalParams:
    # 注意：kb_doc_count=0（未传）会落入「小知识库」分支 → kb_factor=0.9
    def test_precise_multiplier(self):
        p = get_retrieval_params_for_query("precise", query_length=20, kb_doc_count=500)
        # base_k * precise(1.5) * len(1.0) * kb(500→1.0)
        assert p["fetch_k"] == int(10 * 1.5 * 1.0 * 1.0)

    def test_summary_multiplier(self):
        p = get_retrieval_params_for_query("summary", query_length=20, kb_doc_count=500)
        assert p["fetch_k"] == int(10 * 2.5 * 1.0 * 1.0)

    def test_short_query_reduces_fetch(self):
        p = get_retrieval_params_for_query("concept", query_length=5, kb_doc_count=500)
        # concept(2.0) * short(0.8) * kb(1.0)
        assert p["fetch_k"] == int(10 * 2.0 * 0.8 * 1.0)

    def test_small_kb_reduces_fetch(self):
        # kb_doc_count 很小时 kb_factor=0.9
        p = get_retrieval_params_for_query("concept", query_length=20, kb_doc_count=10)
        assert p["fetch_k"] == int(10 * 2.0 * 1.0 * 0.9)

    def test_huge_kb_raises_fetch(self):
        p = get_retrieval_params_for_query("concept", query_length=20, kb_doc_count=2000)
        assert p["fetch_k"] == int(10 * 2.0 * 1.0 * 1.2)

    def test_stable_keys_present(self):
        p = get_retrieval_params_for_query("reasoning", query_length=30)
        assert set(p.keys()) == {"fetch_k", "top_k", "similarity_threshold"}
