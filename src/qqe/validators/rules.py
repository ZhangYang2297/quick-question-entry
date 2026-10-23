"""通用规则校验。

刻意的取舍：
- **不校验源题号**：源题号乱序/跳号/重号/缺失都是正常输入，校验它只会误报。
- **不校验 order**：逐图校验时 order 尚未分配；序号连续性由 validate_order_continuity
  在**合并之后**单独校验。
- **残题裁定在这里，不在模型**：enforce_fragment() 与模型的 is_fragment 交叉，
  任一方判残即按残处理 —— 宁可错杀进"已排除"，也不让残题混入正文。
- **营销关键词只加 warning 不删除**：删错内容比留着更糟，人工在校对页处理。
"""

from __future__ import annotations

import re

from qqe.domain.models import CHOICE_TYPES, Question
from qqe.validators.table_rules import validate_tables
from qqe.validators.types import Severity, ValidationIssue

LETTERS = "ABCDEFGHIJ"
MIN_STEM_LENGTH = 4

# 营销/干扰关键词（实测样本归纳：直播间横幅、机构引流话术）。命中即 warning，不删除。
MARKETING_KEYWORDS = ("领取", "粉丝群", "主讲", "关注+", "上岸", "机考模拟", "私信", "报名")

__all__ = [
    "Severity",
    "ValidationIssue",
    "enforce_fragment",
    "format_issues",
    "has_errors",
    "validate_order_continuity",
    "validate_questions",
]


def _compact(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def enforce_fragment(questions: list[Question]) -> list[Question]:
    """完整性裁定：与模型的 is_fragment 标记交叉。

    - 结构不完整（选择题选项 <2 或题干为空）→ 强制判残，reason 以 validator: 开头
    - 模型已标记 is_fragment 且结构完整 → 保留模型标记（模型看到了代码看不到的东西，
      例如"题干明显被上一页截断但仍写了半句"）
    返回新列表；不抛异常。
    """
    for question in questions:
        if question.is_fragment:
            continue
        stem_empty = len(_compact(question.stem)) == 0
        too_few_options = question.type in CHOICE_TYPES and len(question.options) < 2
        if stem_empty:
            question.is_fragment = True
            question.fragment_reason = "validator:stem_empty"
        elif too_few_options:
            question.is_fragment = True
            question.fragment_reason = "validator:options_lt_2"
    return questions


def validate_questions(questions: list[Question], groups: list[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for index, question in enumerate(questions):
        if len(_compact(question.stem)) < MIN_STEM_LENGTH:
            issues.append(
                ValidationIssue(
                    code="stem_too_short",
                    message=f"题干过短（{question.stem!r}），疑似切分或识别错误",
                    question_index=index,
                    field="stem",
                )
            )

        if any(kw in question.stem for kw in MARKETING_KEYWORDS):
            issues.append(
                ValidationIssue(
                    code="possible_marketing_text",
                    message="题干疑似混入营销/机构文本，请在校对页人工确认",
                    severity=Severity.WARNING,
                    question_index=index,
                    field="stem",
                )
            )

        if question.type in CHOICE_TYPES:
            labels = [option.label for option in question.options]
            if len(labels) < 2:
                issues.append(
                    ValidationIssue(
                        code="option_too_few",
                        message=f"选择题只有 {len(labels)} 个选项，至少应有 2 个",
                        question_index=index,
                        field="options",
                    )
                )
            elif labels != list(LETTERS[: len(labels)]):
                issues.append(
                    ValidationIssue(
                        code="option_letter_mismatch",
                        message=f"选项标签应为 A/B/C... 顺序，实际为 {labels}",
                        question_index=index,
                        field="options",
                    )
                )

        if question.group_title and groups and question.group_title not in groups:
            issues.append(
                ValidationIssue(
                    code="group_title_unknown",
                    message=f"大题标题 {question.group_title!r} 不在 groups 清单中",
                    severity=Severity.WARNING,
                    question_index=index,
                    field="group_title",
                )
            )

        issues.extend(validate_tables(question.tables, question_index=index))
    return issues


def validate_order_continuity(questions: list[Question]) -> list[ValidationIssue]:
    """合并完成后校验：order 必须是 1..N 连续、无缺口、无重复。"""
    expected = list(range(1, len(questions) + 1))
    actual = [question.order for question in questions]
    if actual == expected:
        return []
    return [
        ValidationIssue(
            code="order_not_continuous",
            message=f"输出序号应为 1..{len(questions)}，实际为 {actual}",
            field="order",
        )
    ]


def format_issues(issues: list[ValidationIssue]) -> str:
    if not issues:
        return "（无问题）"
    lines = []
    for index, issue in enumerate(issues, start=1):
        location = "整页" if issue.question_index is None else f"第 {issue.question_index + 1} 题"
        lines.append(f"{index}. [{issue.code}] {location}：{issue.message}")
    return "\n".join(lines)


def has_errors(issues: list[ValidationIssue]) -> bool:
    return any(issue.severity is Severity.ERROR for issue in issues)
