"""领域模型。所有跨模块传递的数据结构都在这里定义。

两条铁律：
1. 模型输出契约（PageParse / PageQuestion）中**没有 order 字段** —— 题目顺序绝不交给模型。
2. Table 一律规整矩形（本项目表格无合并单元格），不引入 spans。
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


class QuestionType(StrEnum):
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    TRUE_FALSE = "true_false"
    FILL_BLANK = "fill_blank"
    SHORT_ANSWER = "short_answer"
    TERM_DEFINE = "term_define"
    CASE_ANALYSIS = "case_analysis"


CHOICE_TYPES = (QuestionType.SINGLE_CHOICE, QuestionType.MULTI_CHOICE)


class Option(BaseModel):
    label: str
    text: str
    source_bbox: list[float] | None = None


class Table(BaseModel):
    caption: str = ""
    headers: list[str] = []
    rows: list[list[str]] = []
    source_bbox: list[float] | None = None

    @property
    def column_count(self) -> int:
        if self.headers:
            return len(self.headers)
        return len(self.rows[0]) if self.rows else 0

    def is_rectangular(self) -> bool:
        width = self.column_count
        if width == 0:
            return False
        return all(len(row) == width for row in self.rows)


class PageQuestion(BaseModel):
    """单张图片中识别到的一道题 —— 即**模型的输出契约**。

    刻意不包含 id / order / upload_order / page_index / batch_seq / source_file：
    这些全部由代码计算或分配。**顺序绝不交给模型。**

    column / is_fragment / fragment_reason 是模型对「版面」与「完整性」的**提议**：
    - column：双栏书页的栏号（0=左栏/单栏，1=右栏），排序要用
    - is_fragment：疑似跨页残题。模型只标记，**是否丢弃由校验器与合并层裁定**
    """

    source_label: str | None = None
    type: QuestionType
    stem: str
    options: list[Option] = []
    tables: list[Table] = []
    group_title: str | None = None
    source_bbox: list[float] | None = None
    column: int = 0
    is_fragment: bool = False
    fragment_reason: str | None = None

    def to_question(
        self,
        upload_order: int,
        page_index: int,
        source_file: str | None = None,
    ) -> Question:
        return Question(
            **self.model_dump(),
            upload_order=upload_order,
            page_index=page_index,
            source_file=source_file,
        )


class PageParse(BaseModel):
    """一张图片的解析结果契约。"""

    title: str | None = None
    groups: list[str] = []
    questions: list[PageQuestion] = []

    def to_questions(
        self,
        upload_order: int,
        page_index: int,
        source_file: str | None = None,
    ) -> list[Question]:
        return [q.to_question(upload_order, page_index, source_file) for q in self.questions]


class Question(BaseModel):
    """流水线内部的题目对象。

    - `id` 是**身份**（跨批次、跨编辑不变）。
    - `order` 是**位置**，由 renormalize() 按列表位置派生（0 表示尚未分配）。
    """

    # 稳定身份：续加时靠它保证"用户改过的老题"不被当成新题
    id: str = Field(default_factory=lambda: uuid4().hex)
    # 输出序号：渲染的唯一依据（0 表示尚未分配）
    order: int = 0
    # 溯源信息：不参与排序，也不参与校验，且不显示在导出件中
    source_label: str | None = None
    upload_order: int = 0
    page_index: int = 0
    batch_seq: int = 0  # 来自第几个录入批次（1 基），仅溯源
    source_file: str | None = None  # 来自哪张图，供校对页回看原图

    type: QuestionType
    stem: str
    options: list[Option] = []
    tables: list[Table] = []
    answer: str | None = None  # 本期不采集，恒为 None
    explanation: str | None = None  # 本期不采集
    group_title: str | None = None
    score: float | None = None
    confidence: float = 1.0
    warnings: list[str] = []
    source_bbox: list[float] | None = None
    # 完整性与版面：模型提议，代码裁定（见 Task 1.3 / 1.5）
    column: int = 0  # 版面栏号：0=左栏/单栏，1=右栏（双栏书页排序必需）
    is_fragment: bool = False  # 疑似残题（模型提议）
    fragment_reason: str | None = None  # 如 "options_only" / "stem_only" / "validator:options_lt_2"

    @property
    def bbox_y(self) -> float:
        """排序第四键：页面纵坐标。无 bbox 时排在本页末尾。"""
        return self.source_bbox[1] if self.source_bbox else float("inf")


class QuestionSet(BaseModel):
    title: str | None = None
    groups: list[str] = []
    # **列表顺序 = 顺序的唯一真相**；order 为按位置派生的值
    questions: list[Question] = []
    meta: dict = {}


def now_iso() -> str:
    """统一的 UTC 时间戳格式（秒级，便于排序与肉眼阅读）。"""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class BatchRecord(BaseModel):
    """一次录入批次的审计记录：进了多少题、哪几张失败、排除了哪些残题。

    `state` 只允许 merged / discarded：**只有 merged 的批次才贡献题目**。
    """

    id: str = Field(default_factory=lambda: uuid4().hex)
    seq: int
    created_at: str = Field(default_factory=now_iso)
    style_name: str | None = None
    image_count: int = 0
    question_ids: list[str] = []
    failed: list[str] = []
    excluded_ids: list[str] = []
    state: str = "merged"


class ExportRecord(BaseModel):
    """一次导出。全量导出是默认；incremental 只含该批新增题（题号从 1 重算）。"""

    id: str = Field(default_factory=lambda: uuid4().hex)
    mode: str = "full"  # full | incremental
    batch_seq: int | None = None  # incremental 时记录来自哪一批
    file_name: str = ""
    path: str | None = None  # 服务端落盘位置（下载时用）
    question_count: int = 0
    created_at: str = Field(default_factory=now_iso)


class Project(BaseModel):
    """服务端的「文档项目」——续加的载体。

    **顺序的唯一真相是 `question_set.questions` 的列表顺序**；
    `order` 是派生值，任何结构变更后都必须 `renormalize()`。
    """

    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str = "未命名文档"
    style_name: str = "标准试卷版"
    # 项目级自定义样式（完整 StyleSpec dict）。为 None 表示"直接用 style_name 预设"。
    # 存在这里而不是只存预设名：样式是项目级资产，改一次对整份文档（含历史批次）生效。
    custom_style: dict | None = None
    owner_id: str = "local"
    question_set: QuestionSet = Field(default_factory=QuestionSet)
    batches: list[BatchRecord] = []
    # 被裁定为残题的题不丢弃，留在项目里供校对页"已排除"区恢复
    excluded: list[Question] = []
    exports: list[ExportRecord] = []
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    deleted_at: str | None = None  # 软删除时间；非空 = 在回收站

    @property
    def question_count(self) -> int:
        return len(self.question_set.questions)

    @property
    def next_batch_seq(self) -> int:
        return max((record.seq for record in self.batches), default=0) + 1

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
