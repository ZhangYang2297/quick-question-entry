"""导出：全量 / 仅本次新增，以及导出历史下载。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from qqe.api.deps import current_user, get_service
from qqe.api.schemas import ExportCreate, export_view
from qqe.project.service import ProjectService
from qqe.store import ExportNotFound

router = APIRouter(tags=["exports"])


@router.post("/projects/{project_id}/exports", status_code=201)
def create_export(
    project_id: str,
    body: ExportCreate | None = None,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    """默认全量导出；`incremental` 只含指定批次新增题（题号从 1 重算）。"""
    service.get_project(project_id, owner_id=user)
    options = body or ExportCreate()
    record = service.export(project_id, mode=options.mode, batch_seq=options.batch_seq)
    return export_view(record)


@router.get("/projects/{project_id}/exports")
def list_exports(
    project_id: str,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    service.get_project(project_id, owner_id=user)
    return {"items": [export_view(record) for record in service.list_exports(project_id)]}


@router.get("/exports/{export_id}/download")
def download_export(
    export_id: str,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    found = service.store.get_export(export_id)
    if found is None:
        raise ExportNotFound(export_id)
    record, project_id = found
    service.get_project(project_id, owner_id=user, include_deleted=True)
    path = Path(record.path or "")
    if not record.path or not path.exists():
        raise ExportNotFound(f"{export_id}（文件已不存在）")
    return FileResponse(
        path,
        filename=record.file_name or path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
