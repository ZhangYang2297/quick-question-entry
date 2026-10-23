-- 持久化 schema（SQLite 起步；语句保持通用，便于将来迁到云数据库）
--
-- 设计要点：
-- 1. questions 全量 JSON 存在 payload 里，同时把"要查询/排序"的字段抽成列
--    （order_index / status / batch_seq）。领域模型的演进不需要改表。
-- 2. order_index 是**派生列**：任何结构变更（删题/调序/续加）后由 renormalize() 重写。
-- 3. status = active | excluded：残题不删，留在项目里可恢复。
-- 4. 软删除靠 projects.deleted_at，默认列表过滤。

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    style_name  TEXT NOT NULL,
    style_json  TEXT,
    owner_id    TEXT NOT NULL,
    title       TEXT,
    groups_json TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    deleted_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id, deleted_at);

CREATE TABLE IF NOT EXISTS questions (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'active',
    order_index INTEGER NOT NULL DEFAULT 0,
    batch_seq   INTEGER NOT NULL DEFAULT 0,
    type        TEXT NOT NULL,
    is_fragment INTEGER NOT NULL DEFAULT 0,
    payload     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_questions_project
    ON questions(project_id, status, order_index);

CREATE TABLE IF NOT EXISTS batches (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    seq        INTEGER NOT NULL,
    state      TEXT NOT NULL DEFAULT 'merged',
    created_at TEXT NOT NULL,
    payload    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_batches_project ON batches(project_id, seq);

-- 批次 ↔ 题目关联（保留"这一批当时进了哪些题、什么顺序"的审计线索）
CREATE TABLE IF NOT EXISTS batch_questions (
    batch_id    TEXT NOT NULL,
    question_id TEXT NOT NULL,
    position    INTEGER NOT NULL,
    PRIMARY KEY (batch_id, question_id)
);

CREATE TABLE IF NOT EXISTS exports (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    mode       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_exports_project ON exports(project_id, created_at);

CREATE TABLE IF NOT EXISTS uploads (
    id             TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    batch_id       TEXT,
    file_name      TEXT NOT NULL,
    content_sha256 TEXT,
    path           TEXT NOT NULL,
    upload_order   INTEGER NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_uploads_project ON uploads(project_id, upload_order);

CREATE TABLE IF NOT EXISTS style_templates (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
