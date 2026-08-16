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

    def test_fallback_on_error(self, monkeypatch):
        monkeypatch.setattr(
            "utils.siliconflow_client.requests.post",
            lambda *a, **k: _FakeResp(500, {}),
        )
        rr = SiliconFlowReranker(api_key="sk-test")
        scores = rr.predict([["q", "a"], ["q", "b"], ["q", "c"]])
        # 回退降序分数
        assert scores[0] > scores[1] > scores[2]
