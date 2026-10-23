"""上传、批次、校对与确认。

**草稿 gate**：批次解析完只是草稿（`needs_review`），未 `confirm` 前
导出与项目详情里都看不到这批题目 —— 放弃批次只丢草稿，不污染项目。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse

from qqe.api.deps import current_user, get_jobs, get_service
from qqe.api.jobs import JobConflict, JobManager, JobNotFound, JobState
from qqe.api.schemas import (
    BatchCreate,
    DraftReorderRequest,
    PreviewRequest,
    RetryRequest,
    batch_view,
    project_view,
    question_view,
    style_of_project,
)
from qqe.domain.models import Question, QuestionSet
from qqe.domain.style import StyleSpec
from qqe.parser.batch import MAX_BATCH_SIZE
from qqe.preprocess.loader import IMAGE_SUFFIXES, PDF_SUFFIXES, load_images
from qqe.preview.css_renderer import render_preview_html
from qqe.project.service import ProjectService
from qqe.store import UploadNotFound

router = APIRouter(tags=["batches"])

ALLOWED_SUFFIXES = IMAGE_SUFFIXES | PDF_SUFFIXES


def _uploads_root(request: Request) -> Path:
    return Path(request.app.state.uploads_dir)


def _upload_dir(request: Request, project_id: str) -> Path:
    path = _uploads_root(request) / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.post("/projects/{project_id}/uploads", status_code=201)
async def upload_files(
    project_id: str,
    request: Request,
    files: list[UploadFile] = File(...),
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
):
    """接收一批文件，**返回顺序 = 提交顺序**（前端据此渲染可拖动列表）。"""
    service.get_project(project_id, owner_id=user)
    if not files:
        raise ValueError("没有收到文件")
    if len(files) > MAX_BATCH_SIZE:
        raise ValueError(
            f"单批最多 {MAX_BATCH_SIZE} 张，本次 {len(files)} 张，请拆分成多个批次上传"
        )

    upload_dir = _upload_dir(request, project_id)
    items: list[dict] = []
    for index, upload in enumerate(files):
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise ValueError(f"不支持的文件类型：{upload.filename or suffix or '未知'}")
        content = await upload.read()
        if not content:
            raise ValueError(f"文件为空：{upload.filename}")
        upload_id = uuid4().hex
        # 落盘名只用 uuid，**原始文件名不参与任何排序或查找**
        destination = upload_dir / f"{upload_id}{suffix}"
        destination.write_bytes(content)
        items.append(
            {
                "id": upload_id,
                "file_name": upload.filename or destination.name,
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "path": str(destination),
                "upload_order": index,
            }
        )

    service.store.add_uploads(project_id, batch_id=None, items=items)
    return {
        "items": [
            {
                "upload_id": item["id"],
                "file_name": item["file_name"],
                "upload_order": item["upload_order"],
            }
            for item in items
        ]
    }


@router.post("/projects/{project_id}/batches", status_code=202)
def create_batch(
    project_id: str,
    body: BatchCreate,
    request: Request,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
    jobs: JobManager = Depends(get_jobs),
):
    """按 `upload_ids` 的顺序创建解析任务（后台并发），立即返回任务 id。"""
    service.get_project(project_id, owner_id=user)
    if not body.upload_ids:
        raise ValueError("请至少选择一张图片")
    if len(body.upload_ids) > MAX_BATCH_SIZE:
        raise ValueError(
            f"单批最多 {MAX_BATCH_SIZE} 张，本次 {len(body.upload_ids)} 张，请拆分成多个批次"
        )

    uploads = []
    for upload_id in body.upload_ids:
        row = service.store.get_upload(upload_id)
        if row is None or row["project_id"] != project_id:
            raise UploadNotFound(upload_id)
        uploads.append(row)

    refs = load_images(
        [Path(row["path"]) for row in uploads],
        work_dir=_upload_dir(request, project_id) / "work",
    )
    job = jobs.create(project_id, refs)
    service.store.assign_uploads_batch(body.upload_ids, job.id)
    return {"batch_id": job.id, "state": str(job.state), "total": job.total}


@router.get("/batches/{batch_id}")
def get_batch(
    batch_id: str,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
    jobs: JobManager = Depends(get_jobs),
):
    """任务态返回实时快照（含按张进度）；已确认的批次回落到数据库记录。"""
    try:
        job = jobs.get(batch_id)
    except JobNotFound:
        job = None

    if job is not None:
        service.get_project(job.project_id, owner_id=user)  # 归属校验
        return jobs.snapshot(job)

    record, project_id = service.get_batch(batch_id)
    service.get_project(project_id, owner_id=user)
    return batch_view(record)


@router.post("/batches/{batch_id}/confirm")
def confirm_batch(
    batch_id: str,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
    jobs: JobManager = Depends(get_jobs),
):
    job = jobs.get(batch_id)
    service.get_project(job.project_id, owner_id=user)
    if job.state is not JobState.NEEDS_REVIEW:
        raise JobConflict(f"批次当前状态为 {job.state}，不能确认并入")
    if not job.questions:
        raise JobConflict("未识别到任何完整题目，未并入文档（残题见 excluded）")

    project, record = service.append_batch(
        job.project_id,
        job.result,
        record_id=job.id,
        order_locked=True,  # 校对页里的顺序就是最终顺序，绝不再按版面重排
    )
    jobs.mark_confirmed(batch_id)
    return {"batch": batch_view(record), "project": project_view(project)}


@router.post("/batches/{batch_id}/discard")
def discard_batch(
    batch_id: str,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
    jobs: JobManager = Depends(get_jobs),
):
    job = jobs.get(batch_id)
    service.get_project(job.project_id, owner_id=user)
    jobs.discard(batch_id)
    return {"batch_id": batch_id, "state": str(job.state)}


@router.post("/batches/{batch_id}/retry")
def retry_batch(
    batch_id: str,
    body: RetryRequest | None = None,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
    jobs: JobManager = Depends(get_jobs),
):
    """单张失败可单独重试：`{"upload_order": k}`；不传则重试全部失败页。"""
    job = jobs.get(batch_id)
    service.get_project(job.project_id, owner_id=user)
    jobs.retry_failed(batch_id, upload_order=body.upload_order if body else None)
    return jobs.snapshot(jobs.get(batch_id))


# ---- 草稿编辑（校对页；确认前都可改） ---------------------------------


@router.get("/batches/{batch_id}/questions")
def list_draft_questions(
    batch_id: str,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
    jobs: JobManager = Depends(get_jobs),
):
    job = jobs.get(batch_id)
    service.get_project(job.project_id, owner_id=user)
    return {
        "items": [question_view(question) for question in job.questions],
        "excluded": [
            question_view(question) for question in (job.result.excluded if job.result else [])
        ],
    }


@router.patch("/batches/{batch_id}/questions/{question_id}")
def patch_draft_question(
    batch_id: str,
    question_id: str,
    body: dict,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
    jobs: JobManager = Depends(get_jobs),
):
    job = jobs.get(batch_id)
    service.get_project(job.project_id, owner_id=user)
    payload = {**body, "id": question_id}
    replacement = Question.model_validate(payload)
    jobs.patch_question(batch_id, question_id, replacement)
    return {"items": [question_view(question) for question in job.questions]}


@router.delete("/batches/{batch_id}/questions/{question_id}")
def delete_draft_question(
    batch_id: str,
    question_id: str,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
    jobs: JobManager = Depends(get_jobs),
):
    job = jobs.get(batch_id)
    service.get_project(job.project_id, owner_id=user)
    jobs.remove_question(batch_id, question_id)
    return {"items": [question_view(question) for question in job.questions]}


@router.post("/batches/{batch_id}/questions")
def add_draft_question(
    batch_id: str,
    body: dict,
    position: int | None = Query(default=None, description="插入位置（0 起）；不传则追加"),
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
    jobs: JobManager = Depends(get_jobs),
):
    """新增一题：拆分题目时用来承接后半段，也可用于补录漏识别的一题。"""
    job = jobs.get(batch_id)
    service.get_project(job.project_id, owner_id=user)
    payload = {key: value for key, value in body.items() if key != "id"}
    question = Question.model_validate(payload)
    jobs.add_question(batch_id, question, position=position)
    return {"items": [question_view(item) for item in job.questions]}


@router.post("/batches/{batch_id}/preview")
def preview_batch(
    batch_id: str,
    body: PreviewRequest | None = None,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
    jobs: JobManager = Depends(get_jobs),
):
    """校对页样式试看：用草稿里**未保存**的 spec 渲染，不落库。"""
    job = jobs.get(batch_id)
    project = service.get_project(job.project_id, owner_id=user)
    spec = (
        StyleSpec.model_validate(body.spec)
        if body is not None and body.spec is not None
        else style_of_project(project)
    )
    question_set = job.result.question_set if job.result else QuestionSet()
    return {
        "html": render_preview_html(question_set, spec),
        "question_count": len(question_set.questions),
    }


@router.get("/batches/{batch_id}/images/{upload_order}")
def get_batch_image(
    batch_id: str,
    upload_order: int,
    page: int = Query(default=0, ge=0),
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
    jobs: JobManager = Depends(get_jobs),
):
    """校对页"回看原图"用。只按 upload_order/page_index 定位，**不认文件名**。"""
    job = jobs.get(batch_id)
    service.get_project(job.project_id, owner_id=user)
    ref = next(
        (
            item
            for item in job.images
            if item.upload_order == upload_order and item.page_index == page
        ),
        None,
    )
    if ref is None or not ref.path.exists():
        raise UploadNotFound(f"{upload_order}#{page}")
    return FileResponse(ref.path)


@router.post("/batches/{batch_id}/reorder")
def reorder_draft(
    batch_id: str,
    body: DraftReorderRequest,
    user: str = Depends(current_user),
    service: ProjectService = Depends(get_service),
    jobs: JobManager = Depends(get_jobs),
):
    job = jobs.get(batch_id)
    service.get_project(job.project_id, owner_id=user)
    jobs.reorder(batch_id, body.question_ids)
    return {"items": [question_view(question) for question in job.questions]}
