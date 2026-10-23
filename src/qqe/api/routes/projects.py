"""项目（文档）相关路由：增删改查、复制、回收站。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from qqe.api.deps import current_user, get_service
from qqe.api.schemas import (
    DuplicateRequest,
    PreviewRequest,
    ProjectCreate,
    ProjectUpdate,
    project_view,
    style_of_project,
)
from qqe.domain.style import StyleSpec
from qqe.preview.css_renderer import render_preview_html
from qqe.project.service import ProjectService

router = APIRouter(tags=["projects"])


@router.get("/projects")
def list_projects(
    trash: bool = Query(default=False, description="true 时列出回收站"),
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    projects = service.list_projects(owner_id=user, trash=trash)
    return {"items": [project_view(project) for project in projects]}


@router.post("/projects", status_code=201)
def create_project(
    body: ProjectCreate,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    project = service.create_project(name=body.name, style_name=body.style_name, owner_id=user)
    return project_view(project, detail=True)


@router.get("/projects/{project_id}/snapshot")
def snapshot_project(
    project_id: str,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    """整份项目快照（含回收站中的文档），供前端同步到云端。"""
    return service.snapshot(project_id, owner_id=user)


@router.post("/projects/import")
def import_project_snapshot(
    body: dict,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    """从云端快照重建本地项目（同 id 覆盖，题目 id 原样保留）。"""
    project = service.import_snapshot(body, owner_id=user)
    return project_view(project, detail=True)


@router.get("/projects/{project_id}")
def get_project(
    project_id: str,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    return project_view(service.get_project(project_id, owner_id=user), detail=True)


@router.patch("/projects/{project_id}")
def update_project(
    project_id: str,
    body: ProjectUpdate,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    project = service.get_project(project_id, owner_id=user)  # 同时完成归属校验
    if body.name is not None:
        project = service.rename_project(project_id, body.name)
    if body.style_name is not None:
        project = service.set_style(project_id, body.style_name)
    return project_view(project, detail=True)


@router.post("/projects/{project_id}/duplicate", status_code=201)
def duplicate_project(
    project_id: str,
    body: DuplicateRequest | None = None,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    service.get_project(project_id, owner_id=user)
    copy = service.duplicate_project(project_id, name=(body.name if body else None))
    return project_view(copy, detail=True)


@router.post("/projects/{project_id}/preview")
def preview_project(
    project_id: str,
    body: PreviewRequest | None = None,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    """样式面板的实时预览。传了 spec 就用未保存的草稿样式渲染。"""
    project = service.get_project(project_id, owner_id=user)
    spec = (
        StyleSpec.model_validate(body.spec)
        if body is not None and body.spec is not None
        else style_of_project(project)
    )
    return {
        "html": render_preview_html(project.question_set, spec),
        "question_count": project.question_count,
    }


@router.delete("/projects/{project_id}", status_code=200)
def soft_delete_project(
    project_id: str,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    service.get_project(project_id, owner_id=user)
    project = service.soft_delete(project_id)
    return project_view(project)


@router.post("/projects/{project_id}/restore")
def restore_project(
    project_id: str,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    service.get_project(project_id, owner_id=user, include_deleted=True)
    project = service.restore(project_id)
    return project_view(project, detail=True)


@router.delete("/projects/{project_id}/purge", status_code=204)
def purge_project(
    project_id: str,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    service.get_project(project_id, owner_id=user, include_deleted=True)
    service.purge(project_id)
    return None
