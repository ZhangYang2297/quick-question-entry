"""请求 / 响应模型与视图构造函数。

响应一律用**扁平字典视图**（而不是直接 dump 领域模型）：
前端需要的字段是稳定的接口契约，领域模型内部字段可以自由演进。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from qqe.domain.models import BatchRecord, ExportRecord, Project, Question
from qqe.domain.style import StyleSpec, get_preset


class ProjectCreate(BaseModel):
    name: str | None = None
    style_name: str = "标准试卷版"


class ProjectUpdate(BaseModel):
    name: str | None = None
    style_name: str | None = None


class DuplicateRequest(BaseModel):
    name: str | None = None


class StyleUpdate(BaseModel):
    """二选一：切预设按名字；调参数传整份 spec（前端把表单完整回传）。"""

    style_name: str | None = None
    spec: dict[str, Any] | None = None


class PreviewRequest(BaseModel):
    """`spec` 为空时用项目当前样式；校对页可传未保存的草稿样式试看效果。"""

    spec: dict[str, Any] | None = None


class BatchCreate(BaseModel):
    """`upload_ids` 的**数组顺序就是题目顺序**（前端按用户点选顺序提交）。"""

    upload_ids: list[str] = Field(default_factory=list)


class ReorderRequest(BaseModel):
    question_ids: list[str] = Field(default_factory=list)


class DraftReorderRequest(BaseModel):
    question_ids: list[str] = Field(default_factory=list)


class ExportCreate(BaseModel):
    mode: Literal["full", "incremental"] = "full"
    batch_seq: int | None = None


class RetryRequest(BaseModel):
    upload_order: int | None = None


def question_view(question: Question) -> dict[str, Any]:
    return {
        "id": question.id,
        "order": question.order,
        "source_label": question.source_label,
        "type": str(question.type),
        "stem": question.stem,
        "options": [option.model_dump() for option in question.options],
        "tables": [table.model_dump() for table in question.tables],
        "group_title": question.group_title,
        "warnings": list(question.warnings),
        "batch_seq": question.batch_seq,
        "source_file": question.source_file,
    }


def batch_view(record: BatchRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "seq": record.seq,
        "state": record.state,
        "created_at": record.created_at,
        "image_count": record.image_count,
        "question_count": len(record.question_ids),
        "question_ids": list(record.question_ids),
        "failed": list(record.failed),
        "excluded_ids": list(record.excluded_ids),
    }


def export_view(record: ExportRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "mode": record.mode,
        "batch_seq": record.batch_seq,
        "file_name": record.file_name,
        "question_count": record.question_count,
        "created_at": record.created_at,
        "download_url": f"/api/exports/{record.id}/download",
    }


def style_of_project(project: Project) -> StyleSpec:
    if project.custom_style:
        return StyleSpec.from_dict(project.custom_style)
    return get_preset(project.style_name)


def project_view(project: Project, *, detail: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": project.id,
        "name": project.name,
        "style_name": project.style_name,
        "owner_id": project.owner_id,
        "title": project.question_set.title,
        "question_count": project.question_count,
        "batch_count": len(project.batches),
        "excluded_count": len(project.excluded),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "deleted_at": project.deleted_at,
    }
    if detail:
        payload["questions"] = [question_view(q) for q in project.question_set.questions]
        payload["batches"] = [batch_view(b) for b in project.batches]
        payload["excluded"] = [question_view(q) for q in project.excluded]
        payload["exports"] = [export_view(e) for e in project.exports]
        payload["groups"] = list(project.question_set.groups)
        payload["style"] = style_of_project(project).to_dict()
        payload["custom_style"] = project.custom_style is not None
    return payload
