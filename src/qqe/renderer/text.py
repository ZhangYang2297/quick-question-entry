"""纯文本排版规则 —— docx 渲染器与 CSS 预览共用同一套。

**为什么单独一层**：同一个题号格式、同一个选项标记、同一个判断题括号，
在 .docx 与预览 HTML 里必须字字一致，否则"预览所见 ≠ 导出所得"。
两边都调这里，一致性就有单测兜底。
"""

from __future__ import annotations

from qqe.domain.models import Option, Question, QuestionType
from qqe.domain.style import NumberFormat, OptionMarker, ParenPosition, ParenStyle, StyleSpec

FULLWIDTH_SPACE = "\u3000"
_FULLWIDTH_PAREN = f"（{FULLWIDTH_SPACE}）"
_HALFWIDTH_PAREN = "( )"

_NUMBER_TEMPLATES = {
    NumberFormat.DOT: "{n}. ",
    NumberFormat.CN_DOT: "{n}、",
    NumberFormat.FULLWIDTH_DOT: "{n}．",
    NumberFormat.PREFIX: "第{n}题 ",
}

_MARKER_TEMPLATES = {
    OptionMarker.DOT: "{label}. ",
    OptionMarker.CN_DOT: "{label}、",
    OptionMarker.PAREN: "({label}) ",
}


def format_number(order: int, number_format: NumberFormat) -> str:
    """题号文本。**只认 order（列表位置），绝不看 source_label。**"""
    return _NUMBER_TEMPLATES[number_format].format(n=order)


def format_option_label(label: str, marker: OptionMarker) -> str:
    return _MARKER_TEMPLATES[marker].format(label=label)


def paren_text(paren_style: ParenStyle) -> str:
    return _FULLWIDTH_PAREN if paren_style == ParenStyle.FULLWIDTH else _HALFWIDTH_PAREN


def apply_true_false_parens(stem: str, style: StyleSpec) -> str:
    """判断题补作答括号。题干里已有括号时不重复添加。"""
    paren = paren_text(style.true_false.paren_style)
    text = stem.strip()
    if text.endswith(paren) or text.endswith(_HALFWIDTH_PAREN) or text.endswith(_FULLWIDTH_PAREN):
        return text
    if text.startswith(paren) or text.startswith(_HALFWIDTH_PAREN):
        return text
    if style.true_false.paren_position == ParenPosition.PREFIX:
        return paren + text
    return text + paren


def question_text(question: Question, style: StyleSpec) -> str:
    """题号 + 题干（同一段落）。判断题按 StyleSpec 补括号。"""
    stem = question.stem.strip()
    if question.type == QuestionType.TRUE_FALSE:
        stem = apply_true_false_parens(stem, style)
    return format_number(question.order, style.stem.number_format) + stem


def option_text(option: Option, style: StyleSpec) -> str:
    return format_option_label(option.label, style.option.marker) + option.text.strip()


def chunk_options(options: list[Option], per_line: int) -> list[list[Option]]:
    """按「一行几个选项」切块；最后一个块可能不满。"""
    if per_line < 1:
        raise ValueError("options_per_line 必须 ≥ 1")
    return [options[index : index + per_line] for index in range(0, len(options), per_line)]


def option_line_text(options: list[Option], style: StyleSpec) -> str:
    """一行内的多个选项用全角空格分隔。"""
    return (FULLWIDTH_SPACE * 2).join(option_text(option, style) for option in options)
