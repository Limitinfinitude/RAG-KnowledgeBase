"""FAISS 写锁（utils/faiss_write_lock）单测：重入、线程互斥、跨进程互斥。

不依赖 FAISS / langchain，子进程仅导入锁模块本身（保持轻量导入正是模块的设计约束）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

import pytest

from utils.faiss_write_lock import LOCK_FILENAME, faiss_write_lock

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_CHILD_HOLDER = f"""
import sys, time
sys.path.insert(0, r"{_PROJECT_ROOT}")
from utils.faiss_write_lock import faiss_write_lock
with faiss_write_lock(sys.argv[1]):
    print("LOCKED", flush=True)
    time.sleep(3)
"""


def test_lock_file_created_and_reentrant(tmp_path):
    with faiss_write_lock(str(tmp_path)):
        assert (tmp_path / LOCK_FILENAME).is_file()
        # 同线程重入（删除回退路径会在持锁时再调 get_vector_db）
        with faiss_write_lock(str(tmp_path), timeout=5):
            pass


def test_thread_mutual_exclusion(tmp_path):
    events = []
    holder_ready = threading.Event()
    holder_may_release = threading.Event()

    def holder():
        with faiss_write_lock(str(tmp_path)):
            events.append("holder-acquired")
            holder_ready.set()
            holder_may_release.wait(timeout=10)
            events.append("holder-released")

    def waiter():
        with faiss_write_lock(str(tmp_path), timeout=30):
            events.append("waiter-acquired")

    t1 = threading.Thread(target=holder)
    t1.start()
    assert holder_ready.wait(timeout=10)
    t2 = threading.Thread(target=waiter)
    t2.start()
    time.sleep(0.5)
    assert "waiter-acquired" not in events, "持锁期间其它线程不应获得锁"

    holder_may_release.set()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert not t1.is_alive() and not t2.is_alive()
    assert events == ["holder-acquired", "holder-released", "waiter-acquired"]


def test_thread_acquire_timeout(tmp_path):
    held = threading.Event()

    def holder():
        with faiss_write_lock(str(tmp_path)):
            held.set()
            time.sleep(1.5)

    t = threading.Thread(target=holder)
    t.start()
    assert held.wait(timeout=10)
    with pytest.raises(TimeoutError):
        with faiss_write_lock(str(tmp_path), timeout=0.2):
            pass
    t.join(timeout=10)


def test_cross_process_exclusion(tmp_path):
    """子进程持锁 3 秒：父进程带超时获取应超时，待子进程退出后应成功获取。"""
    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD_HOLDER, str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        first_line = proc.stdout.readline()
        assert "LOCKED" in first_line, f"子进程未成功持锁: {first_line}"

        with pytest.raises(TimeoutError):
            with faiss_write_lock(str(tmp_path), timeout=1.0):
                pass

        # 子进程 3 秒后自动退出释放锁，这里阻塞等待并成功获取
        with faiss_write_lock(str(tmp_path), timeout=30):
            pass
    finally:
        proc.wait(timeout=30)


def test_different_dirs_do_not_block(tmp_path):
    a, b = tmp_path / "user_a", tmp_path / "user_b"
    with faiss_write_lock(str(a)):
        with faiss_write_lock(str(b), timeout=5):
            pass  # 不同用户目录互不阻塞
