"""测试硅基流动客户端：embedding / rerank 接口（mock requests）。"""
import pytest

from utils.siliconflow_client import SiliconFlowEmbeddings, SiliconFlowReranker


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


class TestSiliconFlowEmbeddings:
    def test_requires_api_key(self):
        with pytest.raises(ValueError):
            SiliconFlowEmbeddings(api_key="")

    def test_embed_query(self, monkeypatch):
        calls = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            calls["json"] = json
            return _FakeResp(200, {"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})

        monkeypatch.setattr("utils.siliconflow_client.requests.post", fake_post)
        emb = SiliconFlowEmbeddings(api_key="sk-test", model="BAAI/bge-m3")
        vec = emb.embed_query("你好")
        assert vec == [0.1, 0.2, 0.3]
        assert calls["json"]["model"] == "BAAI/bge-m3"
        assert calls["json"]["input"] == ["你好"]
        assert calls["json"] is not None

    def test_is_callable(self, monkeypatch):
        # FAISS 等 LangChain 组件会以 embedding(text) 方式调用，须支持 __call__
        monkeypatch.setattr(
            "utils.siliconflow_client.requests.post",
            lambda *a, **k: _FakeResp(200, {"data": [{"index": 0, "embedding": [1.0, 2.0]}]}),
        )
        emb = SiliconFlowEmbeddings(api_key="sk-test")
        assert callable(emb)
        assert emb("查询") == [1.0, 2.0]

    def test_isinstance_embeddings(self):
        from langchain_core.embeddings import Embeddings

        emb = SiliconFlowEmbeddings(api_key="sk-test")
        assert isinstance(emb, Embeddings)

    def test_embed_documents_batches(self, monkeypatch):
        # 3 条文档，batch_size=2，应拆成 2 批
        def fake_post(url, headers=None, json=None, timeout=None):
            texts = json["input"]
            return _FakeResp(200, {"data": [{"index": i, "embedding": [float(i)]} for i in range(len(texts))]})

        monkeypatch.setattr("utils.siliconflow_client.requests.post", fake_post)
        emb = SiliconFlowEmbeddings(api_key="sk-test", batch_size=2)
        vecs = emb.embed_documents(["a", "b", "c"])
        assert vecs == [[0.0], [1.0], [0.0]]

    def test_error_raises(self, monkeypatch):
        monkeypatch.setattr(
            "utils.siliconflow_client.requests.post",
            lambda *a, **k: _FakeResp(401, {}),
        )
        emb = SiliconFlowEmbeddings(api_key="sk-bad")
        with pytest.raises(RuntimeError):
            emb.embed_query("x")


class TestSiliconFlowReranker:
    def test_predict_maps_scores(self, monkeypatch):
        def fake_post(url, headers=None, json=None, timeout=None):
            assert json["query"] == "q"
            assert json["documents"] == ["d0", "d1", "d2"]
            return _FakeResp(200, {"results": [
                {"index": 2, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.5},
                {"index": 1, "relevance_score": 0.1},
            ]})

        monkeypatch.setattr("utils.siliconflow_client.requests.post", fake_post)
        rr = SiliconFlowReranker(api_key="sk-test")
        scores = rr.predict([["q", "d0"], ["q", "d1"], ["q", "d2"]])
        assert scores == [0.5, 0.1, 0.9]

    def test_score_is_probability_flag(self):
        rr = SiliconFlowReranker(api_key="sk-test")
        assert rr.score_is_probability is True

    def test_error_raises_instead_of_fake_scores(self, monkeypatch):
        # 失败必须上抛（rerank_documents 会保留原序原分）；
        # 内部伪造 1.0 递减高分会绕过 SIMILARITY_THRESHOLD 与低置信防线
        monkeypatch.setattr(
            "utils.siliconflow_client.requests.post",
            lambda *a, **k: _FakeResp(500, {}),
        )
        rr = SiliconFlowReranker(api_key="sk-test")
        with pytest.raises(RuntimeError, match="500"):
            rr.predict([["q", "a"], ["q", "b"], ["q", "c"]])


class TestSiliconFlowOCR:
    def test_requires_api_key(self):
        from utils.siliconflow_client import SiliconFlowOCR
        with pytest.raises(ValueError):
            SiliconFlowOCR(api_key="")

    def test_extract_text_request_format_and_unwrap(self, monkeypatch):
        import base64

        from utils.siliconflow_client import SiliconFlowOCR

        calls = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            calls.update(url=url, json=json)
            content = "<markdown># 标题\n\n正文内容</markdown>"
            return _FakeResp(200, {"choices": [{"message": {"content": content}}]})

        monkeypatch.setattr("utils.siliconflow_client.requests.post", fake_post)
        ocr = SiliconFlowOCR(api_key="sk-test", model="deepseek-ai/DeepSeek-OCR")
        text = ocr.extract_text(b"\x89PNG-fake", mime="image/png")

        assert text == "# 标题\n\n正文内容"
        assert calls["url"].endswith("/v1/chat/completions")
        assert calls["json"]["model"] == "deepseek-ai/DeepSeek-OCR"
        content = calls["json"]["messages"][0]["content"]
        assert content[0]["type"] == "image_url"
        assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert base64.b64encode(b"\x89PNG-fake").decode() in content[0]["image_url"]["url"]
        assert "<|grounding|>" in content[1]["text"]

    def test_http_error_raises(self, monkeypatch):
        from utils.siliconflow_client import SiliconFlowOCR

        class ErrResp(_FakeResp):
            def __init__(self):
                super().__init__(500, {})
                self.text = "server exploded"

        monkeypatch.setattr("utils.siliconflow_client.requests.post", lambda *a, **k: ErrResp())
        ocr = SiliconFlowOCR(api_key="sk-test")
        with pytest.raises(RuntimeError, match="500"):
            ocr.extract_text(b"img")

    def test_empty_content_raises(self, monkeypatch):
        from utils.siliconflow_client import SiliconFlowOCR

        monkeypatch.setattr(
            "utils.siliconflow_client.requests.post",
            lambda *a, **k: _FakeResp(200, {"choices": [{"message": {"content": "  "}}]}),
        )
        ocr = SiliconFlowOCR(api_key="sk-test")
        with pytest.raises(RuntimeError, match="空内容"):
            ocr.extract_text(b"img")


class TestSiliconFlowOCCleaning:
    def test_grounding_annotations_removed(self):
        from utils.siliconflow_client import _clean_ocr_content

        raw = (
            "<markdown><|ref|>title<|/ref|><|det|>[[33, 106, 500, 214]]<|/det|>\n"
            "RAG Evaluation Report\n\n"
            "<|ref|>text<|/ref|><|det|>[[33, 325, 644, 480]]<|/det|>\n"
            "Recall@5 = 0.87</markdown>"
        )
        out = _clean_ocr_content(raw)
        assert "RAG Evaluation Report" in out and "Recall@5" in out
        assert "<|ref|>" not in out and "<|det|>" not in out and "[[" not in out

    def test_plain_markdown_kept(self):
        from utils.siliconflow_client import _clean_ocr_content

        out = _clean_ocr_content("<markdown># 标题\n\n| 列A | 列B |\n|---|---|\n| 1 | 2 |</markdown>")
        assert "| 列A | 列B |" in out and "| 1 | 2 |" in out
