"""CssRenderer：同一份 StyleSpec → CSS 变量 / CSS 文本 / 预览 HTML。

为什么不用"先出 docx 再转 HTML"：慢，而且字体、行距、表格渲染都会失真。
这里让两个渲染器读同一个 StyleSpec，前端看到的松紧与字号就是导出件的样子。

单位换算约定（唯一一处）：
    pt → px：1pt = 96/72 px = 4/3 px（CSS 的 96dpi 基准）
页面宽度直接用 mm，避免 A4/B5 换算误差。
"""

from __future__ import annotations

import html

from qqe.domain.models import QuestionSet
from qqe.domain.style import PAPER_MM, StyleSpec
from qqe.renderer.docx_renderer import ordered_questions
from qqe.renderer.roles import Role, resolve
from qqe.renderer.text import chunk_options, option_line_text, question_text

PT_TO_PX = 96 / 72


def pt_to_px(points: float) -> float:
    return round(points * PT_TO_PX, 3)


def _num(value: float) -> str:
    """去掉无意义的 .0：13.0 → 13，10.5 保持 10.5。"""
    return f"{value:g}"


def _pt(value: float) -> str:
    return f"{_num(value)}pt"


def _px(value: float) -> str:
    return f"{_num(pt_to_px(value))}px"


def css_variables(style: StyleSpec) -> dict[str, str]:
    """StyleSpec → CSS 自定义属性。字段改动必须在这里体现。"""
    width_mm, _height_mm = PAPER_MM[style.page.paper.value]
    stem = resolve(style, Role.QUESTION)
    option = resolve(style, Role.OPTION)
    section = resolve(style, Role.SECTION_TITLE)
    title = resolve(style, Role.DOC_TITLE)
    caption = resolve(style, Role.TABLE_CAPTION)

    return {
        # 页面
        "--qqe-page-width": f"{_num(width_mm)}mm",
        "--qqe-margin-top": f"{_num(style.page.margin_top_cm)}cm",
        "--qqe-margin-bottom": f"{_num(style.page.margin_bottom_cm)}cm",
        "--qqe-margin-left": f"{_num(style.page.margin_left_cm)}cm",
        "--qqe-margin-right": f"{_num(style.page.margin_right_cm)}cm",
        # 字体
        "--qqe-font-cjk": f'"{style.font.cjk}"',
        "--qqe-font-latin": f'"{style.font.latin}"',
        "--qqe-font-size": _pt(style.font.size_pt),
        "--qqe-color": style.font.color,
        # 标题
        "--qqe-title-size": _pt(title.size_pt),
        "--qqe-title-weight": "700" if title.bold else "400",
        "--qqe-title-align": title.align.value,
        "--qqe-title-space-after": _px(title.space_after_pt),
        # 大题
        "--qqe-section-size": _pt(section.size_pt),
        "--qqe-section-weight": "700" if section.bold else "400",
        "--qqe-section-align": section.align.value,
        "--qqe-section-space-before": _px(section.space_before_pt),
        "--qqe-section-space-after": _px(section.space_after_pt),
        # 题干
        "--qqe-stem-size": _pt(stem.size_pt),
        "--qqe-stem-weight": "700" if stem.bold else "400",
        "--qqe-stem-line-height": str(stem.line_spacing),
        "--qqe-stem-space-before": _px(stem.space_before_pt),
        "--qqe-stem-space-after": _px(stem.space_after_pt),
        "--qqe-stem-indent": _px(stem.first_line_indent_pt()),
        "--qqe-stem-align": stem.align.value,
        # 选项
        "--qqe-option-size": _pt(option.size_pt),
        "--qqe-option-weight": "700" if option.bold else "400",
        "--qqe-option-line-height": str(option.line_spacing),
        "--qqe-option-space-before": _px(option.space_before_pt),
        "--qqe-option-space-after": _px(option.space_after_pt),
        "--qqe-option-indent": _px(option.left_indent_pt()),
        # 表格
        "--qqe-table-size": _pt(style.table.cell_size_pt),
        "--qqe-table-line-height": str(style.table.line_spacing),
        "--qqe-table-padding": _px(style.table.cell_padding_pt),
        "--qqe-table-border-width": _pt(style.table.border_width_pt),
        "--qqe-table-border-color": style.table.border_color,
        "--qqe-table-header-bg": style.table.header_background or "transparent",
        "--qqe-table-header-weight": "700" if style.table.header_bold else "400",
        "--qqe-table-align": style.table.align.value,
        "--qqe-table-cell-align": style.table.cell_align.value,
        "--qqe-caption-size": _pt(caption.size_pt),
        "--qqe-caption-align": caption.align.value,
    }


def render_css(style: StyleSpec, prefix: str = ".qqe-doc") -> str:
    variables = css_variables(style)
    lines = [f"{prefix} {{"]
    for name, value in variables.items():
        lines.append(f"  {name}: {value};")
    lines.append("  font-family: var(--qqe-font-cjk), var(--qqe-font-latin);")
    lines.append("}")
    lines.append(prefix + " .qqe-page {")
    lines.append("  width: var(--qqe-page-width);")
    lines.append(
        "  padding: var(--qqe-margin-top) var(--qqe-margin-right) "
        "var(--qqe-margin-bottom) var(--qqe-margin-left);"
    )
    lines.append("  background: #fff; margin: 0 auto; box-sizing: border-box;")
    lines.append("}")
    lines.append(prefix + " .qqe-title {")
    lines.append("  font-size: var(--qqe-title-size); font-weight: var(--qqe-title-weight);")
    lines.append("  text-align: var(--qqe-title-align);")
    lines.append("  margin: 0 0 var(--qqe-title-space-after);")
    lines.append("}")
    lines.append(prefix + " .qqe-section {")
    lines.append("  font-size: var(--qqe-section-size); font-weight: var(--qqe-section-weight);")
    lines.append("  text-align: var(--qqe-section-align);")
    lines.append("  margin: var(--qqe-section-space-before) 0 var(--qqe-section-space-after);")
    lines.append("}")
    lines.append(prefix + " .qqe-question {")
    lines.append("  font-size: var(--qqe-stem-size); font-weight: var(--qqe-stem-weight);")
    lines.append("  line-height: var(--qqe-stem-line-height); text-align: var(--qqe-stem-align);")
    lines.append("  text-indent: var(--qqe-stem-indent);")
    lines.append("  margin: var(--qqe-stem-space-before) 0 var(--qqe-stem-space-after);")
    lines.append("  white-space: pre-wrap;")
    lines.append("}")
    lines.append(prefix + " .qqe-option {")
    lines.append("  font-size: var(--qqe-option-size); font-weight: var(--qqe-option-weight);")
    lines.append("  line-height: var(--qqe-option-line-height);")
    lines.append("  margin: var(--qqe-option-space-before) 0 var(--qqe-option-space-after);")
    lines.append("  padding-left: var(--qqe-option-indent);")
    lines.append("  white-space: pre-wrap;")
    lines.append("}")
    lines.append(prefix + " .qqe-table {")
    lines.append("  border-collapse: collapse; margin: 0 auto;")
    lines.append("  font-size: var(--qqe-table-size); margin-left: auto; margin-right: auto;")
    lines.append("}")
    lines.append(prefix + " .qqe-table th, " + prefix + " .qqe-table td {")
    lines.append("  border: var(--qqe-table-border-width) solid var(--qqe-table-border-color);")
    lines.append("  padding: var(--qqe-table-padding);")
    lines.append("  line-height: var(--qqe-table-line-height);")
    lines.append("  text-align: var(--qqe-table-cell-align);")
    lines.append("}")
    lines.append(prefix + " .qqe-table th {")
    lines.append("  font-weight: var(--qqe-table-header-weight);")
    lines.append("  background: var(--qqe-table-header-bg);")
    lines.append("}")
    lines.append(prefix + " .qqe-caption {")
    lines.append("  font-size: var(--qqe-caption-size); text-align: var(--qqe-caption-align);")
    lines.append("  margin: 0.3em 0;")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def _table_html(table) -> str:
    parts = ['<table class="qqe-table">']
    if table.headers:
        parts.append("<thead><tr>")
        parts.extend(f"<th>{_escape(cell)}</th>" for cell in table.headers)
        parts.append("</tr></thead>")
    parts.append("<tbody>")
    for row in table.rows:
        parts.append("<tr>")
        parts.extend(f"<td>{_escape(cell)}</td>" for cell in row)
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def render_preview_html(question_set: QuestionSet, style: StyleSpec) -> str:
    """给前端/本地预览用的完整 HTML 片段（含内联 CSS）。

    文字内容与 .docx 走同一套排版函数（question_text / option_line_text），
    所以"预览里看到的题号与选项排布"就是导出件里的。
    """
    blocks: list[str] = []
    if question_set.title:
        blocks.append(f'<h1 class="qqe-title">{_escape(question_set.title)}</h1>')

    current_group: str | None = None
    for question in ordered_questions(question_set):
        if question.group_title and question.group_title != current_group:
            blocks.append(f'<h2 class="qqe-section">{_escape(question.group_title)}</h2>')
            current_group = question.group_title
        blocks.append(f'<p class="qqe-question">{_escape(question_text(question, style))}</p>')
        for table in question.tables:
            if table.caption:
                blocks.append(f'<p class="qqe-caption">{_escape(table.caption)}</p>')
            blocks.append(_table_html(table))
        for chunk in chunk_options(question.options, style.option.options_per_line):
            blocks.append(f'<p class="qqe-option">{_escape(option_line_text(chunk, style))}</p>')

    return (
        "<style>\n" + render_css(style) + "</style>\n"
        '<div class="qqe-doc"><div class="qqe-page">\n' + "\n".join(blocks) + "\n</div></div>\n"
    )
