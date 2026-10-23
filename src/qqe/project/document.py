"""离线「文档项目」：一个 JSON 文件就是一份可续加的文档。

M3 阶段还没有数据库，但续加的语义必须现在就对：
- 项目里存的是**结构化题目**，不是 .docx —— 导出的 docx 是静态文件，禁止文件级追加；
- 每次续加都 `append` 到题目列表末尾，再全量重渲染；
- 题目 `id` 落盘保存，续加/编辑时老题的身份不变（M4 的复制、删除都依赖这点）。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel, Field

from qqe.domain.merge import append_outcomes, append_questions
from qqe.domain.models import BatchRecord, Question, QuestionSet, now_iso
from qqe.domain.style import DEFAULT_PRESET

if TYPE_CHECKING:  # 只用于类型标注，避免 project 层依赖 parser 的运行时
    from qqe.parser.batch import BatchResult

PROJECT_FILE_VERSION = 1
DEFAULT_PROJECT_NAME = "未命名文档"

__all__ = [
    "DEFAULT_PROJECT_NAME",
    "PROJECT_FILE_VERSION",
    "BatchRecord",
    "DocumentProject",
    "load_project",
    "now_iso",
    "save_project",
]


class DocumentProject(BaseModel):
    """一份可续加的文档。`question_set.questions` 的**列表顺序**就是最终题序。"""

    version: int = PROJECT_FILE_VERSION
    name: str = DEFAULT_PROJECT_NAME
    style_name: str = DEFAULT_PRESET
    question_set: QuestionSet = Field(default_factory=QuestionSet)
    batches: list[BatchRecord] = []
    # 被裁定为残题的题不删除，留在项目里供校对页"已排除"区恢复
    excluded: list[Question] = []
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @property
    def next_batch_seq(self) -> int:
        return max((record.seq for record in self.batches), default=0) + 1

    @property
    def question_count(self) -> int:
        return len(self.question_set.questions)

    def append(self, batch: BatchResult, *, style_name: str | None = None) -> BatchRecord:
        """把一批解析结果**追加到末尾**，返回本次批次记录。"""
        self.question_set, record, self.excluded = apply_batch(
            self.question_set,
            self.batches,
            self.excluded,
            batch,
            style_name=style_name or self.style_name,
        )
        if style_name:
            self.style_name = style_name
        self.batches.append(record)
        self.updated_at = now_iso()
        return record


def apply_batch(
    question_set: QuestionSet,
    batches: list[BatchRecord],
    excluded: list[Question],
    batch: BatchResult,
    *,
    style_name: str | None = None,
    record_id: str | None = None,
    order_locked: bool = False,
) -> tuple[QuestionSet, BatchRecord, list[Question]]:
    """续加的**唯一实现**（JSON 项目与数据库项目共用）。

    - 既有题目：列表位置、`id`、内容全部不动（append_outcomes 保证）
    - 新题目：按版面落位后接在末尾，并打上本批的 `batch_seq`
    - `order_locked=True`：顺序已由用户在校对页确认，**不再按版面重排**
    - 残题不丢，进入 excluded 供校对页恢复
    """
    seq = max((record.seq for record in batches), default=0) + 1
    if order_locked:
        merged = append_questions(
            question_set,
            list(batch.question_set.questions),
            batch_seq=seq,
            title=batch.question_set.title,
            groups=batch.question_set.groups,
        )
    else:
        merged = append_outcomes(question_set, batch.outcomes, batch_seq=seq)
    new_ids = [q.id for q in merged.questions if q.batch_seq == seq]

    record = BatchRecord(
        id=record_id or uuid4().hex,
        seq=seq,
        style_name=style_name,
        image_count=len(batch.outcomes) + len(batch.failed),
        question_ids=new_ids,
        failed=[
            f"第{failed.upload_order + 1}张/第{failed.page_index + 1}页：{failed.error}"
            for failed in batch.failed
        ],
        excluded_ids=[q.id for q in batch.excluded],
    )
    return merged, record, [*excluded, *batch.excluded]


def save_project(project: DocumentProject, path: Path) -> Path:
    """原子写入：先写临时文件再 replace，避免中途失败留下半个 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(project.model_dump(mode="json"), ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".qqe-project-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return path


def load_project(path: Path) -> DocumentProject:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"项目文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"项目文件不是合法 JSON：{path}（{exc}）") from exc

    version = payload.get("version")
    if version != PROJECT_FILE_VERSION:
        raise ValueError(
            f"项目文件版本不支持：{version}（当前支持 {PROJECT_FILE_VERSION}）：{path}"
        )
    return DocumentProject.model_validate(payload)
