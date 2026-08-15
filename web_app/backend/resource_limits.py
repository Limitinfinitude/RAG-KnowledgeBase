"""异步路径上的并发槽位，避免检索+LLM 同步代码拖死事件循环、CPU/内存被瞬时打满。"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import HTTPException

_sem: Optional[asyncio.Semaphore] = None


def _chat_concurrency_limit() -> int:
    return max(1, int(os.environ.get("RAG_MAX_CONCURRENT_CHAT", "8")))


def rag_chat_semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(_chat_concurrency_limit())
    return _sem


def reset_rag_chat_semaphore_for_tests() -> None:
    """仅测试用：更换并发上限前清空单例。"""
    global _sem
    _sem = None


@asynccontextmanager
async def rag_chat_slot() -> AsyncIterator[None]:
    """
    包裹一轮知识库/即时文档对话（含流式整段输出期间持锁）。
    RAG_CHAT_ACQUIRE_TIMEOUT_SEC>0 时，排队超时返回 503。
    """
    sem = rag_chat_semaphore()
    wait_s = (os.environ.get("RAG_CHAT_ACQUIRE_TIMEOUT_SEC") or "").strip()
    if wait_s:
        try:
            await asyncio.wait_for(sem.acquire(), timeout=float(wait_s))
        except asyncio.TimeoutError:
            raise HTTPException(status_code=503, detail="服务器繁忙，请稍后重试") from None
    else:
        await sem.acquire()
    try:
        yield
    finally:
        sem.release()
