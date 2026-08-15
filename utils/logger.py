# utils/logger.py
"""
日志系统
记录系统操作、错误和统计信息
"""
import os
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from config import STREAMLIT_KB_DIR

# 文件日志固定落在 Streamlit 本地知识库侧（避免 Web 未设上下文时写错目录）
LOG_DIR = os.path.join(STREAMLIT_KB_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "system.log")
STATS_FILE = os.path.join(STREAMLIT_KB_DIR, "statistics.json")

# 确保日志目录存在
os.makedirs(LOG_DIR, exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def log_query(query: str, intent: str, response_time: float, 
              retrieved_docs: int = 0, llm_calls: int = 0,
              prompt_tokens: int = 0, completion_tokens: int = 0, total_tokens: int = 0):
    """记录查询日志"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "type": "query",
        "query": query,
        "intent": intent,
        "response_time": response_time,
        "retrieved_docs": retrieved_docs,
        "llm_calls": llm_calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens
    }
    logger.info(f"Query: {query[:50]}... | Intent: {intent} | Time: {response_time:.2f}s | Tokens: {total_tokens}")
    _append_to_stats("queries", log_entry)


def log_token_usage(
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    model: str = "unknown",
    call_type: str = "qa",
    user_id: Optional[int] = None,
    *,
    latency_ms: Optional[float] = None,
    api_path: Optional[str] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    session_id: Optional[int] = None,
):
    """记录token使用情况"""
    log_entry: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "type": "token_usage",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "model": model,
        "call_type": call_type,  # qa, rephrase, chat等
    }
    if user_id is not None:
        log_entry["user_id"] = int(user_id)
    if latency_ms is not None:
        log_entry["latency_ms"] = float(latency_ms)
    if api_path:
        log_entry["api_path"] = str(api_path)[:256]
    if not success:
        log_entry["success"] = False
    if error_message:
        log_entry["error_message"] = str(error_message)[:2000]
    if session_id is not None:
        log_entry["session_id"] = int(session_id)
    logger.info(f"Token Usage: {total_tokens} (prompt: {prompt_tokens}, completion: {completion_tokens}) | Model: {model}")
    _append_to_stats("token_usage", log_entry)
    try:
        from utils.llm_log_store import insert_llm_call_log_best_effort

        insert_llm_call_log_best_effort(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            model=model,
            call_type=call_type,
            user_id=user_id,
            session_id=session_id,
            latency_ms=latency_ms,
            api_path=api_path,
            success=success,
            error_message=error_message,
        )
    except Exception:
        pass


def log_retrieval(query: str, initial_count: int, reranked_count: int, 
                 rerank_time: float, reranker_type: str = "local"):
    """记录检索日志"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "type": "retrieval",
        "query": query[:100],
        "initial_count": initial_count,
        "reranked_count": reranked_count,
        "rerank_time": rerank_time,
        "reranker_type": reranker_type
    }
    logger.info(f"Retrieval: {initial_count} -> {reranked_count} docs | Time: {rerank_time:.2f}s | Type: {reranker_type}")
    _append_to_stats("retrievals", log_entry)


def log_error(error_type: str, error_message: str, context: Optional[Dict] = None):
    """记录错误日志"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "type": "error",
        "error_type": error_type,
        "error_message": error_message,
        "context": context or {}
    }
    logger.error(f"Error [{error_type}]: {error_message}")
    _append_to_stats("errors", log_entry)


def log_file_upload(file_name: str, file_size: int, chunks: int, category: str):
    """记录文件上传日志"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "type": "upload",
        "file_name": file_name,
        "file_size": file_size,
        "chunks": chunks,
        "category": category
    }
    logger.info(f"Upload: {file_name} | Size: {file_size} bytes | Chunks: {chunks} | Category: {category}")
    _append_to_stats("uploads", log_entry)


def log_file_delete(file_name: str, chunks_deleted: int):
    """记录文件删除日志"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "type": "delete",
        "file_name": file_name,
        "chunks_deleted": chunks_deleted
    }
    logger.info(f"Delete: {file_name} | Chunks deleted: {chunks_deleted}")
    _append_to_stats("deletes", log_entry)


def _append_to_stats(category: str, entry: Dict):
    """追加统计信息到文件"""
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                stats = json.load(f)
        else:
            stats = {
                "queries": [],
                "retrievals": [],
                "errors": [],
                "uploads": [],
                "deletes": [],
                "token_usage": []
            }
        
        if category not in stats:
            stats[category] = []
        
        stats[category].append(entry)
        
        # 只保留最近1000条记录
        if len(stats[category]) > 1000:
            stats[category] = stats[category][-1000:]
        
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save stats: {e}")


def get_recent_logs(category: str = None, limit: int = 100) -> List[Dict]:
    """获取最近的日志"""
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                stats = json.load(f)
            
            if category:
                return stats.get(category, [])[-limit:]
            else:
                # 合并所有类别
                all_logs = []
                for cat in ["queries", "retrievals", "errors", "uploads", "deletes", "token_usage"]:
                    all_logs.extend(stats.get(cat, []))
                # 按时间排序
                all_logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
                return all_logs[:limit]
        return []
    except Exception as e:
        logger.error(f"Failed to load logs: {e}")
        return []


def get_statistics() -> Dict:
    """获取统计信息"""
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                stats = json.load(f)
        else:
            stats = {
                "queries": [],
                "retrievals": [],
                "errors": [],
                "uploads": [],
                "deletes": [],
                "token_usage": []
            }
        
        # 计算统计
        total_queries = len(stats.get("queries", []))
        total_retrievals = len(stats.get("retrievals", []))
        total_errors = len(stats.get("errors", []))
        total_uploads = len(stats.get("uploads", []))
        total_deletes = len(stats.get("deletes", []))
        
        # 平均响应时间
        queries = stats.get("queries", [])
        avg_response_time = sum(q.get("response_time", 0) for q in queries) / len(queries) if queries else 0
        
        # 平均重排序时间
        retrievals = stats.get("retrievals", [])
        avg_rerank_time = sum(r.get("rerank_time", 0) for r in retrievals) / len(retrievals) if retrievals else 0
        
        # 意图分布
        intent_dist = {}
        for q in queries:
            intent = q.get("intent", "UNKNOWN")
            intent_dist[intent] = intent_dist.get(intent, 0) + 1
        
        # 重排序器类型分布
        reranker_dist = {}
        for r in retrievals:
            r_type = r.get("reranker_type", "unknown")
            reranker_dist[r_type] = reranker_dist.get(r_type, 0) + 1
        
        # Token统计
        token_logs = stats.get("token_usage", [])
        total_prompt_tokens = sum(t.get("prompt_tokens", 0) for t in token_logs)
        total_completion_tokens = sum(t.get("completion_tokens", 0) for t in token_logs)
        total_tokens = sum(t.get("total_tokens", 0) for t in token_logs)
        
        # 按模型统计token
        model_token_stats = {}
        for t in token_logs:
            model = t.get("model", "unknown")
            if model not in model_token_stats:
                model_token_stats[model] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "calls": 0
                }
            model_token_stats[model]["prompt_tokens"] += t.get("prompt_tokens", 0)
            model_token_stats[model]["completion_tokens"] += t.get("completion_tokens", 0)
            model_token_stats[model]["total_tokens"] += t.get("total_tokens", 0)
            model_token_stats[model]["calls"] += 1

        user_token_stats: Dict[str, Dict[str, Any]] = {}
        for t in token_logs:
            raw_uid = t.get("user_id")
            ukey = "_unset"
            if raw_uid is not None:
                try:
                    ukey = str(int(raw_uid))
                except (TypeError, ValueError):
                    ukey = "_unset"
            if ukey not in user_token_stats:
                user_token_stats[ukey] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "calls": 0,
                }
            user_token_stats[ukey]["prompt_tokens"] += t.get("prompt_tokens", 0)
            user_token_stats[ukey]["completion_tokens"] += t.get("completion_tokens", 0)
            user_token_stats[ukey]["total_tokens"] += t.get("total_tokens", 0)
            user_token_stats[ukey]["calls"] += 1
        
        # 估算费用（基于常见模型价格，单位：元）
        # DeepSeek: $0.14/$0.28 per 1M tokens (input/output)
        # OpenAI GPT-4: $30/$60 per 1M tokens
        # OpenAI GPT-3.5: $0.5/$1.5 per 1M tokens
        estimated_cost = 0.0
        for model, stats_data in model_token_stats.items():
            if "deepseek" in model.lower():
                cost = (stats_data["prompt_tokens"] * 0.14 / 1_000_000) + (stats_data["completion_tokens"] * 0.28 / 1_000_000)
                estimated_cost += cost * 7.2  # 汇率约7.2
            elif "gpt-4" in model.lower():
                cost = (stats_data["prompt_tokens"] * 30 / 1_000_000) + (stats_data["completion_tokens"] * 60 / 1_000_000)
                estimated_cost += cost * 7.2
            elif "gpt-3.5" in model.lower() or "gpt-35" in model.lower():
                cost = (stats_data["prompt_tokens"] * 0.5 / 1_000_000) + (stats_data["completion_tokens"] * 1.5 / 1_000_000)
                estimated_cost += cost * 7.2
            else:
                # 默认使用DeepSeek价格
                cost = (stats_data["prompt_tokens"] * 0.14 / 1_000_000) + (stats_data["completion_tokens"] * 0.28 / 1_000_000)
                estimated_cost += cost * 7.2
        
        return {
            "total_queries": total_queries,
            "total_retrievals": total_retrievals,
            "total_errors": total_errors,
            "total_uploads": total_uploads,
            "total_deletes": total_deletes,
            "avg_response_time": round(avg_response_time, 2),
            "avg_rerank_time": round(avg_rerank_time, 3),
            "intent_distribution": intent_dist,
            "reranker_distribution": reranker_dist,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "model_token_stats": model_token_stats,
            "user_token_stats": user_token_stats,
            "token_usage_calls": len(token_logs),
            "estimated_cost": round(estimated_cost, 4),
            "last_updated": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get statistics: {e}")
        return {}

