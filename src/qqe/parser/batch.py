"""批量并发解析编排。

设计要点：
- 图片之间互相独立 → 用线程池并发（Provider 是同步的，线程比 event loop 更稳）。
- 结果按 upload_order 归位，**绝不按完成顺序拼接**。
- 单张失败只记录、不抛出，不阻塞整批。
- 单批上限 MAX_BATCH_SIZE 张，超出**明确报错**（前端据此提示拆分批次）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from qqe.domain.merge import merge_outcomes, separate_fragments
from qqe.domain.models import Question, QuestionSet
from qqe.parser.prompt import SYSTEM_PROMPT
from qqe.parser.repair import PageOutcome, parse_page_with_repair
from qqe.preprocess.loader import ImageRef
from qqe.providers.base import VisionModel

ProgressCallback = Callable[[int, int], None]

MAX_BATCH_SIZE = 20


@dataclass(frozen=True)
class FailedPage:
    upload_order: int
    page_index: int
    error: str


@dataclass
class BatchResult:
    question_set: QuestionSet
    outcomes: list[PageOutcome] = field(default_factory=list)
    failed: list[FailedPage] = field(default_factory=list)
    excluded: list[Question] = field(default_factory=list)  # 被过滤的残题，供校对页展示与恢复


class AllPagesFailedError(RuntimeError):
    """整批一张都没成功。

    单独定义是为了让**调用方能拿到失败明细**（前端要按张重试），
    而不是只看到一句字符串。
    """

    def __init__(self, failed: list[FailedPage]) -> None:
        self.failed = failed
        first = failed[0] if failed else None
        detail = f"首个错误：{first.error}" if first else "无失败明细"
        super().__init__(f"全部图片解析失败，{detail}")


def parse_batch(
    model: VisionModel,
    images: Sequence[ImageRef],
    *,
    schema: dict,
    system_prompt: str = SYSTEM_PROMPT,
    max_concurrency: int = 4,
    max_retries: int = 2,
    max_batch_size: int = MAX_BATCH_SIZE,
    on_progress: ProgressCallback | None = None,
) -> BatchResult:
    refs = list(images)
    if not refs:
        return BatchResult(question_set=QuestionSet())
    if len(refs) > max_batch_size:
        raise ValueError(f"单批最多 {max_batch_size} 张，本次传入 {len(refs)} 张，请拆分成多个批次")

    results: dict[tuple[int, int], PageOutcome] = {}
    failed: list[FailedPage] = []
    done = 0

    with ThreadPoolExecutor(max_workers=max(1, max_concurrency)) as pool:
        futures = {
            pool.submit(
                parse_page_with_repair,
                model,
                ref,
                schema=schema,
                system_prompt=system_prompt,
                max_retries=max_retries,
            ): ref
            for ref in refs
        }
        for future in as_completed(futures):
            ref = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:  # noqa: BLE001 —— 刻意宽catch：单张图失败必须隔离，不能拖垮整批
                failed.append(FailedPage(ref.upload_order, ref.page_index, repr(exc)))
            else:
                results[ref.key] = outcome
            done += 1
            if on_progress:
                on_progress(done, len(refs))

    outcomes = [results[key] for key in sorted(results)]
    if not outcomes and failed:
        raise AllPagesFailedError(failed)

    question_set = merge_outcomes(outcomes)
    # 被剥离的残题收集进 excluded（含 reason 与原图引用），供校对页"已排除"展示与恢复
    excluded: list[Question] = []
    for outcome in outcomes:
        _complete, fragments = separate_fragments(outcome.questions)
        excluded.extend(fragments)

    return BatchResult(
        question_set=question_set,
        outcomes=outcomes,
        failed=failed,
        excluded=excluded,
    )
