// 文档页：常驻文档名 + 题目列表 + 批次记录；上传即续加，没有多余的询问。

import { api, TYPE_LABELS } from "../api.js";
import {
  h, clear, toast, toastErr, confirmModal, promptModal, popupMenu, timeLabel, questionCardView,
} from "../ui.js";
import { topbar } from "../app.js";
import { openStyleSheet } from "./styles.js";
import { openExportSheet } from "./exports.js";

export async function render(root, { projectId }) {
  const project = await api.getProject(projectId);
  clear(root);

  const actions = [
    h("button", { class: "btn small", onclick: () => openExportSheet(project, refresh) }, "导出"),
    h("button", { class: "btn small primary", onclick: () => location.hash = `#/p/${projectId}/upload` }, "＋ 录题"),
  ];

  root.append(
    topbar({
      name: project.name,
      sub: `${project.question_count} 题 · 样式：${project.style_name}${project.custom_style ? "（自定义）" : ""}`,
      actions,
    }),
  );

  // 文档操作入口（重命名 / 复制 / 删除）
  root.append(
    h("div", { style: { display: "flex", gap: "8px", marginTop: "12px" } },
      h("button", { class: "btn small", onclick: () => rename(project, refresh) }, "✏️ 重命名"),
      h("button", { class: "btn small", onclick: () => duplicate(project) }, "📄 创建副本"),
      h("button", { class: "btn small danger", onclick: () => remove(project) }, "🗑 删除"),
      h("button", { class: "btn small", onclick: () => openStyleSheet(project, refresh) }, "🎨 样式与预览"),
    ),
  );

  // 解析中的批次（草稿续校）
  const draftBatches = project.batches.filter((batch) => batch.state === "needs_review");
  if (draftBatches.length) {
    root.append(h("div", { class: "section-title" }, h("span", {}, "待校对的批次")));
    for (const batch of draftBatches) {
      root.append(
        h("div", {
          class: "card doc-card",
          onclick: () => location.hash = `#/b/${batch.id}`,
        },
          h("div", { class: "meta" },
            h("div", { class: "name" }, `第 ${batch.seq} 批草稿`),
            h("div", { class: "info" }, `${batch.question_count} 题待确认 · ${batch.image_count} 张图`),
          ),
          h("span", { class: "badge warn" }, "待校对"),
        ),
      );
    }
  }

  // 题目列表（只显示 order 作为题号）
  root.append(h("div", { class: "section-title" },
    h("span", {}, "全部题目"),
    h("span", { class: "n" }, `${project.questions.length} 题`),
  ));
  if (!project.questions.length) {
    root.append(
      h("div", { class: "empty" },
        h("div", { class: "big" }, "📷"),
        h("div", {}, "还没有题目。点右上角「＋ 录题」上传第一批图片。"),
      ),
    );
  } else {
    for (const question of project.questions) root.append(questionCard(question));
  }

  // 批次历史
  const merged = project.batches.filter((batch) => batch.state !== "needs_review");
  if (merged.length) {
    root.append(h("div", { class: "section-title" }, h("span", {}, "批次记录")));
    for (const batch of [...merged].reverse()) {
      root.append(
        h("div", { class: "card", style: { marginTop: "8px", padding: "10px 14px", display: "flex", alignItems: "center", gap: "10px" } },
          h("span", { class: "badge brand" }, `第 ${batch.seq} 批`),
          h("span", { style: { flex: 1, fontSize: "13.5px", color: "var(--muted)" } },
            `${batch.question_count} 题 · ${batch.image_count} 张图 · ${timeLabel(batch.created_at)}`),
          h("span", { class: `badge ${batch.state === "discarded" ? "danger" : ""}` },
            batch.state === "discarded" ? "已放弃" : "已并入"),
        ),
      );
    }
  }

  // 底部常驻录题条（移动端主操作）
  root.append(
    h("div", { class: "action-bar" },
      h("button", { class: "btn primary", onclick: () => location.hash = `#/p/${projectId}/upload` }, "📷 上传图片继续录入"),
    ),
  );

  async function refresh() {
    await render(root, { projectId });
  }
}

function questionCard(question) {
  const card = h("div", {
    class: `card q-card ${question.warnings && question.warnings.length ? "has-warn" : ""}`,
  },
    h("div", { class: "head" },
      h("span", { class: "no" }, String(question.order)),
      questionCardView(question),
    ),
    h("div", { class: "foot" },
      h("span", { class: "badge" }, TYPE_LABELS[question.type] || question.type),
      (question.warnings || []).map((warning) => h("span", { class: "badge warn" }, warning)),
    ),
  );
  return card;
}

async function rename(project, refresh) {
  const name = await promptModal({ title: "重命名文档", value: project.name });
  if (!name || name === project.name) return;
  try {
    await api.renameProject(project.id, name);
    toast("已重命名", "ok");
    await refresh();
  } catch (error) {
    toastErr(error);
  }
}

async function duplicate(project) {
  const ok = await confirmModal({
    title: "创建副本",
    message: `将复制「${project.name}」（含 ${project.question_count} 题）。副本与原文档互不影响。`,
    confirmText: "复制",
  });
  if (!ok) return;
  try {
    const copy = await api.duplicateProject(project.id);
    toast("已创建副本", "ok");
    location.hash = `#/p/${copy.id}`;
  } catch (error) {
    toastErr(error);
  }
}

async function remove(project) {
  const ok = await confirmModal({
    title: "删除文档",
    message: `删除含 ${project.question_count} 题的「${project.name}」？删除后可在回收站恢复。`,
    confirmText: "删除",
    danger: true,
  });
  if (!ok) return;
  try {
    await api.deleteProject(project.id);
    toast("已移入回收站");
    location.hash = "#/";
  } catch (error) {
    toastErr(error);
  }
}
