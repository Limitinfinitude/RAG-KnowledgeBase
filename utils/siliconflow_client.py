"""硅基流动（SiliconFlow）API 客户端：Embedding 与 Rerank。

- SiliconFlowEmbeddings：兼容 LangChain Embeddings 接口（embed_documents / embed_query）
- SiliconFlowReranker：兼容项目 reranker 接口（predict(pairs) -> List[float]）

API 端点：
- Embedding: POST {base_url}/v1/embeddings   body: {"model", "input"}
- Rerank:    POST {base_url}/v1/rerank      body: {"model", "query", "documents", "top_n"}
"""
from __future__ import annotations

import base64
import logging
import re
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
        """重排打分；失败抛 RuntimeError（由 rerank_documents 捕获并保留原序原分）。

        不在内部回退伪造分数：1.0 递减的假分会让未重排结果绕过
        SIMILARITY_THRESHOLD 与低置信防线，掩盖 API 故障。
        """
        if not pairs:
            return []
        query = pairs[0][0] if pairs[0] else ""
        documents = [p[1] if len(p) > 1 else "" for p in pairs]
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


# DeepSeek-OCR 官方提示词（硅基流动文档 §4 PDF OCR）：grounding 版输出带版面的 markdown，
# 表格/公式还原效果最好，适合 RAG 入库
OCR_MARKDOWN_PROMPT = "<image>\n<|grounding|>Convert the document to markdown."


def _strip_markdown_wrapper(text: str) -> str:
    """去掉模型输出外层的 <markdown>…</markdown> 或 ```markdown 代码围栏。"""
    t = (text or "").strip()
    m = re.match(r"^<markdown>(.*)</markdown>$", t, re.S)
    if m:
        return m.group(1).strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:markdown)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


# grounding 版提示词会给标题/元素附坐标标注（<|ref|>…<|det|>[[x1,y1,x2,y2]]<|/det|>），
# 识别内容在标注行的下一行，标注本身对 RAG 入库是噪音，统一剔除
_GROUNDING_SPAN = re.compile(r"<\|ref\|>.*?<\|/det\|>|<\|ref\|>.*?(?=\n)|<\|det\|>.*?<\|/det\|>")


def _clean_ocr_content(text: str) -> str:
    t = _strip_markdown_wrapper(text)
    t = _GROUNDING_SPAN.sub("", t)
    t = re.sub(r"<\|/ref\|>|<\|/det\|>", "", t)
    # 压缩 3 连以上空行
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


class SiliconFlowOCR:
    """OCR：POST {base_url}/v1/chat/completions（image_url base64 + DeepSeek-OCR 提示词）。

    兼容 DeepSeek-OCR 及任何 OpenAI 视觉格式的模型（Qwen-VL 系列等），
    换模型只需改 model 名。
    """

    def __init__(self, api_key: str, model: str = "deepseek-ai/DeepSeek-OCR",
                 base_url: str = DEFAULT_BASE_URL, timeout: int = 120,
                 prompt: str = OCR_MARKDOWN_PROMPT):
        if not api_key:
            raise ValueError("硅基流动 API Key 未配置")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = int(timeout)
        self.prompt = prompt
        self._endpoint = f"{self.base_url}/v1/chat/completions"

    def extract_text(self, image_bytes: bytes, mime: str = "image/png") -> str:
        """识别单页图片字节，返回 markdown 文本；失败抛 RuntimeError（由调用方回退）。"""
        b64 = base64.b64encode(image_bytes).decode("ascii")
        resp = requests.post(
            self._endpoint,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        {"type": "text", "text": self.prompt},
                    ],
                }],
            },
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"硅基流动 OCR 请求失败 {resp.status_code}: {resp.text[:300]}")
        try:
            content = (resp.json().get("choices") or [{}])[0].get("message", {}).get("content") or ""
        except (ValueError, KeyError, IndexError) as e:
            raise RuntimeError(f"硅基流动 OCR 响应格式异常: {e}") from e
        text = _clean_ocr_content(content)
        if not text:
            raise RuntimeError("硅基流动 OCR 返回空内容")
        return text
