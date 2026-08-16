"""硅基流动（SiliconFlow）API 客户端：Embedding 与 Rerank。

- SiliconFlowEmbeddings：兼容 LangChain Embeddings 接口（embed_documents / embed_query）
- SiliconFlowReranker：兼容项目 reranker 接口（predict(pairs) -> List[float]）

API 端点：
- Embedding: POST {base_url}/v1/embeddings   body: {"model", "input"}
- Rerank:    POST {base_url}/v1/rerank      body: {"model", "query", "documents", "top_n"}
"""
from __future__ import annotations

import logging
from typing import List, Optional

import requests

try:
    from langchain_core.embeddings import Embeddings
except Exception:  # 若 langchain_core 不可用则退回纯 duck-typing
    Embeddings = None

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.siliconflow.cn"

# 硅基流动 embedding 模型推荐清单（管理端下拉可选项）
EMBEDDING_MODEL_OPTIONS: List[str] = [
    "BAAI/bge-m3",
    "BAAI/bge-large-zh-v1.5",
    "BAAI/bge-large-en-v1.5",
    "Pro/BAAI/bge-m3",
    "Qwen/Qwen3-Embedding-8B",
    "Qwen/Qwen3-Embedding-4B",
    "Qwen/Qwen3-Embedding-0.6B",
]

# 硅基流动 rerank 模型推荐清单
RERANK_MODEL_OPTIONS: List[str] = [
    "BAAI/bge-reranker-v2-m3",
    "Pro/BAAI/bge-reranker-v2-m3",
    "Qwen/Qwen3-Reranker-8B",
    "Qwen/Qwen3-Reranker-4B",
    "Qwen/Qwen3-Reranker-0.6B",
]


class SiliconFlowEmbeddingsBase(Embeddings if Embeddings is not None else object):
    pass


class SiliconFlowEmbeddings(SiliconFlowEmbeddingsBase):
    """基于硅基流动 /v1/embeddings 的 LangChain 兼容嵌入实现。

    继承 langchain_core.embeddings.Embeddings，满足 FAISS.add_documents / from_texts
    对 embedding 对象的要求（含 __call__ = embed_query）。
    """

    score_is_probability = False  # 标记：非 reranker，无意义，仅为接口统一

    def __init__(self, api_key: str, model: str = "BAAI/bge-m3",
                 base_url: str = DEFAULT_BASE_URL, batch_size: int = 16, timeout: int = 60):
        if not api_key:
            raise ValueError("硅基流动 API Key 未配置")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.batch_size = max(1, int(batch_size))
        self.timeout = int(timeout)
        self._endpoint = f"{self.base_url}/v1/embeddings"

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        resp = requests.post(
            self._endpoint,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "input": texts},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"硅基流动 embedding 请求失败 {resp.status_code}: {resp.text[:300]}")
        payload = resp.json()
        data = payload.get("data") or []
        # 按 index 排序，确保顺序与输入一致
        data = sorted(data, key=lambda x: x.get("index", 0))
        vectors = [item.get("embedding") or [] for item in data]
        if len(vectors) != len(texts):
            raise RuntimeError(f"硅基流动 embedding 返回条数不符：期望 {len(texts)}，实际 {len(vectors)}")
        return vectors

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for i in range(0, len(texts), self.batch_size):
            chunk = texts[i:i + self.batch_size]
            out.extend(self._embed_batch([t for t in chunk]))
        return out

    def embed_query(self, text: str) -> List[float]:
        return self._embed_batch([text])[0]

    def __call__(self, text: str) -> List[float]:
        """LangChain 旧式调用别名：embedding(text) == embed_query(text)。"""
        return self.embed_query(text)


class SiliconFlowReranker:
    """基于硅基流动 /v1/rerank 的重排序实现。

    兼容项目 reranker 接口：predict(pairs) -> List[float]，其中 pairs 为 [[query, doc], ...]，
    且所有 pair 共享同一个 query（见 services/rerank_documents 的调用方式）。
    """

    # 关键标记：硅基流动 rerank 返回的 relevance_score 已是 0-1 概率，
    # rerank_documents 需据此跳过 sigmoid 转换（本地 CrossEncoder 返回的是 logits）。
    score_is_probability = True

    def __init__(self, api_key: str, model: str = "BAAI/bge-reranker-v2-m3",
                 base_url: str = DEFAULT_BASE_URL, timeout: int = 60):
        if not api_key:
            raise ValueError("硅基流动 API Key 未配置")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = int(timeout)
        self._endpoint = f"{self.base_url}/v1/rerank"

    def predict(self, pairs: List[List[str]]) -> List[float]:
        if not pairs:
            return []
        query = pairs[0][0] if pairs[0] else ""
        documents = [p[1] if len(p) > 1 else "" for p in pairs]
        try:
            resp = requests.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "query": query, "documents": documents, "top_n": len(documents)},
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"硅基流动 rerank 请求失败 {resp.status_code}: {resp.text[:300]}")
            results = (resp.json().get("results") or [])
            score_map = {int(r.get("index", -1)): float(r.get("relevance_score", 0.0)) for r in results}
            return [score_map.get(i, 0.0) for i in range(len(pairs))]
        except Exception as e:
            logger.warning("[SiliconFlowReranker] rerank 失败: %s，回退默认分数", e)
            # 回退：降序分数，保持输入顺序
            return [1.0 - (i / len(pairs)) * 0.5 for i in range(len(pairs))]
