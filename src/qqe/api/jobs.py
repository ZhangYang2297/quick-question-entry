"""异步解析任务（内存态）。

**为什么先放内存**：解析是分钟级长任务，HTTP 请求不能一直挂着；但草稿在
人工确认前本来就不该落库。M4 先用进程内任务表，重启后未确认的草稿丢失 —
这正是"未确认的批次不污染项目"的另一种表达。

状态流：`parsing → needs_review → confirmed / discarded`；解析整体失败进 `failed`。
单张图失败只记录在 `failed` 里，任务仍是 needs_review（可单独重试）。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from qqe.domain.merge import merge_outcomes
from qqe.domain.models import Question, QuestionSet, now_iso
from qqe.domain.ordering import renormalize
from qqe.parser.batch import (
    MAX_BATCH_SIZE,
    AllPagesFailedError,
    BatchResult,
    FailedPage,
    parse_batch,
)
from qqe.preprocess.loader import ImageRef
from qqe.providers.base import VisionModel


class JobState(StrEnum):
    PARSING = "parsing"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    DISCARDED = "discarded"
    FAILED = "failed"


class JobNotFound(LookupError):
    pass


class JobConflict(RuntimeError):
    """任务当前状态不允许这个操作（如对已确认的批次改草稿）。"""


@dataclass
class Job:
    id: str
    project_id: str
    images: list[ImageRef]
    total: int
    state: JobState = JobState.PARSING
    done: int = 0
    created_at: str = field(default_factory=now_iso)
    result: BatchResult | None = None
    error: str | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def questions(self) -> list[Question]:
        return self.result.question_set.questions if self.result else []

    @property
    def failed(self) -> list[FailedPage]:
        return self.result.failed if self.result else []


class JobManager:
    def __init__(
        self,
        model: VisionModel,
        *,
        schema: dict,
        max_concurrency: int = 4,
        max_retries: int = 2,
        max_workers: int = 2,
    ) -> None:
        self.model = model
        self.schema = schema
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self._jobs: dict[str, Job] = {}
        self._guard = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="qqe-job")

    # ---- 生命周期 -------------------------------------------------------
    def create(self, project_id: str, images: list[ImageRef]) -> Job:
        refs = list(images)
        if not refs:
            raise ValueError("没有可解析的图片")
        if len(refs) > MAX_BATCH_SIZE:
            raise ValueError(f"单批最多 {MAX_BATCH_SIZE} 张，本次 {len(refs)} 张，请拆分成多个批次")
        job = Job(id=uuid4().hex, project_id=project_id, images=refs, total=len(refs))
        with self._guard:
            self._jobs[job.id] = job
        self._executor.submit(self._run, job)
        return job

    def _run(self, job: Job) -> None:
        job.state = JobState.PARSING
        try:
            batch = parse_batch(
                self.model,
                job.images,
                schema=self.schema,
                max_concurrency=self.max_concurrency,
                max_retries=self.max_retries,
                on_progress=self._progress(job),
            )
        except AllPagesFailedError as exc:
            # 一张都没成功不是"系统炸了"，而是"这批需要重试/人工处理"：
            # 保留失败明细，状态停在可重试的 needs_review。
            with job.lock:
                job.result = BatchResult(question_set=QuestionSet(), failed=list(exc.failed))
                job.error = str(exc)
                job.done = job.total
                job.state = JobState.NEEDS_REVIEW
            return
        except Exception as exc:  # noqa: BLE001 —— 任务失败要落成状态，不能丢在线程里
            with job.lock:
                job.state = JobState.FAILED
                job.error = str(exc) or repr(exc)
            return
        with job.lock:
            job.result = batch
            job.done = job.total
            job.state = JobState.NEEDS_REVIEW

    def _progress(self, job: Job):
        def callback(done: int, total: int) -> None:
            with job.lock:
                job.done = done
                job.total = total

        return callback

    def get(self, job_id: str) -> Job:
        with self._guard:
            job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        return job

    def discard(self, job_id: str) -> Job:
        job = self.get(job_id)
        with job.lock:
            if job.state is JobState.CONFIRMED:
                raise JobConflict("批次已并入文档，不能放弃")
            job.state = JobState.DISCARDED
        return job

    def mark_confirmed(self, job_id: str) -> None:
        job = self.get(job_id)
        with job.lock:
            job.state = JobState.CONFIRMED

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ---- 草稿编辑（校对页用） -------------------------------------------
    def _editable(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.state is not JobState.NEEDS_REVIEW or job.result is None:
            raise JobConflict(f"批次当前状态 {job.state} 不允许编辑草稿")
        return job

    def patch_question(self, job_id: str, question_id: str, replacement: Question) -> Job:
        job = self._editable(job_id)
        with job.lock:
            questions = job.result.question_set.questions
            index = next((i for i, q in enumerate(questions) if q.id == question_id), None)
            if index is None:
                raise JobNotFound(question_id)
            original = questions[index]
            questions[index] = replacement.model_copy(
                update={
                    "id": question_id,
                    "order": original.order,
                    "upload_order": original.upload_order,
                    "page_index": original.page_index,
                    "source_file": original.source_file,
                }
            )
        return job

    def remove_question(self, job_id: str, question_id: str) -> Job:
        job = self._editable(job_id)
        with job.lock:
            questions = job.result.question_set.questions
            remaining = [q for q in questions if q.id != question_id]
            if len(remaining) == len(questions):
                raise JobNotFound(question_id)
            job.result.question_set.questions = renormalize(remaining)
        return job

    def add_question(self, job_id: str, question: Question, *, position: int | None = None) -> Job:
        """在校对页新增一题（拆分/补录用）。`position` 为空则追加到末尾。"""
        job = self._editable(job_id)
        with job.lock:
            questions = list(job.result.question_set.questions)
            if position is None or position >= len(questions):
                questions.append(question)
            else:
                questions.insert(max(position, 0), question)
            job.result.question_set.questions = renormalize(questions)
        return job

    def reorder(self, job_id: str, ordered_question_ids: list[str]) -> Job:
        job = self._editable(job_id)
        with job.lock:
            questions = job.result.question_set.questions
            by_id = {q.id: q for q in questions}
            if len(ordered_question_ids) != len(questions) or set(ordered_question_ids) != set(
                by_id
            ):
                raise ValueError("调序必须包含草稿中的全部题目 id，且不重复")
            job.result.question_set.questions = renormalize(
                [by_id[qid] for qid in ordered_question_ids]
            )
        return job

    def retry_failed(self, job_id: str, *, upload_order: int | None = None) -> Job:
        """重试失败的页（全部或指定一张）。**会按版面重排草稿，手动调序需重做。**"""
        job = self.get(job_id)
        with job.lock:
            if job.state not in (JobState.NEEDS_REVIEW, JobState.FAILED):
                raise JobConflict(f"批次当前状态 {job.state} 不允许重试")
            targets = [
                ref
                for ref in job.images
                if (ref.upload_order, ref.page_index)
                in {(f.upload_order, f.page_index) for f in job.failed}
            ]
            if upload_order is not None:
                targets = [ref for ref in targets if ref.upload_order == upload_order]
            if not targets:
                raise ValueError("没有需要重试的失败页")
            job.state = JobState.PARSING
            job.error = None

        try:
            retried = parse_batch(
                self.model,
                targets,
                schema=self.schema,
                max_concurrency=self.max_concurrency,
                max_retries=self.max_retries,
                on_progress=self._progress(job),
            )
        except Exception as exc:  # noqa: BLE001
            with job.lock:
                job.state = JobState.FAILED
                job.error = str(exc) or repr(exc)
            return job

        with job.lock:
            targets_keys = {(ref.upload_order, ref.page_index) for ref in targets}
            kept = [
                outcome
                for outcome in (job.result.outcomes if job.result else [])
                if (outcome.upload_order, outcome.page_index) not in targets_keys
            ]
            outcomes = [*kept, *retried.outcomes]
            merged = merge_outcomes(outcomes)  # 残题在内部被剥离，返回的已是完整题
            job.result = BatchResult(
                question_set=merged,
                outcomes=outcomes,
                failed=[
                    failed
                    for failed in (job.result.failed if job.result else [])
                    if (failed.upload_order, failed.page_index) not in targets_keys
                ]
                + list(retried.failed),
                excluded=[
                    *(job.result.excluded if job.result else []),
                    *retried.excluded,
                ],
            )
            job.done = job.total
            job.state = JobState.NEEDS_REVIEW
        return job

    # ---- 视图 -----------------------------------------------------------
    def snapshot(self, job: Job) -> dict:
        with job.lock:
            result = job.result
            return {
                "batch_id": job.id,
                "project_id": job.project_id,
                "state": str(job.state),
                "total": job.total,
                "done": job.done,
                "created_at": job.created_at,
                "error": job.error,
                "question_count": len(result.question_set.questions) if result else 0,
                "excluded_count": len(result.excluded) if result else 0,
                "images": [
                    {
                        "upload_order": ref.upload_order,
                        "page_index": ref.page_index,
                        "name": ref.display_name or ref.path.name,
                    }
                    for ref in job.images
                ],
                "failed": [
                    {
                        "upload_order": failed.upload_order,
                        "page_index": failed.page_index,
                        "error": failed.error,
                    }
                    for failed in (result.failed if result else [])
                ],
                "questions": [
                    _question_view(question)
                    for question in (result.question_set.questions if result else [])
                ],
                "excluded": [_question_view(q) for q in (result.excluded if result else [])],
            }


def _question_view(question: Question) -> dict:
    return {
        "id": question.id,
        "order": question.order,
        "source_label": question.source_label,
        "type": str(question.type),
        "stem": question.stem,
        "options": [option.model_dump() for option in question.options],
        "tables": [table.model_dump() for table in question.tables],
        "warnings": list(question.warnings),
        "source_file": question.source_file,
        "batch_seq": question.batch_seq,
    }
