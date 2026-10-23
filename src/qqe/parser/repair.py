"""自修复重试环：校验失败就把问题回喂给模型，让它自己改。

降级原则：**始终不抛异常**。重试用尽后返回带 warnings 的低置信度结果，
交给人工校对页兜底 —— 绝不让一张图失败拖垮整批。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from qqe.domain.models import PageParse, Question
from qqe.parser.prompt import SYSTEM_PROMPT, build_feedback_prompt
from qqe.parser.vlm_parser import ParseError, parse_page_text
from qqe.preprocess.loader import ImageRef
from qqe.providers.base import VisionModel
from qqe.validators.clean import clean_questions
from qqe.validators.rules import format_issues, has_errors, validate_questions
from qqe.validators.types import Severity, ValidationIssue


@dataclass
class PageOutcome:
    upload_order: int
    page_index: int
    title: str | None = None
    groups: list[str] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    attempts: int = 0
    low_confidence: bool = False

    @property
    def key(self) -> tuple[int, int]:
        return (self.upload_order, self.page_index)


def _apply_warnings(
    questions: list[Question],
    issues: list[ValidationIssue],
    cleaning_notes: dict[int, list[str]] | None = None,
) -> None:
    """把 issue 与清洗记录写进对应题目的 warnings，供校对页高亮。"""
    notes = cleaning_notes or {}
    for index, question in enumerate(questions):
        related = [
            issue
            for issue in issues
            if issue.question_index is None or issue.question_index == index
        ]
        messages = [f"{issue.code}: {issue.message}" for issue in related]
        messages.extend(notes.get(index, []))
        if messages:
            question.warnings = [*question.warnings, *messages]
        if related:
            question.confidence = 0.5


def parse_page_with_repair(
    model: VisionModel,
    ref: ImageRef,
    *,
    schema: dict,
    system_prompt: str = SYSTEM_PROMPT,
    max_retries: int = 2,
) -> PageOutcome:
    page = PageParse()
    questions: list[Question] = []
    issues: list[ValidationIssue] = []
    cleaning_notes: dict[int, list[str]] = {}
    feedback: str | None = None

    for attempt in range(1, max_retries + 2):
        raw = model.complete_json(
            system_prompt=system_prompt,
            image_path=ref.path,
            json_schema=schema,
            feedback=feedback,
        )
        try:
            page = parse_page_text(raw)
        except ParseError as exc:
            issues = [
                ValidationIssue(code="json_unparsable", message=str(exc), severity=Severity.ERROR)
            ]
            questions = []
            cleaning_notes = {}
        else:
            questions = page.to_questions(
                ref.upload_order,
                ref.page_index,
                source_file=ref.display_name or ref.path.name,
            )
            # 先清洗版式噪声，再校验 —— 否则"行尾作答字母"会被当成题干内容带进导出件
            cleaning_notes = clean_questions(questions)
            issues = validate_questions(questions, page.groups)
            if not has_errors(issues):
                # 只有 warning（或完全没问题）就直接采用，不浪费一次模型调用
                _apply_warnings(questions, issues, cleaning_notes)
                return PageOutcome(
                    upload_order=ref.upload_order,
                    page_index=ref.page_index,
                    title=page.title,
                    groups=list(page.groups),
                    questions=questions,
                    issues=issues,
                    attempts=attempt,
                    low_confidence=False,
                )
        feedback = build_feedback_prompt(format_issues(issues))

    _apply_warnings(questions, issues, cleaning_notes)
    return PageOutcome(
        upload_order=ref.upload_order,
        page_index=ref.page_index,
        title=page.title,
        groups=list(page.groups),
        questions=questions,
        issues=issues,
        attempts=max_retries + 1,
        low_confidence=True,
    )
