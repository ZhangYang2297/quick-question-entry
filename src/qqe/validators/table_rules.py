"""表格结构规则。表格一旦错位会连带整题报废，所以这里不放水。"""

from __future__ import annotations

from qqe.domain.models import Table
from qqe.validators.types import Severity, ValidationIssue

EMPTY_CELL_RATIO_LIMIT = 0.5


def validate_tables(
    tables: list[Table], *, question_index: int | None = None
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for table_index, table in enumerate(tables):
        if not table.rows:
            issues.append(
                ValidationIssue(
                    code="table_empty",
                    message=f"第 {table_index + 1} 个表格没有数据行",
                    question_index=question_index,
                    field="tables",
                )
            )
            continue

        width = table.column_count
        for row_index, row in enumerate(table.rows):
            if len(row) != width:
                issues.append(
                    ValidationIssue(
                        code="table_row_width_mismatch",
                        message=(
                            f"第 {table_index + 1} 个表格第 {row_index + 1} 行有 {len(row)} 格，"
                            f"应为 {width} 格"
                        ),
                        question_index=question_index,
                        field="tables",
                    )
                )

        if table.headers and any(not header.strip() for header in table.headers):
            issues.append(
                ValidationIssue(
                    code="table_header_empty",
                    message=f"第 {table_index + 1} 个表格存在空表头",
                    severity=Severity.WARNING,
                    question_index=question_index,
                    field="tables",
                )
            )

        total_cells = width * len(table.rows)
        empty_cells = sum(1 for row in table.rows for cell in row if not cell.strip())
        if total_cells and empty_cells / total_cells > EMPTY_CELL_RATIO_LIMIT:
            issues.append(
                ValidationIssue(
                    code="table_too_many_empty_cells",
                    message=f"第 {table_index + 1} 个表格空单元格过多，疑似漏识别",
                    severity=Severity.WARNING,
                    question_index=question_index,
                    field="tables",
                )
            )
    return issues
