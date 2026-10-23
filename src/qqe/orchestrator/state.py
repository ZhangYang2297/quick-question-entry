"""批次状态机。

为什么要有状态机：续加模式下「这一批有没有真的并入项目」是**语义分界线**。
- 只有走到 `MERGED`，这批题目才算进了项目，才允许导出；
- 没 `MERGED` 的批次是草稿，`DISCARDED` 掉不影响项目里已有的任何题目；
- `DONE` 只表示"渲染完成"，不是并入的前提 —— 先并入再渲染。

状态迁移是白名单制：不在表里的迁移一律拒绝，避免出现
"解析失败还去渲染"这种靠 if 兜不住的乱序。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class BatchState(StrEnum):
    PENDING = "pending"
    PREPROCESSING = "preprocessing"
    PARSING = "parsing"
    NEEDS_REVIEW = "needs_review"
    MERGED = "merged"
    RENDERING = "rendering"
    DONE = "done"
    FAILED = "failed"
    DISCARDED = "discarded"


# 白名单：左 → 右。终态（DONE / DISCARDED）没有出边。
TRANSITIONS: dict[BatchState, frozenset[BatchState]] = {
    BatchState.PENDING: frozenset(
        {BatchState.PREPROCESSING, BatchState.FAILED, BatchState.DISCARDED}
    ),
    BatchState.PREPROCESSING: frozenset({BatchState.PARSING, BatchState.FAILED}),
    BatchState.PARSING: frozenset({BatchState.NEEDS_REVIEW, BatchState.FAILED}),
    BatchState.NEEDS_REVIEW: frozenset(
        {BatchState.MERGED, BatchState.DISCARDED, BatchState.FAILED}
    ),
    BatchState.MERGED: frozenset({BatchState.RENDERING, BatchState.FAILED}),
    BatchState.RENDERING: frozenset({BatchState.DONE, BatchState.FAILED}),
    BatchState.DONE: frozenset(),
    BatchState.FAILED: frozenset({BatchState.DISCARDED}),
    BatchState.DISCARDED: frozenset(),
}

# 只有已并入项目（或并入之后继续走）的批次才允许导出
EXPORTABLE_STATES = frozenset({BatchState.MERGED, BatchState.RENDERING, BatchState.DONE})


class IllegalTransition(RuntimeError):
    """非法状态迁移，或在不允许的状态下执行了需要前置状态的操作。"""


@dataclass
class BatchStateMachine:
    state: BatchState = BatchState.PENDING
    failure_reason: str | None = None
    history: list[BatchState] = field(default_factory=lambda: [BatchState.PENDING])

    def can_transition(self, target: BatchState) -> bool:
        return target in TRANSITIONS[self.state]

    def transition(self, target: BatchState) -> BatchState:
        if not self.can_transition(target):
            raise IllegalTransition(f"非法状态迁移：{self.state} → {target}")
        self.state = target
        self.history.append(target)
        return self.state

    def fail(self, reason: str) -> BatchState:
        """进入 FAILED 并保留原因；FAILED 不可再恢复（重试是新批次）。"""
        if not self.can_transition(BatchState.FAILED):
            raise IllegalTransition(f"当前状态 {self.state} 不允许标记失败")
        self.failure_reason = reason
        return self.transition(BatchState.FAILED)

    def discard(self) -> BatchState:
        """放弃草稿批次：只丢这一批的解析结果，项目已有题目不受影响。"""
        return self.transition(BatchState.DISCARDED)

    def ensure_exportable(self) -> None:
        if self.state not in EXPORTABLE_STATES:
            raise IllegalTransition(
                f"批次尚未并入项目（当前 {self.state}），不能导出；"
                "只有 merged / rendering / done 允许导出"
            )

    @property
    def is_terminal(self) -> bool:
        return not TRANSITIONS[self.state]
