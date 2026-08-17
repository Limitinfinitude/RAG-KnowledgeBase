"""FAISS 索引写锁：按知识库目录串行化「改内存 + save_local」的完整过程。

背景：上传入库（ingest worker 线程）、用户删除文档（FastAPI 线程池）、
管理员重置索引可能在同一用户目录上并发执行。FAISS.save_local 直接覆盖
index.faiss / index.pkl，两个写者交错会把索引写坏。

两级互斥：
1. 进程内按目录 RLock——单进程部署（默认）下的主防线；同线程可重入
   （删除的回退路径会在持锁状态下再调 get_vector_db）；
2. 目录内 .faiss_write.lock 文件锁（POSIX flock / Windows msvcrt）——
   跨进程兜底（uvicorn --workers N、Streamlit 与 Web 并存等场景）。

注意：锁文件放在知识库根目录而非 faiss_index 子目录内，因为重置/清空
索引会 rmtree(faiss_index)，不能把正在持有的锁文件删掉。

用法::

    with faiss_write_lock():            # 默认取当前上下文 get_kb_dir()
        vector_db.add_documents(docs)   # 改内存
        vector_db.save_local(index_dir) # 落盘，两者必须在同一临界区
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from typing import Dict, Iterator, Optional

logger = logging.getLogger(__name__)

LOCK_FILENAME = ".faiss_write.lock"

# 文件锁非阻塞轮询间隔（flock 阻塞模式用不到；msvcrt / 带超时路径使用）
_FILE_LOCK_POLL_SEC = 0.2

_dir_locks: Dict[str, "_DirWriteLock"] = {}
_dir_locks_master = threading.Lock()


def _try_import_fcntl():
    try:
        import fcntl  # noqa: F401  仅 POSIX

        return fcntl
    except ImportError:
        return None


class _DirWriteLock:
    """单目录写锁：RLock 排队本进程线程；最外层持锁期间额外持有文件锁。"""

    def __init__(self, lock_path: str) -> None:
        self._rlock = threading.RLock()
        self.lock_path = lock_path
        self._depth = 0
        self._file = None

    def acquire(self, timeout: Optional[float] = None) -> bool:
        # _thread.RLock 不接受 timeout=None（必须是 -1 或数值）
        got = self._rlock.acquire() if timeout is None else self._rlock.acquire(timeout=timeout)
        if not got:
            return False
        try:
            if self._depth == 0:
                os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
                f = open(self.lock_path, "a+b")
                try:
                    _lock_file_exclusive(f, self.lock_path, timeout=timeout)
                except BaseException:
                    f.close()
                    raise
                self._file = f
            self._depth += 1
            return True
        except BaseException:
            self._rlock.release()
            raise

    def release(self) -> None:
        self._depth -= 1
        try:
            if self._depth == 0 and self._file is not None:
                _unlock_file(self._file)
                self._file.close()
                self._file = None
        finally:
            self._rlock.release()


def _lock_file_exclusive(f, lock_path: str, timeout: Optional[float]) -> None:
    deadline = None if timeout is None else time.monotonic() + timeout

    fcntl = _try_import_fcntl()
    if fcntl is not None:
        if deadline is None:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            return
        while True:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError:
                _check_deadline(deadline, timeout, lock_path)

    # Windows：msvcrt 无无限阻塞模式（LK_LOCK 仅重试 10 次），改用非阻塞 + 轮询
    import msvcrt

    while True:
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            _check_deadline(deadline, timeout, lock_path)


def _check_deadline(deadline: Optional[float], timeout: Optional[float], lock_path: str) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError(f"等待 FAISS 写锁超时（{timeout}s）：{lock_path}")
    time.sleep(_FILE_LOCK_POLL_SEC)


def _unlock_file(f) -> None:
    fcntl = _try_import_fcntl()
    if fcntl is not None:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return
    import msvcrt

    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        # 进程异常退出时锁已被系统强制释放，重复解锁属无害失败
        logger.warning("释放 FAISS 文件写锁失败：%s", f.name)


@contextlib.contextmanager
def faiss_write_lock(
    kb_dir: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Iterator[None]:
    """按知识库目录获取 FAISS 写锁；默认取当前上下文目录（get_kb_dir）。

    timeout 为秒；仅在需要快速失败的场景（健康检查/测试）传入，
    正常写路径不传（大文件入库可能持锁数分钟）。
    """
    if kb_dir is None:
        from utils.path_context import get_kb_dir

        kb_dir = get_kb_dir()
    key = os.path.normcase(os.path.abspath(kb_dir))
    with _dir_locks_master:
        lk = _dir_locks.get(key)
        if lk is None:
            lk = _DirWriteLock(os.path.join(kb_dir, LOCK_FILENAME))
            _dir_locks[key] = lk
    if not lk.acquire(timeout=timeout):
        raise TimeoutError(f"等待 FAISS 写锁超时（{timeout}s）：{kb_dir}")
    try:
        yield
    finally:
        lk.release()
