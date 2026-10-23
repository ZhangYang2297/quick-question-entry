"""端到端编排：一批图片/PDF → 结构化题目 → 并入文档项目 → 渲染 .docx。

编排层只做「按顺序串联 + 状态记录」，不承担任何解析或格式逻辑 ——
解析在 parser，格式在 renderer，它俩互不认识。

失败处理原则：**不把异常抛给调用方**（CLI/HTTP 都要有稳定的响应），
而是把批次推进到 FAILED 并保留原因；能部分成功的（个别图失败）继续走完。
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from qqe.domain.schema import page_parse_json_schema
from qqe.domain.style import DEFAULT_PRESET, StyleSpec, get_preset
from qqe.orchestrator.state import BatchState, BatchStateMachine
from qqe.parser.batch import MAX_BATCH_SIZE, BatchResult, parse_batch
from qqe.preprocess.loader import ImageRef, load_images
from qqe.project.document import DocumentProject, load_project, save_project
from qqe.providers.base import VisionModel
from qqe.renderer.docx_renderer import render_docx


class EmptyBatchError(ValueError):
    """一张图都没识别出完整题目 —— 绝不导出空文档。"""


@dataclass
class PipelineResult:
    machine: BatchStateMachine
    batch: BatchResult | None = None
    document: DocumentProject | None = None
    docx_path: Path | None = None
    project_path: Path | None = None
    batch_seq: int = 0
    images: list[ImageRef] = field(default_factory=list)
    cost_cny: float = 0.0
    elapsed_s: float = 0.0
    error: str | None = None

    @property
    def state(self) -> BatchState:
        return self.machine.state

    @property
    def ok(self) -> bool:
        return self.state is BatchState.DONE

    @property
    def question_count(self) -> int:
        return self.document.question_count if self.document else 0


def _total_cost(model: VisionModel) -> float:
    """累计模型调用成本。假实现没有 cost 字段，按 0 计。"""
    calls = getattr(model, "calls", None) or []
    return sum(float(getattr(call, "cost_cny", 0.0) or 0.0) for call in calls)


def run_pipeline(
    paths: Sequence[Path],
    *,
    model: VisionModel,
    out_path: Path,
    style: StyleSpec | None = None,
    project_path: Path | None = None,
    project_name: str | None = None,
    work_dir: Path | None = None,
    max_concurrency: int = 4,
    max_retries: int = 2,
    on_progress=None,
    on_review=None,
) -> PipelineResult:
    """跑完整条链路。返回结果对象，不抛业务异常（`result.error` 说明原因）。"""
    out_path = Path(out_path)
    work_dir = Path(work_dir) if work_dir else out_path.parent / ".qqe-work"
    machine = BatchStateMachine()
    result = PipelineResult(machine=machine)
    cost_before = _total_cost(model)
    started = time.monotonic()

    try:
        # ---- 1. 项目先就位：项目文件坏了，要在花钱调模型之前就失败 ----
        if project_path is not None and Path(project_path).exists():
            document = load_project(project_path)
        else:
            document = DocumentProject(name=project_name or out_path.stem)
        result.document = document
        result.project_path = Path(project_path) if project_path else None

        if style is None:
            style = get_preset(document.style_name or DEFAULT_PRESET)

        # ---- 2. 预处理 ----
        machine.transition(BatchState.PREPROCESSING)
        result.images = load_images([Path(path) for path in paths], work_dir=work_dir)
        if not result.images:
            raise ValueError("没有可处理的图片")
        if len(result.images) > MAX_BATCH_SIZE:
            raise ValueError(
                f"单批最多 {MAX_BATCH_SIZE} 张，本次展开后 {len(result.images)} 张，请拆分批处理"
            )
        document.style_name = style.name

        # ---- 3. 解析（并发，按 upload_order 归位） ----
        machine.transition(BatchState.PARSING)
        batch = parse_batch(
            model,
            result.images,
            schema=page_parse_json_schema(),
            max_concurrency=max_concurrency,
            max_retries=max_retries,
            on_progress=on_progress,
        )
        result.batch = batch

        # ---- 4. 待校对：此处不再自动改题，人工确认后才并入项目 ----
        machine.transition(BatchState.NEEDS_REVIEW)
        if not batch.question_set.questions:
            raise EmptyBatchError("未识别到任何完整题目，未导出（残题见 result.batch.excluded）")
        # 校对环节：返回 False 表示放弃本批 —— 只丢草稿，项目已有题目不受影响
        if on_review is not None and not on_review(batch):
            machine.discard()
            return result

        # ---- 5. 并入项目（续加只发生在数据层）+ 落盘 ----
        record = document.append(batch, style_name=style.name)
        result.batch_seq = record.seq
        if project_path is not None:
            save_project(document, project_path)
        machine.transition(BatchState.MERGED)

        # ---- 6. 全量重渲染：绝不"追加到旧 docx" ----
        machine.transition(BatchState.RENDERING)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(render_docx(document.question_set, style))
        result.docx_path = out_path
        machine.transition(BatchState.DONE)
    except Exception as exc:  # noqa: BLE001 —— 编排层负责把任何失败翻译成 FAILED 状态
        result.error = str(exc) or repr(exc)
        if machine.can_transition(BatchState.FAILED):
            machine.fail(result.error)
    finally:
        result.cost_cny = round(_total_cost(model) - cost_before, 6)
        result.elapsed_s = round(time.monotonic() - started, 2)

    return result
