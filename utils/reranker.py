# utils/reranker.py
"""
重排序器模块
支持本地 CrossEncoder 和 Ollama 重排序模型
"""
import logging
import os
import requests
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from sentence_transformers import CrossEncoder
from utils.logger import log_retrieval, log_error

logger = logging.getLogger(__name__)

# Ollama 配置
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_RERANKER_MODEL = "qllama/bge-reranker-v2-m3:q4_k_m"

# 进程级 reranker 缓存：Web 端每请求重载模型会阻塞事件循环且极慢，
# 按 (provider, model, base_url) 缓存；配置变更换 key 自动重建
_reranker_cache: Dict[tuple, Any] = {}
_reranker_cache_lock = threading.Lock()


class OllamaReranker:
    """Ollama 重排序器"""

    # 返回的分数已是 0-1（_extract_score/_get_embedding_score/_fallback_score 均裁剪到 0-1）
    score_is_probability = True

    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = OLLAMA_RERANKER_MODEL):
        # 注意：本实现从自由文本中抓数字当分数、逐 pair 串行 HTTP，分数可靠性有限，
        # 已不推荐使用（保留仅为兼容）；建议切换云端 rerank 或本地 CrossEncoder。
        logger.warning("[Reranker] OllamaReranker 为遗留实现，分数可靠性有限，建议改用云端/本地重排")
        self.base_url = base_url
        self.model = model
        self.api_url = f"{base_url}/api/generate"
        self.embeddings_url = f"{base_url}/api/embeddings"
    
    def predict(self, pairs: List[List[str]]) -> List[float]:
        """
        对查询-文档对进行重排序
        :param pairs: [[query, doc], ...] 格式的列表
        :return: 分数列表
        """
        try:
            scores = []
            for query, doc in pairs:
                try:
                    # 方法1：尝试使用 embeddings API 获取向量，然后计算相似度
                    # 对于 reranker 模型，可能需要构造特定的 prompt
                    prompt = f"Query: {query}\nDocument: {doc[:500]}\nRelevance score:"
                    
                    # 尝试使用 generate API（如果模型支持）
                    response = requests.post(
                        self.api_url,
                        json={
                            "model": self.model,
                            "prompt": prompt,
                            "stream": False,
                            "options": {
                                "temperature": 0.0,
                                "num_predict": 10  # 只生成分数部分
                            }
                        },
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        text = result.get("response", "").strip()
                        # 尝试从响应中提取分数
                        score = self._extract_score(text, query, doc)
                        scores.append(score)
                    else:
                        # 如果 generate 失败，尝试 embeddings
                        score = self._get_embedding_score(query, doc)
                        scores.append(score)
                        
                except Exception as e:
                    # 如果所有方法都失败，使用备用方法
                    scores.append(self._fallback_score(query, doc))
            
            return scores
        except Exception as e:
            log_error("reranker_ollama", str(e), {"model": self.model})
            # 返回默认分数
            return [0.5] * len(pairs)
    
    def _get_embedding_score(self, query: str, doc: str) -> float:
        """使用 embeddings API 计算相似度"""
        try:
            # 获取查询和文档的 embeddings
            query_emb = requests.post(
                self.embeddings_url,
                json={"model": self.model, "prompt": query},
                timeout=30
            )
            doc_emb = requests.post(
                self.embeddings_url,
                json={"model": self.model, "prompt": doc[:1000]},  # 增加文档长度限制
                timeout=30
            )
            
            if query_emb.status_code == 200 and doc_emb.status_code == 200:
                q_data = query_emb.json()
                d_data = doc_emb.json()
                
                q_vec = q_data.get("embedding", [])
                d_vec = d_data.get("embedding", [])
                
                if q_vec and d_vec and len(q_vec) == len(d_vec):
                    # 计算余弦相似度
                    dot_product = sum(a * b for a, b in zip(q_vec, d_vec))
                    q_norm = sum(a * a for a in q_vec) ** 0.5
                    d_norm = sum(b * b for b in d_vec) ** 0.5
                    if q_norm > 0 and d_norm > 0:
                        cosine_sim = float(dot_product / (q_norm * d_norm))
                        # 归一化到 0-1 范围（余弦相似度范围是 -1 到 1）
                        normalized_score = (cosine_sim + 1) / 2
                        return max(0.0, min(1.0, normalized_score))
        except Exception as e:
            log_error("reranker_ollama_embedding", str(e), {"query": query[:50]})
        return self._fallback_score(query, doc)
    
    def _extract_score(self, text: str, query: str, doc: str) -> float:
        """从模型响应中提取分数"""
        try:
            # 尝试提取数字分数
            import re
            numbers = re.findall(r'\d+\.?\d*', text)
            if numbers:
                score = float(numbers[0])
                # 归一化到 0-1 范围
                if score > 1:
                    score = score / 100.0 if score <= 100 else 1.0
                return max(0.0, min(1.0, score))
        except:
            pass
        return self._fallback_score(query, doc)
    
    def _fallback_score(self, query: str, doc: str) -> float:
        """备用评分方法（基于文本相似度）"""
        # 改进的关键词匹配评分
        query_words = set(query.lower().split())
        doc_lower = doc.lower()
        doc_words = set(doc_lower.split())
        
        if not query_words:
            return 0.0
        
        # 计算关键词重叠
        overlap = len(query_words & doc_words)
        
        # 计算部分匹配（包含关系）
        partial_match = sum(1 for word in query_words if word in doc_lower)
        
        # 综合评分
        base_score = overlap / len(query_words) if query_words else 0.0
        partial_score = partial_match / len(query_words) if query_words else 0.0
        
        # 加权平均
        final_score = (base_score * 0.7 + partial_score * 0.3)
        return min(final_score, 1.0)


def get_reranker(use_ollama: bool = False, ollama_base_url: str = None, ollama_model: str = None):
    """
    获取重排序器
    :param use_ollama: 是否使用 Ollama
    :param ollama_base_url: Ollama 服务地址
    :param ollama_model: Ollama 模型名称
    :return: 重排序器实例
    """
    if use_ollama:
        base_url = ollama_base_url or OLLAMA_BASE_URL
        model = ollama_model or OLLAMA_RERANKER_MODEL
        return OllamaReranker(base_url=base_url, model=model)

    # 云端重排序（OpenAI 兼容 /v1/rerank）
    from utils.web_system_settings import get_rerank_config

    cfg = get_rerank_config()
    if cfg["provider_type"] != "local":
        from utils.siliconflow_client import SiliconFlowReranker

        logger.info("[Reranker] 使用云端重排序模型 %s（provider=%s）", cfg["model"], cfg["provider"])
        return SiliconFlowReranker(api_key=cfg["api_key"], model=cfg["model"], base_url=cfg["base_url"])

    # 使用本地 CrossEncoder
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    local_reranker_path = os.path.join(project_root, "models", "bge-reranker-base_local")

    try:
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        device = "cpu"

    if os.path.exists(local_reranker_path):
        logger.info("[Reranker] 使用本地 reranker: %s", local_reranker_path)
        return CrossEncoder(local_reranker_path, device=device)
    else:
        logger.info("[Reranker] 本地 reranker 不存在，正在从 Hugging Face 下载 BAAI/bge-reranker-base ...")
        logger.info("（约 1GB，第一次运行较慢，后续离线使用）")

        model = CrossEncoder("BAAI/bge-reranker-base")
        os.makedirs(local_reranker_path, exist_ok=True)
        model.save(local_reranker_path)
        logger.info("[Reranker] 下载完成，已保存到: %s", local_reranker_path)

        return CrossEncoder(local_reranker_path, device=device)


def get_cached_reranker():
    """带进程级缓存的 get_reranker（Web 端入口统一用这个）。

    构造可能很慢（加载本地模型/下载），调用方应放在 asyncio.to_thread 里执行；
    失败会抛异常（调用方记录日志并降级为不重排），不再静默。
    """
    from utils.web_system_settings import get_rerank_config

    cfg = get_rerank_config()
    key = (str(cfg.get("provider")), str(cfg.get("model")), str(cfg.get("base_url")))
    with _reranker_cache_lock:
        cached = _reranker_cache.get(key)
    if cached is not None:
        return cached
    inst = get_reranker()  # 慢构造放锁外，避免阻塞其它请求
    with _reranker_cache_lock:
        _reranker_cache[key] = inst
    return inst


def rerank_documents(
    query: str,
    documents: List,
    reranker,
    top_k: int = 3,
    reranker_type: str = "local",
    fallback_scores: Optional[List[float]] = None,
) -> List[Tuple]:
    """
    重排序文档
    :param query: 查询文本
    :param documents: 文档列表
    :param reranker: 重排序器实例
    :param top_k: 返回前 k 个结果
    :param reranker_type: 重排序器类型
    :param fallback_scores: 重排失败时沿用的原始检索分数（保持原序原分，
        不伪造高分——伪高分会让未重排结果绕过 SIMILARITY_THRESHOLD 与低置信防线）
    :return: 排序后的文档和分数列表（分数已归一化到0-1）
    """
    if not documents:
        return []

    start_time = time.perf_counter()

    try:
        # 构建查询-文档对
        pairs = [[query, doc.page_content if hasattr(doc, "page_content") else str(doc)]
                 for doc in documents]

        # 获取分数（CrossEncoder 返回 logits；硅基流动 rerank 返回 0-1 概率，见 score_is_probability 标记）
        scores = reranker.predict(pairs)

        # 调试信息：原始分数
        logger.debug("[Reranker] 类型: %s, 文档数: %d", reranker_type, len(documents))
        logger.debug("[Reranker] 原始分数范围: min=%.4f, max=%.4f, avg=%.4f", min(scores), max(scores), sum(scores)/len(scores))

        if getattr(reranker, "score_is_probability", False):
            # 分数已是 0-1 概率（硅基流动 / Ollama），直接裁剪，无需 sigmoid
            normalized_scores = [max(0.0, min(1.0, float(s))) for s in scores]
        else:
            # 本地 CrossEncoder 返回 logits（约 -10~10），用 sigmoid 转 0-1 概率
            import math

            normalized_scores = [1 / (1 + math.exp(-score)) for score in scores]

        # 排序
        scored_docs = sorted(zip(documents, normalized_scores), key=lambda x: x[1], reverse=True)

        rerank_time = time.perf_counter() - start_time

        # 记录日志
        log_retrieval(
            query=query,
            initial_count=len(documents),
            reranked_count=len(scored_docs),
            rerank_time=rerank_time,
            reranker_type=reranker_type
        )

        return scored_docs[:top_k]
    except Exception as e:
        log_error("reranker_error", str(e), {"query": query[:50], "doc_count": len(documents)})
        logger.exception("[Reranker] 重排失败，保留原序原分: %s", e)
        # 保留输入顺序与原始检索分（无原始分则 0.0 → 上层低置信分支正确触发）
        n = min(top_k, len(documents))
        if fallback_scores is not None and len(fallback_scores) >= n:
            return [(documents[i], float(fallback_scores[i])) for i in range(n)]
        return [(documents[i], 0.0) for i in range(n)]

