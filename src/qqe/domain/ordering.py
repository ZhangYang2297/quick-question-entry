"""题目排序与重编号 —— 本项目唯一允许决定「顺序」的地方。

两个函数职责严格分离（这是续加能正确工作的地基）：

1. `order_by_layout()` —— **批次内版面初始落位**
   排序键优先级（不可调换）：
       1. upload_order  批次内图片上传顺序（用户点选顺序）
       2. page_index    PDF 内的页序
       3. column        版面栏号（0=左栏/单栏，1=右栏）—— 双栏书页必须先左后右
       4. bbox_y        栏内题目纵坐标
   **只在新批次解析完成时用一次**，不写 order。

2. `renormalize()` —— **编号派生**
   完全不排序，只按**列表位置**写 order = 1..N。
   因为「列表顺序」才是顺序的唯一真相，续加时已有题目原位不动。

严禁在此模块之外用源题号或文件名排序。
"""

from __future__ import annotations

from collections.abc import Iterable

from qqe.domain.models import Question


def sort_key(question: Question) -> tuple[int, int, int, float]:
    return (
        question.upload_order,
        question.page_index,
        question.column,
        question.bbox_y,
    )


def order_by_layout(questions: Iterable[Question]) -> list[Question]:
    """按版面键排序后返回新列表。**不修改 order**（编号交给 renormalize）。"""
    return sorted(questions, key=sort_key)


def renormalize(questions: Iterable[Question]) -> list[Question]:
    """按当前列表位置重写 order = 1..N。**不排序**，也不改变列表顺序。

    幂等：对已编号的列表再跑一次，结果不变。
    id 与 source_label 原样保留。
    """
    ordered = list(questions)
    for index, question in enumerate(ordered, start=1):
        question.order = index
    return ordered


def assign_order(questions: Iterable[Question]) -> list[Question]:
    """批次合并的组合动作：先版面落位，再统一编号。"""
    return renormalize(order_by_layout(questions))
