"""文档项目：可续加的题目集合、批次记录与服务层。"""

from __future__ import annotations

from qqe.project.document import (
    PROJECT_FILE_VERSION,
    BatchRecord,
    DocumentProject,
    apply_batch,
    load_project,
    save_project,
)
from qqe.project.service import (
    BatchConflictError,
    InvalidOrderError,
    ProjectService,
)

__all__ = [
    "PROJECT_FILE_VERSION",
    "BatchConflictError",
    "BatchRecord",
    "DocumentProject",
    "InvalidOrderError",
    "ProjectService",
    "apply_batch",
    "load_project",
    "save_project",
]
