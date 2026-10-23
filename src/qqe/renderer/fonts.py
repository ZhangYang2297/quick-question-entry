"""中文 docx 字体封装。

**必须同时设置 `w:eastAsia`**：python-docx 的 `run.font.name` 只写 ascii/hAnsi，
中文会回落到默认字体（往往是等线），导出件看起来"不是设置的字体"。
这个坑在本项目里是硬约束，有 XML 级单测兜底。
"""

from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from docx.text.run import Run

from qqe.renderer.roles import RoleStyle


def _get_or_add_rfonts(rpr):
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    return rfonts


def apply_font(
    run: Run,
    *,
    cjk: str,
    latin: str,
    size_pt: float,
    color: str = "#000000",
    bold: bool = False,
) -> Run:
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run.font.color.rgb = RGBColor.from_string(color.lstrip("#").upper())
    # 西文
    run.font.name = latin
    # 中文（关键）：eastAsia 属性才是 Word 里真正生效的中文字体
    rfonts = _get_or_add_rfonts(run._element.get_or_add_rPr())
    rfonts.set(qn("w:ascii"), latin)
    rfonts.set(qn("w:hAnsi"), latin)
    rfonts.set(qn("w:eastAsia"), cjk)
    rfonts.set(qn("w:cs"), latin)
    return run


def apply_role_font(run: Run, role_style: RoleStyle) -> Run:
    return apply_font(
        run,
        cjk=role_style.cjk,
        latin=role_style.latin,
        size_pt=role_style.size_pt,
        color=role_style.color,
        bold=role_style.bold,
    )
