"""
请求级知识库路径上下文：Streamlit 默认用本地目录；Web 每用户独立 knowledge_db。
配合 contextvars，支持 asyncio 下多用户并发互不干扰。
"""
from __future__ import annotations

import os
from contextvars import ContextVar, Token
from typing import Optional

_kb_dir_var: ContextVar[Optional[str]] = ContextVar("kb_dir", default=None)
_use_web_server_api_config: ContextVar[bool] = ContextVar("use_web_server_api_config", default=False)


def get_kb_dir() -> str:
    """当前上下文知识库根目录（含 faiss_index、metadata、bm25 等）。"""
    override = _kb_dir_var.get()
    if override:
        return override
    from config import STREAMLIT_KB_DIR

    return STREAMLIT_KB_DIR


def get_api_config_dir() -> str:
    """api_config.json 所在目录：线上为全局 server 目录；Streamlit 为本地知识库目录。"""
    if _use_web_server_api_config.get():
        from config import WEB_SERVER_DIR

        os.makedirs(WEB_SERVER_DIR, exist_ok=True)
        return WEB_SERVER_DIR
    return get_kb_dir()


def set_user_kb_context(user_id: int) -> tuple[Token, Token]:
    """Web：绑定当前请求到某用户的知识库 + 使用全局 server API 配置。"""
    from config import WEB_USERS_ROOT

    kb = os.path.join(WEB_USERS_ROOT, str(int(user_id)), "knowledge_db")
    os.makedirs(kb, exist_ok=True)
    t_kb = _kb_dir_var.set(kb)
    t_api = _use_web_server_api_config.set(True)
    return t_kb, t_api


def reset_kb_context(t_kb: Token, t_api: Token) -> None:
    _kb_dir_var.reset(t_kb)
    _use_web_server_api_config.reset(t_api)


def get_current_web_user_id() -> Optional[int]:
    """从当前知识库路径解析 Web 用户 id；Streamlit 等非 Web 多用户上下文返回 None。"""
    kb = (get_kb_dir() or "").replace("\\", "/").rstrip("/")
    marker = "/users/"
    if marker not in kb:
        return None
    try:
        after = kb.split(marker, 1)[1]
        seg = after.split("/", 1)[0]
        return int(seg)
    except (ValueError, IndexError):
        return None
