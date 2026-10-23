"""渲染层：QuestionSet + StyleSpec → .docx（唯一交付物生成者）。"""

from __future__ import annotations

from qqe.renderer.docx_renderer import DocxRenderer, RenderError, ordered_questions, render_docx
from qqe.renderer.roles import Role, RoleStyle, resolve
from qqe.renderer.table_renderer import add_table

__all__ = [
    "DocxRenderer",
    "RenderError",
    "Role",
    "RoleStyle",
    "add_table",
    "ordered_questions",
    "render_docx",
    "resolve",
]
