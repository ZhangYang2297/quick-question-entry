"""SQLite 持久化层。

**这一层只认识领域对象，不掺业务规则**：
- 不做排序决策、不做残题裁定、不做归属校验 —— 那些属于 project.service / api；
- 只负责「按 id 存取 + 按 order_index 还原列表顺序 + 事务」。

并发：一个连接被多线程共享（`check_same_thread=False`），所有读写都过同一把
可重入锁。真正的业务串行化（同项目两次续加不互相覆盖）在 `store.locks`。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from qqe.domain.models import (
    BatchRecord,
    ExportRecord,
    Project,
    Question,
    QuestionSet,
    now_iso,
)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class ProjectNotFound(LookupError):
    pass


class BatchNotFound(LookupError):
    pass


class QuestionNotFound(LookupError):
    pass


class UploadNotFound(LookupError):
    pass


class ExportNotFound(LookupError):
    pass


_UNSET = object()


def _dump_json(value: Any) -> str | None:
    """None 要写成 SQL NULL，而不是字符串 "null"（否则读回来永远不为空）。"""
    return None if value is None else json.dumps(value, ensure_ascii=False)


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """就地补列：老数据库（M4 建的表）不需要重建就能用上新字段。"""
        columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(projects)").fetchall()
        }
        if "style_json" not in columns:
            self._conn.execute("ALTER TABLE projects ADD COLUMN style_json TEXT")

    # ---- 基础设施 -------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    # ---- projects -------------------------------------------------------
    def create_project(self, project: Project) -> Project:
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO projects
                    (id, name, style_name, style_json, owner_id, title, groups_json,
                     created_at, updated_at, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project.id,
                    project.name,
                    project.style_name,
                    _dump_json(project.custom_style),
                    project.owner_id,
                    project.question_set.title,
                    json.dumps(project.question_set.groups, ensure_ascii=False),
                    project.created_at,
                    project.updated_at,
                    project.deleted_at,
                ),
            )
            self._write_questions(
                conn, project.id, project.question_set.questions, project.excluded
            )
            for batch in project.batches:
                self._insert_batch(conn, project.id, batch)
            for record in project.exports:
                self._insert_export(conn, project.id, record)
        return self.get_project(project.id)  # type: ignore[return-value]

    def get_project(self, project_id: str, *, include_deleted: bool = False) -> Project | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if row is None:
                return None
            if row["deleted_at"] and not include_deleted:
                return None
            return self._assemble(row)

    def list_projects(self, *, owner_id: str | None = None, trash: bool = False) -> list[Project]:
        sql = "SELECT * FROM projects WHERE deleted_at IS {} NULL".format("NOT" if trash else "")
        params: list[Any] = []
        if owner_id is not None:
            sql += " AND owner_id = ?"
            params.append(owner_id)
        sql += " ORDER BY updated_at DESC, id"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            return [self._assemble(row) for row in rows]

    def update_meta(
        self,
        project_id: str,
        *,
        name: Any = _UNSET,
        style_name: Any = _UNSET,
        custom_style: Any = _UNSET,
        title: Any = _UNSET,
        groups: Any = _UNSET,
        deleted_at: Any = _UNSET,
    ) -> None:
        fields: list[str] = []
        params: list[Any] = []
        mapping = {
            "name": name,
            "style_name": style_name,
            "deleted_at": deleted_at,
        }
        for column, value in mapping.items():
            if value is not _UNSET:
                fields.append(f"{column} = ?")
                params.append(value)
        if title is not _UNSET:
            fields.append("title = ?")
            params.append(title)
        if custom_style is not _UNSET:
            fields.append("style_json = ?")
            params.append(_dump_json(custom_style))
        if groups is not _UNSET:
            fields.append("groups_json = ?")
            params.append(json.dumps(groups, ensure_ascii=False))
        fields.append("updated_at = ?")
        params.append(now_iso())
        params.append(project_id)
        with self._tx() as conn:
            conn.execute(f"UPDATE projects SET {', '.join(fields)} WHERE id = ?", params)

    def delete_project(self, project_id: str) -> None:
        """彻底删除（连同题目 / 批次 / 导出 / 上传记录）。"""
        with self._tx() as conn:
            conn.execute(
                "DELETE FROM batch_questions WHERE batch_id IN "
                "(SELECT id FROM batches WHERE project_id = ?)",
                (project_id,),
            )
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    # ---- questions ------------------------------------------------------
    def save_questions(
        self,
        project_id: str,
        active: Sequence[Question],
        excluded: Sequence[Question] = (),
    ) -> None:
        """整体重写某个项目的题目（删除 / 调序 / 编辑后统一走这里）。"""
        with self._tx() as conn:
            self._write_questions(conn, project_id, active, excluded)
            conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now_iso(), project_id))

    def list_questions(self, project_id: str) -> list[Question]:
        """按 order_index 升序返回（order 就是顺序真相的物化结果）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM questions WHERE project_id = ? AND status = 'active' "
                "ORDER BY order_index ASC",
                (project_id,),
            ).fetchall()
        return [Question.model_validate_json(row["payload"]) for row in rows]

    def get_question(self, question_id: str) -> tuple[Question, str] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, project_id FROM questions WHERE id = ? AND status = 'active'",
                (question_id,),
            ).fetchone()
        if row is None:
            return None
        return Question.model_validate_json(row["payload"]), row["project_id"]

    # ---- batches --------------------------------------------------------
    def insert_batch(self, project_id: str, batch: BatchRecord) -> None:
        with self._tx() as conn:
            self._insert_batch(conn, project_id, batch)

    def get_batch(self, batch_id: str) -> tuple[BatchRecord, str] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, project_id, state FROM batches WHERE id = ?", (batch_id,)
            ).fetchone()
        if row is None:
            return None
        record = BatchRecord.model_validate_json(row["payload"])
        record.state = row["state"]
        return record, row["project_id"]

    def list_batches(self, project_id: str) -> list[BatchRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload, state FROM batches WHERE project_id = ? ORDER BY seq ASC",
                (project_id,),
            ).fetchall()
        records = []
        for row in rows:
            record = BatchRecord.model_validate_json(row["payload"])
            record.state = row["state"]
            records.append(record)
        return records

    def set_batch_state(self, batch_id: str, state: str) -> None:
        with self._tx() as conn:
            conn.execute("UPDATE batches SET state = ? WHERE id = ?", (state, batch_id))

    # ---- exports --------------------------------------------------------
    def insert_export(self, project_id: str, record: ExportRecord) -> None:
        with self._tx() as conn:
            self._insert_export(conn, project_id, record)

    def list_exports(self, project_id: str) -> list[ExportRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM exports WHERE project_id = ? ORDER BY rowid DESC",
                (project_id,),
            ).fetchall()
        return [ExportRecord.model_validate_json(row["payload"]) for row in rows]

    def get_export(self, export_id: str) -> tuple[ExportRecord, str] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, project_id FROM exports WHERE id = ?", (export_id,)
            ).fetchone()
        if row is None:
            return None
        return ExportRecord.model_validate_json(row["payload"]), row["project_id"]

    # ---- uploads --------------------------------------------------------
    def add_uploads(
        self,
        project_id: str,
        *,
        batch_id: str | None,
        items: Sequence[dict[str, Any]],
    ) -> None:
        with self._tx() as conn:
            for item in items:
                conn.execute(
                    """
                    INSERT INTO uploads
                        (id, project_id, batch_id, file_name, content_sha256, path,
                         upload_order, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["id"],
                        project_id,
                        batch_id,
                        item["file_name"],
                        item.get("content_sha256"),
                        item["path"],
                        item["upload_order"],
                        item.get("created_at") or now_iso(),
                    ),
                )

    def get_upload(self, upload_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()
        return dict(row) if row else None

    def assign_uploads_batch(self, upload_ids: Sequence[str], batch_id: str) -> None:
        with self._tx() as conn:
            for upload_id in upload_ids:
                conn.execute("UPDATE uploads SET batch_id = ? WHERE id = ?", (batch_id, upload_id))

    def list_uploads(self, project_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM uploads WHERE project_id = ? ORDER BY upload_order ASC",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---- 内部 -----------------------------------------------------------
    def _write_questions(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        active: Sequence[Question],
        excluded: Sequence[Question],
    ) -> None:
        conn.execute("DELETE FROM questions WHERE project_id = ?", (project_id,))
        for index, question in enumerate(active, start=1):
            # order 是派生列：落库时按列表位置重算，绝不信任调用方传进来的值
            snapshot = question.model_copy(update={"order": index})
            self._insert_question(conn, project_id, snapshot, status="active", index=index)
        for question in excluded:
            snapshot = question.model_copy(update={"order": 0})
            self._insert_question(conn, project_id, snapshot, status="excluded", index=0)

    def _insert_question(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        question: Question,
        *,
        status: str,
        index: int,
    ) -> None:
        conn.execute(
            """
            INSERT INTO questions
                (id, project_id, status, order_index, batch_seq, type, is_fragment, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question.id,
                project_id,
                status,
                index,
                question.batch_seq,
                str(question.type),
                1 if question.is_fragment else 0,
                question.model_dump_json(),
            ),
        )

    def _insert_batch(self, conn: sqlite3.Connection, project_id: str, batch: BatchRecord) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO batches (id, project_id, seq, state, created_at, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                batch.id,
                project_id,
                batch.seq,
                batch.state,
                batch.created_at,
                batch.model_dump_json(),
            ),
        )
        for position, question_id in enumerate(batch.question_ids):
            conn.execute(
                "INSERT OR REPLACE INTO batch_questions (batch_id, question_id, position) "
                "VALUES (?, ?, ?)",
                (batch.id, question_id, position),
            )

    def _insert_export(
        self, conn: sqlite3.Connection, project_id: str, record: ExportRecord
    ) -> None:
        conn.execute(
            """
            INSERT INTO exports (id, project_id, mode, created_at, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                record.id,
                project_id,
                record.mode,
                record.created_at,
                record.model_dump_json(),
            ),
        )

    def _assemble(self, row: sqlite3.Row) -> Project:
        project_id = row["id"]
        with self._lock:
            question_rows = self._conn.execute(
                "SELECT payload FROM questions WHERE project_id = ? AND status = 'active' "
                "ORDER BY order_index ASC",
                (project_id,),
            ).fetchall()
            excluded_rows = self._conn.execute(
                "SELECT payload FROM questions WHERE project_id = ? AND status = 'excluded' "
                "ORDER BY rowid ASC",
                (project_id,),
            ).fetchall()
        batches = self.list_batches(project_id)
        exports = self.list_exports(project_id)
        return Project(
            id=project_id,
            name=row["name"],
            style_name=row["style_name"],
            custom_style=json.loads(row["style_json"]) if row["style_json"] else None,
            owner_id=row["owner_id"],
            question_set=QuestionSet(
                title=row["title"],
                groups=json.loads(row["groups_json"] or "[]"),
                questions=[Question.model_validate_json(r["payload"]) for r in question_rows],
            ),
            batches=batches,
            excluded=[Question.model_validate_json(r["payload"]) for r in excluded_rows],
            exports=exports,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted_at=row["deleted_at"],
        )
