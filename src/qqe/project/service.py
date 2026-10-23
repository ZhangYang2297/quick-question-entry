"""文档项目服务：续加、调序、编辑、复制、软删除、导出的唯一入口。

**为什么要有这一层**：API 和 CLI 都通过它改项目，规则只写一遍：
1. 任何结构变更（续加 / 调序 / 删题 / 拆并 / 改题）之后必须 `renormalize()`；
2. 同一项目的写操作串行（`ProjectLocks`），并发续加不会互相覆盖；
3. 复制项目必须**逐个重生成题目 id**，否则两份文档共享身份、互相污染；
4. 删除是软删除；彻底删除只允许从回收站发起。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from qqe.domain.models import (
    BatchRecord,
    ExportRecord,
    Project,
    Question,
    QuestionSet,
    now_iso,
)
from qqe.domain.ordering import renormalize
from qqe.domain.style import DEFAULT_PRESET, StyleSpec, get_preset
from qqe.project.document import DEFAULT_PROJECT_NAME, apply_batch
from qqe.renderer.docx_renderer import render_docx
from qqe.store.db import BatchNotFound, ProjectNotFound, QuestionNotFound, Store
from qqe.store.locks import ProjectLocks

_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\r\n\t]+')


class InvalidOrderError(ValueError):
    """调序请求的 id 集合与项目现有题目不一致。"""


class BatchConflictError(ValueError):
    """批次已被确认或已放弃，不能重复处理。"""


def _safe_filename(name: str) -> str:
    cleaned = _UNSAFE_FILENAME.sub("_", name).strip(" .")
    return cleaned or "未命名文档"


def _ensure_style(style_name: str) -> None:
    """未知样式统一翻译成 ValueError（API 层 → 400，而不是 500）。"""
    try:
        get_preset(style_name)
    except KeyError as exc:
        raise ValueError(str(exc).strip("'\"")) from exc


class ProjectService:
    def __init__(
        self,
        store: Store,
        *,
        locks: ProjectLocks | None = None,
        out_dir: str | Path = "out",
    ) -> None:
        self.store = store
        self.locks = locks or ProjectLocks()
        self.out_dir = Path(out_dir)

    # ---- 读 -------------------------------------------------------------
    def list_projects(self, *, owner_id: str | None = None, trash: bool = False) -> list[Project]:
        return self.store.list_projects(owner_id=owner_id, trash=trash)

    def get_project(
        self,
        project_id: str,
        *,
        owner_id: str | None = None,
        include_deleted: bool = False,
    ) -> Project:
        project = self.store.get_project(project_id, include_deleted=include_deleted)
        if project is None:
            raise ProjectNotFound(project_id)
        if owner_id is not None and project.owner_id != owner_id:
            # 越权与不存在返回同样的错误，避免泄漏"这个 id 存在"
            raise ProjectNotFound(project_id)
        return project

    def get_batch(self, batch_id: str) -> tuple[BatchRecord, str]:
        found = self.store.get_batch(batch_id)
        if found is None:
            raise BatchNotFound(batch_id)
        return found

    # ---- 创建与元信息 ---------------------------------------------------
    def create_project(
        self,
        *,
        name: str | None = None,
        style_name: str = DEFAULT_PRESET,
        owner_id: str = "local",
    ) -> Project:
        _ensure_style(style_name)  # 未知样式提前报错
        project = Project(
            name=(name or "").strip() or DEFAULT_PROJECT_NAME,
            style_name=style_name,
            owner_id=owner_id,
        )
        return self.store.create_project(project)

    def rename_project(self, project_id: str, name: str) -> Project:
        with self.locks.hold(project_id):
            self.get_project(project_id)
            self.store.update_meta(project_id, name=(name or "").strip() or DEFAULT_PROJECT_NAME)
            return self.get_project(project_id)

    def set_style(self, project_id: str, style_name: str) -> Project:
        """切预设：**同时清掉自定义样式**，否则切了预设还是按老的自定义渲染。"""
        _ensure_style(style_name)
        with self.locks.hold(project_id):
            self.get_project(project_id)
            self.store.update_meta(project_id, style_name=style_name, custom_style=None)
            return self.get_project(project_id)

    def set_style_spec(self, project_id: str, spec) -> Project:
        """保存项目级自定义样式（完整 StyleSpec）。样式对整份文档立即生效。"""
        payload = spec.to_dict()
        with self.locks.hold(project_id):
            self.get_project(project_id)
            self.store.update_meta(
                project_id, style_name=payload.get("name") or "自定义", custom_style=payload
            )
            return self.get_project(project_id)

    def style_of(self, project: Project):
        """项目实际生效的样式：自定义优先，否则用预设。导出与预览都走这里。"""
        if project.custom_style:
            return StyleSpec.from_dict(project.custom_style)
        return get_preset(project.style_name)

    # ---- 续加 -----------------------------------------------------------
    def append_batch(
        self,
        project_id: str,
        batch,
        *,
        style_name: str | None = None,
        record_id: str | None = None,
        order_locked: bool = False,
    ) -> tuple[Project, BatchRecord]:
        """把一批解析结果追加到末尾。**新题接在最后，老题原位不动。**"""
        with self.locks.hold(project_id):
            project = self.get_project(project_id)
            merged, record, excluded = apply_batch(
                project.question_set,
                project.batches,
                project.excluded,
                batch,
                style_name=style_name or project.style_name,
                record_id=record_id,
                order_locked=order_locked,
            )
            self.store.save_questions(project_id, merged.questions, excluded)
            self.store.insert_batch(project_id, record)
            if merged.title:
                self.store.update_meta(project_id, title=merged.title, groups=merged.groups)
            if style_name:
                self.store.update_meta(project_id, style_name=style_name, custom_style=None)
            return self.get_project(project_id), record

    # ---- 结构变更 -------------------------------------------------------
    def reorder(self, project_id: str, ordered_question_ids: list[str]) -> Project:
        with self.locks.hold(project_id):
            project = self.get_project(project_id)
            current = project.question_set.questions
            by_id = {question.id: question for question in current}
            if len(ordered_question_ids) != len(current) or set(ordered_question_ids) != set(by_id):
                raise InvalidOrderError(
                    f"调序请求包含 {len(ordered_question_ids)} 个题目 id，"
                    f"与项目现有 {len(current)} 题不一致（必须完整且不重复）"
                )
            questions = renormalize([by_id[qid] for qid in ordered_question_ids])
            self.store.save_questions(project_id, questions, project.excluded)
            return self.get_project(project_id)

    def remove_question(self, project_id: str, question_id: str) -> Project:
        with self.locks.hold(project_id):
            project = self.get_project(project_id)
            remaining = [q for q in project.question_set.questions if q.id != question_id]
            if len(remaining) == len(project.question_set.questions):
                raise QuestionNotFound(question_id)
            self.store.save_questions(project_id, renormalize(remaining), project.excluded)
            # 批次审计里不再引用已删除的题（否则「仅导出本批新增」会缺题）
            for batch in project.batches:
                if question_id in batch.question_ids:
                    batch.question_ids = [qid for qid in batch.question_ids if qid != question_id]
                    self.store.insert_batch(project_id, batch)
            return self.get_project(project_id)

    def replace_question(self, question_id: str, replacement: Question) -> Project:
        """PATCH 整题替换：身份（id）与位置不变，内容整体换掉。"""
        found = self.store.get_question(question_id)
        if found is None:
            raise QuestionNotFound(question_id)
        _, project_id = found
        with self.locks.hold(project_id):
            project = self.get_project(project_id)
            questions = project.question_set.questions
            index = next(i for i, q in enumerate(questions) if q.id == question_id)
            kept = replacement.model_copy(
                update={
                    "id": question_id,
                    "order": questions[index].order,
                    "batch_seq": questions[index].batch_seq,
                }
            )
            questions[index] = kept
            self.store.save_questions(project_id, questions, project.excluded)
            return self.get_project(project_id)

    def split_question(self, project_id: str, question_id: str, parts: list[Question]) -> Project:
        """把一道题拆成多道（拆出来的都是新身份，避免与原文共享 id）。"""
        if not parts:
            raise ValueError("拆分至少要保留一道题")
        with self.locks.hold(project_id):
            project = self.get_project(project_id)
            questions = project.question_set.questions
            index = next((i for i, q in enumerate(questions) if q.id == question_id), None)
            if index is None:
                raise QuestionNotFound(question_id)
            original = questions[index]
            fresh = [
                part.model_copy(update={"id": uuid4().hex, "batch_seq": original.batch_seq})
                for part in parts
            ]
            self.store.save_questions(
                project_id,
                renormalize(questions[:index] + fresh + questions[index + 1 :]),
                project.excluded,
            )
            return self.get_project(project_id)

    def merge_questions(
        self, project_id: str, question_ids: list[str], merged: Question
    ) -> Project:
        """合并**相邻**的几道题为一道，落在最前面那道题的位置上。"""
        if len(question_ids) < 2:
            raise ValueError("合并至少需要两道题")
        with self.locks.hold(project_id):
            project = self.get_project(project_id)
            questions = project.question_set.questions
            positions = [i for i, q in enumerate(questions) if q.id in set(question_ids)]
            if len(positions) != len(question_ids):
                raise QuestionNotFound(",".join(question_ids))
            if positions != list(range(min(positions), min(positions) + len(positions))):
                raise ValueError("只能合并相邻的题目")
            start = positions[0]
            first = questions[start]
            replacement = merged.model_copy(update={"id": first.id, "batch_seq": first.batch_seq})
            tail = questions[positions[-1] + 1 :]
            self.store.save_questions(
                project_id,
                renormalize([*questions[:start], replacement, *tail]),
                project.excluded,
            )
            return self.get_project(project_id)

    def restore_excluded(
        self, project_id: str, question_id: str, position: int | None = None
    ) -> Project:
        """把「已排除」的残题恢复到正式清单（校对页的兜底动作）。"""
        with self.locks.hold(project_id):
            project = self.get_project(project_id)
            target = next((q for q in project.excluded if q.id == question_id), None)
            if target is None:
                raise QuestionNotFound(question_id)
            remaining_excluded = [q for q in project.excluded if q.id != question_id]
            questions = list(project.question_set.questions)
            index = len(questions) if position is None else max(0, min(position, len(questions)))
            questions.insert(index, target.model_copy(update={"is_fragment": False}))
            self.store.save_questions(project_id, renormalize(questions), remaining_excluded)
            return self.get_project(project_id)

    # ---- 文档管理 -------------------------------------------------------
    def duplicate_project(self, project_id: str, *, name: str | None = None) -> Project:
        """深拷贝一份文档。

        **必须逐个重生成题目 id**：否则两份文档共享同一批身份，
        改副本会顺着 id 改到原件（数据层看起来完全正常，但语义已错）。
        """
        with self.locks.hold(project_id):
            source = self.get_project(project_id)
            id_map = {
                question.id: uuid4().hex
                for question in [*source.question_set.questions, *source.excluded]
            }

            copied_questions = [
                question.model_copy(update={"id": id_map[question.id]})
                for question in source.question_set.questions
            ]
            copied_excluded = [
                question.model_copy(update={"id": id_map[question.id]})
                for question in source.excluded
            ]
            copied_batches = [
                batch.model_copy(
                    deep=True,
                    update={
                        "id": uuid4().hex,
                        "question_ids": [
                            id_map[qid] for qid in batch.question_ids if qid in id_map
                        ],
                        "excluded_ids": [
                            id_map[qid] for qid in batch.excluded_ids if qid in id_map
                        ],
                    },
                )
                for batch in source.batches
            ]
            copied_exports = [
                record.model_copy(update={"id": uuid4().hex}) for record in source.exports
            ]
            copy = Project(
                name=(name or "").strip() or f"{source.name} 副本",
                style_name=source.style_name,
                custom_style=dict(source.custom_style) if source.custom_style else None,
                owner_id=source.owner_id,
                question_set=QuestionSet(
                    title=source.question_set.title,
                    groups=list(source.question_set.groups),
                    questions=renormalize(copied_questions),
                ),
                batches=copied_batches,
                excluded=copied_excluded,
                exports=copied_exports,
            )
            return self.store.create_project(copy)

    def soft_delete(self, project_id: str) -> Project:
        with self.locks.hold(project_id):
            self.get_project(project_id)
            self.store.update_meta(project_id, deleted_at=now_iso())
            return self.get_project(project_id, include_deleted=True)

    def restore(self, project_id: str) -> Project:
        with self.locks.hold(project_id):
            self.get_project(project_id, include_deleted=True)
            self.store.update_meta(project_id, deleted_at=None)
            return self.get_project(project_id)

    def purge(self, project_id: str) -> None:
        """彻底删除：**只允许对回收站里的文档执行**，防误删。"""
        with self.locks.hold(project_id):
            project = self.store.get_project(project_id, include_deleted=True)
            if project is None:
                raise ProjectNotFound(project_id)
            if project.deleted_at is None:
                raise ValueError("只能彻底删除回收站中的文档（请先删除）")
            self.store.delete_project(project_id)

    # ---- 云同步快照 -----------------------------------------------------
    def snapshot(self, project_id: str, *, owner_id: str | None = None) -> dict:
        """整份项目快照（题目/批次/导出记录/样式/软删除标记），供云端持久化。

        快照是自描述的：重建时保留 id 与 created_at/updated_at，云端的
        updated_at 与本地一致，同步才能比较出新旧。
        """
        project = self.get_project(project_id, owner_id=owner_id, include_deleted=True)
        return project.model_dump(mode="json")

    def import_snapshot(self, snapshot: dict, *, owner_id: str | None = None) -> Project:
        """把云端快照重建为本地项目：同 id 已存在则整体替换，幂等。

        归属归调用方（owner_id）；题目 id / 批次 / 导出记录原样保留。
        """
        project = Project.model_validate(snapshot)
        with self.locks.hold(project.id):
            if self.store.get_project(project.id, include_deleted=True) is not None:
                self.store.delete_project(project.id)
            if owner_id:
                project = project.model_copy(update={"owner_id": owner_id})
            self.store.create_project(project)
            # 快照可能带 deleted_at（回收站文档也要能重建）
            return self.get_project(project.id, include_deleted=True)

    # ---- 导出 -----------------------------------------------------------
    def export(
        self, project_id: str, *, mode: str = "full", batch_seq: int | None = None
    ) -> ExportRecord:
        """从项目题目**全量重渲染**。

        `incremental` 只导出某一批新增题目（题号从 1 重算），是「保留能力」，
        不是文件级追加 —— 导出的 .docx 永远是独立的新文件。
        """
        project = self.get_project(project_id)
        style = self.style_of(project)
        questions = project.question_set.questions
        title = project.question_set.title

        if mode == "incremental":
            seq = batch_seq if batch_seq is not None else self._latest_batch_seq(project)
            if seq is None:
                raise ValueError("项目还没有任何批次，无法仅导出新增题目")
            scoped = [q for q in questions if q.batch_seq == seq]
            if not scoped:
                raise ValueError(f"第 {seq} 批没有可导出的题目")
            set_for_export = QuestionSet(
                title=title,
                groups=project.question_set.groups,
                questions=[q.model_copy(update={"order": i}) for i, q in enumerate(scoped, 1)],
            )
        elif mode == "full":
            seq = None
            set_for_export = project.question_set
        else:
            raise ValueError(f"未知导出模式：{mode}")

        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        suffix = f"_第{seq}批" if mode == "incremental" else ""
        file_name = f"{_safe_filename(project.name)}{suffix}_{stamp}.docx"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / file_name
        path.write_bytes(render_docx(set_for_export, style))

        record = ExportRecord(
            mode=mode,
            batch_seq=seq,
            file_name=file_name,
            path=str(path),
            question_count=len(set_for_export.questions),
        )
        self.store.insert_export(project_id, record)
        return record

    def list_exports(self, project_id: str) -> list[ExportRecord]:
        self.get_project(project_id)
        return self.store.list_exports(project_id)

    @staticmethod
    def _latest_batch_seq(project: Project) -> int | None:
        merged = [batch.seq for batch in project.batches if batch.state == "merged"]
        return max(merged) if merged else None
