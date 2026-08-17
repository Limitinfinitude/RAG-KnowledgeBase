import logging
import os
from typing import Optional

from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


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
    """根据当前 API 配置构造 ChatOpenAI（不依赖 Streamlit）。config_name 指定预设名。

    配置读取失败或配置不完整时立即抛错并记日志，不再静默回退空 key 的客户端——
    那会把配置错误推迟到对话调用时才爆 401，难以排查。调用方（Web 端点、
    查询分类器、摘要器）均已有 try/except 或规则回退。
    """
    try:
        from utils.api_config import get_api_config_for

        api_config = get_api_config_for(config_name)
    except Exception as e:
        logger.exception("build_chat_llm: 读取 LLM API 配置失败（config_name=%r）", config_name)
        raise RuntimeError(f"读取 LLM API 配置失败: {e}") from e

    model = str(api_config.get("model") or "").strip()
    api_key = str(api_config.get("api_key") or "").strip()
    base_url = str(api_config.get("base_url") or "").strip()
    if not model or not api_key or not base_url:
        raise RuntimeError(
            "LLM API 配置不完整（"
            f"model={model or '未设置'}, api_key={'已配置' if api_key else '缺失'}, "
            f"base_url={base_url or '未设置'}），请在管理端「检索设置 → 模型 API」完成配置"
        )

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        use_responses_api=False,
        streaming=True,
        timeout=_default_llm_timeout_sec(),
    )
