"""段落角色（Role）与 StyleSpec 的映射。

渲染器从不直接写"宋体 10.5pt"这种常量，而是：
    角色 → resolve(style, role) → RoleStyle → 落到 docx / CSS

这样"换一套样式"只是换一份 StyleSpec，渲染逻辑一行都不用改。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from qqe.domain.style import Align, StyleSpec


class Role(StrEnum):
    DOC_TITLE = "doc_title"
    SECTION_TITLE = "section_title"
    QUESTION = "question"  # 题号 + 题干（同一段）
    OPTION = "option"
    TABLE_CAPTION = "table_caption"
    TABLE_HEADER = "table_header"
    TABLE_CELL = "table_cell"


@dataclass(frozen=True)
class RoleStyle:
    cjk: str
    latin: str
    size_pt: float
    color: str
    bold: bool
    align: Align
    line_spacing: float
    space_before_pt: float
    space_after_pt: float
    left_indent_chars: float = 0.0
    first_line_indent_chars: float = 0.0

    def left_indent_pt(self) -> float:
        """字符缩进换算成磅值：中文一个字宽 ≈ 当前字号。"""
        return self.left_indent_chars * self.size_pt

    def first_line_indent_pt(self) -> float:
        return self.first_line_indent_chars * self.size_pt


def resolve(style: StyleSpec, role: Role) -> RoleStyle:
    base = {
        "cjk": style.font.cjk,
        "latin": style.font.latin,
        "color": style.font.color,
    }

    if role == Role.DOC_TITLE:
        return RoleStyle(
            **base,
            size_pt=style.title.size_pt,
            bold=style.title.bold,
            align=style.title.align,
            line_spacing=1.0,
            space_before_pt=0.0,
            space_after_pt=style.title.space_after_pt,
        )

    if role == Role.SECTION_TITLE:
        return RoleStyle(
            **base,
            size_pt=style.section.size_pt,
            bold=style.section.bold,
            align=style.section.align,
            line_spacing=1.0,
            space_before_pt=style.section.space_before_pt,
            space_after_pt=style.section.space_after_pt,
        )

    if role == Role.QUESTION:
        return RoleStyle(
            **base,
            size_pt=style.stem.size_pt,
            bold=style.stem.bold,
            align=style.stem.align,
            line_spacing=style.stem.line_spacing,
            space_before_pt=style.stem.space_before_pt,
            space_after_pt=style.stem.space_after_pt,
            first_line_indent_chars=style.stem.first_line_indent_chars,
        )

    if role == Role.OPTION:
        return RoleStyle(
            **base,
            size_pt=style.option.size_pt,
            bold=style.option.bold,
            align=style.stem.align,
            line_spacing=style.option.line_spacing,
            space_before_pt=style.option.space_before_pt,
            space_after_pt=style.option.space_after_pt,
            left_indent_chars=style.option.left_indent_chars,
        )

    if role == Role.TABLE_CAPTION:
        return RoleStyle(
            **base,
            size_pt=style.table.caption_size_pt,
            bold=False,
            align=style.table.caption_align,
            line_spacing=style.table.line_spacing,
            space_before_pt=style.stem.space_after_pt,
            space_after_pt=style.table.cell_padding_pt,
        )

    if role == Role.TABLE_HEADER:
        return RoleStyle(
            **base,
            size_pt=style.table.cell_size_pt,
            bold=style.table.header_bold,
            align=style.table.cell_align,
            line_spacing=style.table.line_spacing,
            space_before_pt=0.0,
            space_after_pt=0.0,
        )

    if role == Role.TABLE_CELL:
        return RoleStyle(
            **base,
            size_pt=style.table.cell_size_pt,
            bold=False,
            align=style.table.cell_align,
            line_spacing=style.table.line_spacing,
            space_before_pt=0.0,
            space_after_pt=0.0,
        )

    raise ValueError(f"未知段落角色：{role}")
