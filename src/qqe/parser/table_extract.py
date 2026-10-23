"""表格归一化与矩形化。

本项目表格无合并单元格，所以矩形化的动作只有两个：补空格 / 截多余格。
"""

from __future__ import annotations

import unicodedata

from qqe.domain.models import Question, Table


def normalize_cell(text: str | None) -> str:
    if text is None:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    return normalized.replace("\u3000", " ").strip()


def normalize_table(table: Table) -> Table:
    return Table(
        caption=normalize_cell(table.caption),
        headers=[normalize_cell(header) for header in table.headers],
        rows=[[normalize_cell(cell) for cell in row] for row in table.rows],
        source_bbox=table.source_bbox,
    )


def repair_row_widths(table: Table) -> Table:
    width = table.column_count
    if width == 0:
        return table
    fixed_rows = []
    changed = False
    for row in table.rows:
        if len(row) == width:
            fixed_rows.append(list(row))
        elif len(row) < width:
            fixed_rows.append(list(row) + [""] * (width - len(row)))
            changed = True
        else:
            fixed_rows.append(list(row)[:width])
            changed = True
    if not changed:
        return table
    return table.model_copy(update={"rows": fixed_rows})


def normalize_tables_in(questions: list[Question]) -> int:
    """就地归一化所有题目的表格，返回处理过的表格数量。"""
    count = 0
    for question in questions:
        if not question.tables:
            continue
        question.tables = [repair_row_widths(normalize_table(table)) for table in question.tables]
        count += len(question.tables)
    return count
