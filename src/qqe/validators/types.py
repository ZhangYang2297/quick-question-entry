"""校验结果类型。自修复重试与前端高亮共用同一套结构。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    severity: Severity = Severity.ERROR
    question_index: int | None = None  # 列表下标（0 基）
    field: str | None = None
