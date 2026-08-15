import os
from typing import Optional

from langchain_openai import ChatOpenAI


def _default_llm_timeout_sec() -> Optional[int]:
    raw = (os.environ.get("RAG_LLM_TIMEOUT_SEC") or "").strip()
    if not raw:
        return 180
    try:
        return max(5, int(raw))
    except ValueError:
        return 180


def build_chat_openai_explicit(
    *,
    model: str,
    api_key: str,
    base_url: str,
    temperature: float = 0.0,
    timeout: Optional[int] = None,
) -> ChatOpenAI:
    """使用显式参数构造客户端（如「模型设置」页连接测试，不读持久化配置）。"""
    kwargs = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
        "use_responses_api": False,
    }
    kwargs["timeout"] = timeout if timeout is not None else _default_llm_timeout_sec()
    kwargs["streaming"] = True
    return ChatOpenAI(**kwargs)


def build_chat_llm(temperature: float, *, config_name: str | None = None) -> ChatOpenAI:
    """根据当前 API 配置构造 ChatOpenAI（不依赖 Streamlit）。config_name 指定 api_config.json 中的预设名。"""
    try:
        from utils.api_config import get_api_config_for

        api_config = get_api_config_for(config_name)
        return ChatOpenAI(
            model=api_config.get("model", "deepseek-chat"),
            api_key=api_config.get("api_key", ""),
            base_url=api_config.get("base_url", "https://api.deepseek.com"),
            temperature=temperature,
            use_responses_api=False,
            streaming=True,
            timeout=_default_llm_timeout_sec(),
        )
    except Exception:
        return ChatOpenAI(
            model="deepseek-chat",
            api_key="",
            base_url="https://api.deepseek.com",
            temperature=temperature,
            use_responses_api=False,
            streaming=True,
            timeout=_default_llm_timeout_sec(),
        )
