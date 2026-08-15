# utils/token_tracker.py
"""
Token使用追踪工具
从LangChain的response中提取token使用信息
"""
from typing import Dict, Optional
from langchain_core.messages import BaseMessage
from utils.logger import log_token_usage
from utils.api_config import get_current_config


def extract_token_usage(response) -> Optional[Dict[str, int]]:
    """
    从LangChain response中提取token使用信息
    返回: {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int} 或 None
    """
    try:
        # LangChain的ChatOpenAI返回的response有response_metadata
        if hasattr(response, 'response_metadata'):
            metadata = response.response_metadata
            if metadata and 'token_usage' in metadata:
                usage = metadata['token_usage']
                return {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0)
                }
        
        # 如果是dict类型
        if isinstance(response, dict):
            if 'response_metadata' in response:
                metadata = response['response_metadata']
                if metadata and 'token_usage' in metadata:
                    usage = metadata['token_usage']
                    return {
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0)
                    }
        
        # 尝试从usage字段直接获取
        if hasattr(response, 'usage'):
            usage = response.usage
            if usage:
                return {
                    "prompt_tokens": getattr(usage, 'prompt_tokens', 0),
                    "completion_tokens": getattr(usage, 'completion_tokens', 0),
                    "total_tokens": getattr(usage, 'total_tokens', 0)
                }
    except Exception as e:
        print(f"提取token使用信息失败: {e}")
    
    return None


def track_token_usage(
    response,
    model: Optional[str] = None,
    call_type: str = "qa",
    user_id: Optional[int] = None,
):
    """
    追踪并记录token使用
    :param response: LangChain的response对象
    :param model: 模型名称，如果为None则从配置中获取
    :param call_type: 调用类型（qa, rephrase, chat等）
    :param user_id: Web 多用户模式下可选，写入统计便于按账号汇总
    :return: usage字典或None
    """
    usage = extract_token_usage(response)
    if usage:
        if model is None:
            try:
                api_config = get_current_config()
                model = api_config.get("model", "unknown")
            except Exception:
                model = "unknown"
        
        log_token_usage(
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            total_tokens=usage["total_tokens"],
            model=model,
            call_type=call_type,
            user_id=user_id,
        )
        
        return usage
    return None

