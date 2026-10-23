"""样式预设与项目样式读写。

样式是**项目级**的：这里改一次，整份文档（含历史批次）的导出与预览立即跟着变。
前端拿到的是完整 `StyleSpec`，所以高级参数面板不需要在前端复制一份字段表。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from qqe.api.deps import current_user, get_service
from qqe.api.schemas import StyleUpdate, project_view, style_of_project
from qqe.domain.style import StyleSpec, get_preset, list_presets
from qqe.project.service import ProjectService

router = APIRouter(tags=["styles"])


@router.get("/styles")
def list_style_presets():
    return {
        "items": [{"name": name, "spec": get_preset(name).to_dict()} for name in list_presets()]
    }


@router.get("/projects/{project_id}/style")
def get_project_style(
    project_id: str,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    project = service.get_project(project_id, owner_id=user)
    return {
        "style": style_of_project(project).to_dict(),
        "style_name": project.style_name,
        "custom": project.custom_style is not None,
    }


@router.put("/projects/{project_id}/style")
def update_project_style(
    project_id: str,
    body: StyleUpdate,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    """切预设或保存自定义样式；两者都传时以 `spec` 为准。"""
    service.get_project(project_id, owner_id=user)
    if body.spec is not None:
        project = service.set_style_spec(project_id, StyleSpec.model_validate(body.spec))
    elif body.style_name:
        project = service.set_style(project_id, body.style_name)
    else:
        raise ValueError("请提供 style_name 或 spec")
    return project_view(project, detail=True)
