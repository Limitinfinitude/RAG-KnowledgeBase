"""RAG / 即时文档：防检索片段与用户输入中的指令注入、越狱话术误导模型。"""
from __future__ import annotations

from typing import List

from langchain_core.messages import BaseMessage, SystemMessage

from utils.prompt_runtime import get_anti_injection_prefix


def prepend_to_first_system(messages: List[BaseMessage]) -> List[BaseMessage]:
    """在首条 SystemMessage 前拼接防注入段（覆盖 DB 覆盖后的模板）。"""
    out: List[BaseMessage] = []
    applied = False
    prefix = get_anti_injection_prefix()
    for m in messages:
        if not applied and isinstance(m, SystemMessage):
            c = str(m.content or "")
            out.append(SystemMessage(content=prefix + c))
            applied = True
        else:
            out.append(m)
    return out


def prepend_to_text_prompt(text: str) -> str:
    """用于单条字符串 prompt（无结构化 System 时）。"""
    return get_anti_injection_prefix() + str(text)
