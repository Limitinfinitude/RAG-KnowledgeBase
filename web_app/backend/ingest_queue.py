"""
异步入库队列：HTTP 仅负责校验与落盘，解析/切分/向量写入在独立线程中执行，
避免阻塞 asyncio 事件循环导致「一人上传、全站卡住」。

注意：任务状态保存在进程内存；多 worker（uvicorn --workers N）时需改为 Redis 等外部队列。
"""
from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.bytes_upload import BytesUploadFile
from utils.metadata_manager import get_all_documents
from utils.path_context import get_kb_dir, reset_kb_context, set_user_kb_context
from utils.web_system_settings import get_max_docs_per_user

from . import vdb_cache

from services.ingest import ingest_file
from utils.compliance import apply_compliance_after_staged_ingest

_MAX_JOBS_RETAINED = 400
_SENTINEL = object()

_jobs_lock = threading.Lock()
_jobs: Dict[str, "IngestJobRecord"] = {}

_pending_lock = threading.Lock()
_pending_by_user: Dict[int, int] = {}

_user_ingest_locks: Dict[int, threading.Lock] = {}
_user_locks_master = threading.Lock()

_task_queue: "queue.Queue[Any]" = queue.Queue()
_worker_thread: Optional[threading.Thread] = None
_shutdown = threading.Event()


@dataclass
class IngestJobRecord:
    job_id: str
    user_id: int
    file_name: str
    category: str
    description: str
    status: str  # queued | running | done | error
    chunks: Optional[int] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=lambda: time.time())
    finished_at: Optional[float] = None


@dataclass
class IngestTask:
    job_id: str
    user_id: int
    file_name: str
    category: str
    description: str
    staging_path: str


def _user_lock(uid: int) -> threading.Lock:
    with _user_locks_master:
        if uid not in _user_ingest_locks:
            _user_ingest_locks[uid] = threading.Lock()
        return _user_ingest_locks[uid]


def try_reserve_ingest_slot(user_id: int) -> tuple[bool, str]:
    """在已绑定用户知识库上下文的请求线程中调用。"""
    max_docs = get_max_docs_per_user()
    with _pending_lock:
        cur = len(get_all_documents())
        pend = _pending_by_user.get(user_id, 0)
        if cur + pend >= max_docs:
            return False, f"已达到单用户最大文档数限制（{max_docs}）"
        _pending_by_user[user_id] = pend + 1
        return True, ""


def release_ingest_slot(user_id: int) -> None:
    with _pending_lock:
        v = _pending_by_user.get(user_id, 0)
        if v <= 1:
            _pending_by_user.pop(user_id, None)
        else:
            _pending_by_user[user_id] = v - 1


def _prune_jobs_unlocked() -> None:
    if len(_jobs) <= _MAX_JOBS_RETAINED:
        return
    terminal = [(jid, j) for jid, j in _jobs.items() if j.status in ("done", "error")]
    terminal.sort(key=lambda x: x[1].created_at)
    for jid, _ in terminal:
        if len(_jobs) <= _MAX_JOBS_RETAINED:
            break
        _jobs.pop(jid, None)


def enqueue_staged_file(
    job_id: str,
    user_id: int,
    file_name: str,
    category: str,
    description: str,
    staging_path: str,
) -> None:
    rec = IngestJobRecord(
        job_id=job_id,
        user_id=user_id,
        file_name=file_name,
        category=category,
        description=description,
        status="queued",
    )
    with _jobs_lock:
        _jobs[job_id] = rec
        _prune_jobs_unlocked()
    _task_queue.put(
        IngestTask(
            job_id=job_id,
            user_id=user_id,
            file_name=file_name,
            category=category,
            description=description,
            staging_path=staging_path,
        )
    )


def forget_job(job_id: str) -> None:
    with _jobs_lock:
        _jobs.pop(job_id, None)


def get_job_for_user(job_id: str, user_id: int) -> Optional[IngestJobRecord]:
    with _jobs_lock:
        rec = _jobs.get(job_id)
        if rec is None or rec.user_id != user_id:
            return None
        return rec


def list_jobs_for_user(user_id: int, limit: int = 40) -> List[IngestJobRecord]:
    with _jobs_lock:
        mine = [j for j in _jobs.values() if j.user_id == user_id]
    mine.sort(key=lambda x: x.created_at, reverse=True)
    return mine[:limit]


def job_to_dict(rec: IngestJobRecord) -> Dict[str, Any]:
    return {
        "job_id": rec.job_id,
        "file_name": rec.file_name,
        "status": rec.status,
        "chunks": rec.chunks,
        "error": rec.error,
        "created_at": rec.created_at,
        "finished_at": rec.finished_at,
    }


def _update_job(job_id: str, **kwargs: Any) -> None:
    with _jobs_lock:
        rec = _jobs.get(job_id)
        if rec is None:
            return
        for k, v in kwargs.items():
            setattr(rec, k, v)


def _load_vdb_from_disk(kb_dir: str) -> Any:
    """从磁盘加载最新 FAISS（预热线程用，不复用入库的内存副本）。

    持有 faiss 写锁加载：防止读到另一写者 save_local 到一半的文件。
    """
    from langchain_community.vectorstores import FAISS

    from utils.embedding import get_embeddings
    from utils.faiss_write_lock import faiss_write_lock

    idx_dir = os.path.join(kb_dir, "faiss_index")
    if not os.path.isfile(os.path.join(idx_dir, "index.faiss")):
        return None
    with faiss_write_lock(kb_dir):
        return FAISS.load_local(
            idx_dir, embeddings=get_embeddings(), allow_dangerous_deserialization=True
        )


_prewarm_running: set = set()
_prewarm_lock = threading.Lock()


def _invalidate_and_prewarm_bm25(user_id: int) -> None:
    """入库/删除后：使 BM25 索引失效，并在后台线程预重建，消除首个用户的冷启动卡顿。

    两个正确性要点：
    1. threading.Thread 不继承 contextvars——线程内必须显式重新绑定用户上下文，
       否则 save_bm25_index 的 get_kb_dir() 会落到默认 Streamlit 目录，
       把该用户的 BM25 索引写进 Streamlit 知识库（跨用户数据污染）；
    2. 重建必须从磁盘重载最新 FAISS，不能复用本次入库的内存副本——
       若同用户的后续任务在本任务与预热执行之间完成，旧快照会把索引写回旧状态。
    """
    try:
        import logging

        from utils.hybrid_search import invalidate_bm25_index, rebuild_bm25_index

        invalidate_bm25_index()
        kb_dir = get_kb_dir()

        with _prewarm_lock:
            if user_id in _prewarm_running:
                return
            _prewarm_running.add(user_id)

        def _prewarm() -> None:
            t_kb = t_api = None
            try:
                t_kb, t_api = set_user_kb_context(user_id)
                # 已有新索引落盘说明更新的任务已完成预热，避免旧状态覆盖
                from utils.hybrid_search import _bm25_index_file

                if os.path.isfile(_bm25_index_file()):
                    return
                fresh_vdb = _load_vdb_from_disk(kb_dir)
                if fresh_vdb is None:
                    return
                rebuild_bm25_index(fresh_vdb)
            except Exception as e:  # noqa: BLE001 — 后台预热失败不应影响主流程
                logging.getLogger(__name__).warning("BM25 后台预热失败: %s", e)
            finally:
                if t_kb is not None:
                    reset_kb_context(t_kb, t_api)
                with _prewarm_lock:
                    _prewarm_running.discard(user_id)

        threading.Thread(target=_prewarm, name=f"bm25-prewarm-{user_id}", daemon=True).start()
    except Exception as e:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning("BM25 失效/预热调度失败: %s", e)


def _process_one_task(task: IngestTask) -> None:
    _update_job(task.job_id, status="running")
    t_kb, t_api = set_user_kb_context(task.user_id)
    try:
        with _user_lock(task.user_id):
            if not os.path.isfile(task.staging_path):
                raise FileNotFoundError("暂存文件已丢失，请重新上传")
            with open(task.staging_path, "rb") as f:
                data = f.read()
            buf = BytesUploadFile(task.file_name, data)
            # 私有 vdb 副本：入库会原地修改内存索引，与缓存对象（检索线程在用）共享会竞态；
            # 嵌入模型可复用（推理线程安全）。写盘由 faiss_write_lock 串行化。
            from utils.db import get_vector_db

            emb = vdb_cache.get_cached_vdb_pair(task.user_id)[1]
            vdb = get_vector_db(emb)
            n = ingest_file(
                buf,
                vdb,
                category=task.category.strip() or "默认知识库",
                description=task.description or "",
            )
            apply_compliance_after_staged_ingest(task.user_id, task.file_name, data)
            vdb_cache.bump_user_cache(task.user_id)
            _invalidate_and_prewarm_bm25(task.user_id)
        _update_job(
            task.job_id,
            status="done",
            chunks=int(n),
            finished_at=time.time(),
            error=None,
        )
    except Exception as e:
        _update_job(
            task.job_id,
            status="error",
            error=str(e),
            finished_at=time.time(),
        )
    finally:
        reset_kb_context(t_kb, t_api)
        try:
            if os.path.isfile(task.staging_path):
                os.unlink(task.staging_path)
        except OSError:
            pass
        release_ingest_slot(task.user_id)


def _worker_loop() -> None:
    while not _shutdown.is_set():
        try:
            task = _task_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        if task is _SENTINEL:
            _task_queue.task_done()
            break
        try:
            _process_one_task(task)
        finally:
            _task_queue.task_done()


def start_worker() -> None:
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    _shutdown.clear()
    _worker_thread = threading.Thread(target=_worker_loop, name="ingest-worker", daemon=True)
    _worker_thread.start()


def stop_worker() -> None:
    _shutdown.set()
    _task_queue.put(_SENTINEL)
    t = _worker_thread
    if t is not None and t.is_alive():
        t.join(timeout=5.0)
