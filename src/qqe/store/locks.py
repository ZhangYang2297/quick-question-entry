"""项目级串行锁。

**为什么必须有**：续加是「读项目 → 追加到末尾 → 整表重写」的复合操作。
两个请求同时进来，后写的那次会带着旧的题目清单覆盖前一次 —— 用户看到的
就是"其中一批题凭空消失"。锁的粒度定在**项目**，不同项目互不阻塞。

用可重入锁（RLock）：`duplicate_project` 内部会再取源项目的锁读一次数据。
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class ProjectLocks:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}

    def _lock_for(self, project_id: str) -> threading.RLock:
        with self._guard:
            lock = self._locks.get(project_id)
            if lock is None:
                lock = threading.RLock()
                self._locks[project_id] = lock
            return lock

    @contextmanager
    def hold(self, project_id: str) -> Iterator[None]:
        lock = self._lock_for(project_id)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    @contextmanager
    def hold_all(self, project_ids: list[str]) -> Iterator[None]:
        """按 id 字典序取多把锁，避免两个请求交叉加锁造成死锁。"""
        acquired: list[threading.RLock] = []
        try:
            for project_id in sorted(set(project_ids)):
                lock = self._lock_for(project_id)
                lock.acquire()
                acquired.append(lock)
            yield
        finally:
            for lock in reversed(acquired):
                lock.release()

    def active_project_count(self) -> int:
        return len(self._locks)
