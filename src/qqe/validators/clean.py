"""确定性文本清洗：Prompt 治不掉的固定噪声，在这里用正则收干净。

为什么放在校验层而不是 Prompt：难度星级、行尾作答字母、括号里的考纲备注
都是**版式噪声**，不是语义判断，用确定性规则处理比让模型"再仔细一点"可靠得多。

原则：
1. 只做可逆、可解释的机械替换（正则白名单），不猜测、不改写语义；
2. **每一处改动都记 warning**，校对页能看到"这题的题干被清理过什么"；
3. 清不掉的（如跨页截断的半道题）不硬修 —— 交给残题裁定与人工校对。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qqe.domain.models import Question

# 难度星级：☆☆☆ / ★★ / ◆ 等（模型常把书上的难度标记一起抄进来）
_STARS = re.compile(r"[☆★◆◇●○]+\s*")
# 星级后面紧跟作答字母（"☆☆☆ D" 是最常见的组合）
_STARS_WITH_ANSWER = re.compile(r"[☆★◆◇●○]+\s*[A-Ea-e]\s*$")
# 行尾孤立的作答字母：模型把用户手写的 A/B/C/D 当成了题干结尾
_TRAILING_ANSWER = re.compile(r"(?:^|(?<=\s))[A-Ea-e]$")
# 括号里的元信息：考纲变动、真题出处等，不属于题干
_META_PARENTHESES = re.compile(
    r"[（(][^（）()]{0,40}(?:考试指导|考试变动|考纲|命题要求|命题依据|真题改编|考点变动)"
    r"[^（）()]{0,40}[）)]"
)
_EXTRA_SPACES = re.compile(r"[ \t\u3000]{2,}")
# 题干里被模型粘进来的选项列表：A. xxx B. xxx ...（标签必须**递增且至少两个**才算）
_INLINE_OPTION_MARKER = re.compile(r"(?:^|(?<=\s))([A-E])[.．、]\s*")
# 题干开头自带源题号（"28. 自发性气胸…"）：源题号由 source_label 单独保存，
# 输出件里题号由 order 决定，重复保留会在导出件里出现"2. 28. 题干"。
_LEADING_QUESTION_NUMBER = re.compile(r"^\s*\d{1,3}\s*[.．、]\s*(?!\d)")
# 大题标题里的序号：模型偶尔把题干整句塞进 group_title（"28. 自发性气胸…"）
_GROUP_TITLE_WITH_NUMBER = re.compile(r"^\s*\d{1,3}\s*[.．、]\s*\S")

NOTE_LABELS = {
    "removed_meta": "已移除括号内元信息（考纲/真题备注）",
    "removed_stars": "已清除难度星级",
    "removed_trailing_answer": "已清除行尾作答字母",
    "removed_leading_number": "已移除题干开头的源题号",
    "removed_inline_options": "已移除题干里重复的选项列表",
    "dropped_group_title": "已移除疑似题干的组标题",
    "normalized_spaces": "已合并多余空格",
}


def split_inline_options(text: str) -> tuple[str, bool]:
    """把题干末尾粘着的选项序列切掉。

    只在**出现至少两个递增标签**（A→B / B→C …）时才动手：
    题干里孤零零一个 "A." 不动，避免误伤正文。
    返回 (剩余题干, 是否切过)。
    """
    markers = list(_INLINE_OPTION_MARKER.finditer(text))
    for start, marker in enumerate(markers):
        expected = ord(marker.group(1))
        hits = 1
        for later in markers[start + 1 :]:
            code = ord(later.group(1))
            if code == expected + 1:
                hits += 1
                expected = code
            elif code > expected + 1:
                break
        if hits >= 2:
            return text[: marker.start()].strip(), True
    return text, False


def clean_text(text: str) -> tuple[str, list[str]]:
    """返回 (清洗后的文本, 改动说明)。文本没变时说明为空列表。"""
    original = text or ""
    cleaned = original
    notes: list[str] = []

    cleaned, cut = split_inline_options(cleaned)
    if cut:
        notes.append(NOTE_LABELS["removed_inline_options"])
    cleaned, count = _LEADING_QUESTION_NUMBER.subn("", cleaned)
    if count:
        notes.append(NOTE_LABELS["removed_leading_number"])
    cleaned, count = _META_PARENTHESES.subn("", cleaned)
    if count:
        notes.append(NOTE_LABELS["removed_meta"])
    cleaned, count = _STARS_WITH_ANSWER.subn("", cleaned)
    if count:
        notes.extend([NOTE_LABELS["removed_stars"], NOTE_LABELS["removed_trailing_answer"]])
    cleaned, count = _STARS.subn("", cleaned)
    if count and NOTE_LABELS["removed_stars"] not in notes:
        notes.append(NOTE_LABELS["removed_stars"])
    cleaned, count = _TRAILING_ANSWER.subn("", cleaned)
    if count and NOTE_LABELS["removed_trailing_answer"] not in notes:
        notes.append(NOTE_LABELS["removed_trailing_answer"])
    cleaned, count = _EXTRA_SPACES.subn(" ", cleaned)
    if count:
        notes.append(NOTE_LABELS["normalized_spaces"])

    cleaned = cleaned.strip()
    if cut:
        cleaned = cleaned.rstrip("，,、;；:：")
    if cleaned != original and not notes:
        notes.append(NOTE_LABELS["normalized_spaces"])
    return cleaned, notes


def clean_questions(questions: list[Question]) -> dict[int, list[str]]:
    """就地清洗题干、选项与组标题，返回 {题目下标: 改动说明}。"""
    touched: dict[int, list[str]] = {}
    for index, question in enumerate(questions):
        notes: list[str] = []
        question.stem, stem_notes = clean_text(question.stem)
        notes.extend(stem_notes)
        for option in question.options:
            option.text, option_notes = clean_text(option.text)
            notes.extend(note for note in option_notes if note not in notes)
        if question.group_title and _GROUP_TITLE_WITH_NUMBER.match(question.group_title):
            # 组标题里出现题号说明模型把题干塞错了字段；留着会让导出件多出一行假题干
            question.group_title = None
            notes.append(NOTE_LABELS["dropped_group_title"])
        if notes:
            touched[index] = notes
    return touched
