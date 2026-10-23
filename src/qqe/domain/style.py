"""样式规格（Single Source of Truth）。

**格式统一靠这个对象，不靠渲染器里的常量。**
`DocxRenderer` 与 `CssRenderer` 都只读它：同一份 StyleSpec 在两边解释一致，
用户在前端预览看到的排版才等于最终 .docx。

设计约束：
1. 所有字段都有明确默认值，**不允许 None** —— 避免"没填"与"填了默认"两种语义混在一起。
2. 字段按角色分组（页面/字体/题干/选项/判断题/表格/大题/标题），换样式只换这张表。
3. 预设模板是常量，取用时深拷贝，避免调用方改坏全局预设。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"

# 纸张尺寸（毫米，宽 × 高）
PAPER_MM: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "B5": (176.0, 250.0),
}


class PaperSize(StrEnum):
    A4 = "A4"
    B5 = "B5"


class Align(StrEnum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


class NumberFormat(StrEnum):
    DOT = "dot"  # 1.
    CN_DOT = "cn_dot"  # 1、
    FULLWIDTH_DOT = "fullwidth_dot"  # 1．
    PREFIX = "prefix"  # 第1题


class OptionMarker(StrEnum):
    DOT = "dot"  # A.
    CN_DOT = "cn_dot"  # A、
    PAREN = "paren"  # (A)


class ParenPosition(StrEnum):
    PREFIX = "prefix"
    SUFFIX = "suffix"


class ParenStyle(StrEnum):
    FULLWIDTH = "fullwidth"  # （　）
    HALFWIDTH = "halfwidth"  # ( )


class PageStyle(BaseModel):
    paper: PaperSize = PaperSize.A4
    margin_top_cm: float = 2.54
    margin_bottom_cm: float = 2.54
    margin_left_cm: float = 3.17
    margin_right_cm: float = 3.17
    header_text: str = ""
    footer_page_number: bool = False


class FontStyle(BaseModel):
    """全局字体：中文走 w:eastAsia，西文走 ascii/hAnsi。"""

    cjk: str = "宋体"
    latin: str = "Times New Roman"
    size_pt: float = 10.5
    color: str = Field(default="#000000", pattern=_COLOR_PATTERN)


class StemStyle(BaseModel):
    size_pt: float = 10.5
    bold: bool = False
    line_spacing: float = 1.5
    space_before_pt: float = 0.0
    space_after_pt: float = 6.0
    first_line_indent_chars: float = 0.0
    align: Align = Align.JUSTIFY
    number_format: NumberFormat = NumberFormat.DOT


class OptionStyle(BaseModel):
    size_pt: float = 10.5
    bold: bool = False
    line_spacing: float = 1.5
    space_before_pt: float = 0.0
    space_after_pt: float = 2.0
    left_indent_chars: float = 2.0
    options_per_line: int = Field(default=1, ge=1, le=5)
    marker: OptionMarker = OptionMarker.DOT


class TrueFalseStyle(BaseModel):
    paren_position: ParenPosition = ParenPosition.SUFFIX
    paren_style: ParenStyle = ParenStyle.FULLWIDTH


class TableStyle(BaseModel):
    header_bold: bool = True
    header_background: str = Field(default="#F2F2F2", pattern=r"^(#[0-9A-Fa-f]{6})?$")
    cell_size_pt: float = 10.0
    cell_padding_pt: float = 3.0
    border_width_pt: float = Field(default=0.5, ge=0.0, le=3.0)
    border_color: str = Field(default="#000000", pattern=_COLOR_PATTERN)
    align: Align = Align.CENTER  # 表格整体对齐
    cell_align: Align = Align.LEFT  # 单元格内文字对齐
    caption_align: Align = Align.CENTER
    repeat_header: bool = True
    caption_size_pt: float = 10.0
    line_spacing: float = 1.2


class SectionStyle(BaseModel):
    """大题标题（如"一、单项选择题"）。"""

    size_pt: float = 12.0
    bold: bool = True
    align: Align = Align.LEFT
    space_before_pt: float = 12.0
    space_after_pt: float = 6.0


class TitleStyle(BaseModel):
    """文档大标题（项目名/卷名）。"""

    size_pt: float = 16.0
    bold: bool = True
    align: Align = Align.CENTER
    space_after_pt: float = 12.0


class StyleSpec(BaseModel):
    name: str = "标准试卷版"
    page: PageStyle = Field(default_factory=PageStyle)
    font: FontStyle = Field(default_factory=FontStyle)
    stem: StemStyle = Field(default_factory=StemStyle)
    option: OptionStyle = Field(default_factory=OptionStyle)
    true_false: TrueFalseStyle = Field(default_factory=TrueFalseStyle)
    table: TableStyle = Field(default_factory=TableStyle)
    section: SectionStyle = Field(default_factory=SectionStyle)
    title: TitleStyle = Field(default_factory=TitleStyle)

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, payload: dict) -> StyleSpec:
        return cls.model_validate(payload)


def _standard() -> StyleSpec:
    return StyleSpec(name="标准试卷版")


def _exam_print() -> StyleSpec:
    """题库打印版：字略小、行距收紧、选项一行两个，适合大量刷题打印。"""
    return StyleSpec(
        name="题库打印版",
        page=PageStyle(margin_left_cm=2.5, margin_right_cm=2.5),
        stem=StemStyle(size_pt=10.5, line_spacing=1.3, space_after_pt=4.0),
        option=OptionStyle(size_pt=10.5, line_spacing=1.3, options_per_line=2),
        table=TableStyle(cell_size_pt=9.5),
    )


def _compact() -> StyleSpec:
    """紧凑省纸版：小字号、窄页边距、选项一行两个，最大化单页题量。"""
    return StyleSpec(
        name="紧凑省纸版",
        page=PageStyle(
            margin_top_cm=1.8,
            margin_bottom_cm=1.8,
            margin_left_cm=1.8,
            margin_right_cm=1.8,
        ),
        font=FontStyle(size_pt=9.0),
        stem=StemStyle(size_pt=9.0, line_spacing=1.1, space_after_pt=2.0),
        option=OptionStyle(size_pt=9.0, line_spacing=1.1, space_after_pt=0.0, options_per_line=2),
        table=TableStyle(cell_size_pt=9.0, cell_padding_pt=2.0, line_spacing=1.0),
        section=SectionStyle(size_pt=11.0, space_before_pt=8.0, space_after_pt=4.0),
        title=TitleStyle(size_pt=14.0, space_after_pt=8.0),
    )


PRESETS: dict[str, StyleSpec] = {
    "标准试卷版": _standard(),
    "题库打印版": _exam_print(),
    "紧凑省纸版": _compact(),
}

DEFAULT_PRESET = "标准试卷版"


def list_presets() -> list[str]:
    return list(PRESETS)


def get_preset(name: str = DEFAULT_PRESET) -> StyleSpec:
    """取预设的**深拷贝**：调用方随便改，都不会污染全局常量。"""
    try:
        preset = PRESETS[name]
    except KeyError as exc:
        raise KeyError(f"未知样式预设：{name}（可选：{'/'.join(PRESETS)}）") from exc
    return StyleSpec.from_dict(preset.to_dict())
