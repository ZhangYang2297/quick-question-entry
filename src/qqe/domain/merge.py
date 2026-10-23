"""批次内合并与续加追加。

三条铁律：
1. **批次内**顺序由 (upload_order, page_index, column, bbox_y) 初始落位决定，
   与传入顺序、并发完成顺序、源题号全部无关。column 保证双栏书页先左后右。
2. **批次并入项目**时，新题一律**追加到末尾**，既有题目原位不动 ——
   这是续加不冲掉已有内容、也不冲掉用户调序的关键。
3. **残题过滤在这里执行，但绝不静默丢弃**：is_fragment 的题被剥离到
   separate_fragments() 的第二个返回值，由调用方（batch.py）放进
   BatchResult.excluded，供校对页展示与恢复。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qqe.domain.models import Question, QuestionSet
from qqe.domain.ordering import order_by_layout, renormalize
from qqe.validators.rules import enforce_fragment

if TYPE_CHECKING:  # 避免与 parser 层循环 import
    from qqe.parser.repair import PageOutcome


def separate_fragments(questions: list[Question]) -> tuple[list[Question], list[Question]]:
    """把残题从正式清单剥离。返回 (完整题, 残题) —— 残题不丢弃，供"已排除"展示与恢复。"""
    complete = [q for q in questions if not q.is_fragment]
    fragments = [q for q in questions if q.is_fragment]
    return complete, fragments


def _merge_pages(
    outcomes: list[PageOutcome], *, order_locked: bool = False
) -> tuple[str | None, list[str], list[Question]]:
    """把多个页结果按 (upload_order, page_index) 汇总为 (title, groups, 题目)。

    `order_locked=True` 表示题目顺序**已由用户在校对页确认**：
    不再按版面重排，直接采用传入顺序（这是"用户手动调序不被冲掉"的关键）。
    """
    ordered_pages = sorted(outcomes, key=lambda outcome: (outcome.upload_order, outcome.page_index))

    title: str | None = None
    groups: list[str] = []
    questions: list[Question] = []

    for outcome in ordered_pages:
        if title is None and outcome.title:
            title = outcome.title
        for group in outcome.groups:
            if group not in groups:
                groups.append(group)
        questions.extend(outcome.questions)

    return title, groups, questions if order_locked else order_by_layout(questions)


def merge_outcomes(outcomes: list[PageOutcome]) -> QuestionSet:
    """单批次合并（等价于把这一批追加到一个空项目）。残题被剥离，不进入题目清单。"""
    title, groups, questions = _merge_pages(outcomes)
    enforce_fragment(questions)  # 代码裁定：与模型标记交叉
    complete, _fragments = separate_fragments(questions)
    return QuestionSet(title=title, groups=groups, questions=renormalize(complete))


def append_outcomes(
    existing: QuestionSet,
    outcomes: list[PageOutcome],
    *,
    batch_seq: int,
    order_locked: bool = False,
) -> QuestionSet:
    """**续加**：把新批次的题目追加到既有题目之后，再统一重编号。

    - 既有题目：顺序、id、内容全部原样保留（连列表位置都不动）
    - 新题目：先按版面落位（`order_locked=True` 时保持传入顺序），残题剥离，
      再整体接在末尾，并打上 batch_seq
    - 最后 renormalize() 把 order 重排为 1..N
    """
    title, groups, new_questions = _merge_pages(outcomes, order_locked=order_locked)
    enforce_fragment(new_questions)
    complete, _fragments = separate_fragments(new_questions)
    return append_questions(existing, complete, batch_seq=batch_seq, title=title, groups=groups)


def append_questions(
    existing: QuestionSet,
    new_questions: list[Question],
    *,
    batch_seq: int,
    title: str | None = None,
    groups: list[str] | None = None,
) -> QuestionSet:
    """把已定序的新题接在既有题目末尾。**调用方负责选题与顺序。**"""
    for question in new_questions:
        question.batch_seq = batch_seq

    merged_groups = list(existing.groups)
    for group in groups or []:
        if group not in merged_groups:
            merged_groups.append(group)

    merged_questions = renormalize([*existing.questions, *new_questions])
    return QuestionSet(
        title=existing.title or title,
        groups=merged_groups,
        questions=merged_questions,
    )
