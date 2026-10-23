"""项目内题目：整题替换、删除、调序、恢复被排除的残题。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from qqe.api.deps import current_user, get_service
from qqe.api.schemas import ReorderRequest, project_view, question_view
from qqe.domain.models import Question
from qqe.project.service import ProjectService
from qqe.store import QuestionNotFound

router = APIRouter(tags=["questions"])


def _locate(service: ProjectService, question_id: str, user: str) -> tuple[Question, str]:
    found = service.store.get_question(question_id)
    if found is None:
        raise QuestionNotFound(question_id)
    question, project_id = found
    service.get_project(project_id, owner_id=user)  # 归属校验
    return question, project_id


@router.patch("/questions/{question_id}")
def patch_question(
    question_id: str,
    body: dict,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    """**整题替换**（含 tables）：身份与位置不变，内容整体换掉。"""
    _locate(service, question_id, user)
    replacement = Question.model_validate({**body, "id": question_id})
    service.replace_question(question_id, replacement)
    return question_view(service.store.get_question(question_id)[0])


@router.delete("/questions/{question_id}")
def delete_question(
    question_id: str,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    _, project_id = _locate(service, question_id, user)
    project = service.remove_question(project_id, question_id)
    return {"project": project_view(project), "removed": question_id}


@router.post("/projects/{project_id}/questions/reorder")
def reorder_questions(
    project_id: str,
    body: ReorderRequest,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    service.get_project(project_id, owner_id=user)
    project = service.reorder(project_id, body.question_ids)
    return project_view(project, detail=True)


@router.post("/projects/{project_id}/excluded/{question_id}/restore")
def restore_excluded(
    project_id: str,
    question_id: str,
    position: int | None = None,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    service.get_project(project_id, owner_id=user)
    project = service.restore_excluded(project_id, question_id, position)
    return project_view(project, detail=True)
