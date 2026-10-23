// 首页 =「我的文档」。进入文档后默认续加，这里绝不弹任何询问框。

import { api } from "../api.js";
import * as cloud from "../cloud.js";
import { h, clear, toast, toastErr, confirmModal, promptModal, popupMenu, timeLabel } from "../ui.js";
import { topbar } from "../app.js";

export async function render(root, { trash = false }) {
  clear(root);
  const data = await (trash ? api.listTrash() : api.listProjects());
  const items = data.items;

  const actions = [
    cloud.cloudButton(),
    h("button", { class: "btn small ghost", onclick: () => location.hash = trash ? "#/" : "#/trash" },
      trash ? "返回文档" : "回收站"),
  ];

  root.append(
    topbar({
      back: false,
      name: trash ? "回收站" : "我的文档",
      sub: trash ? "彻底删除后不可恢复" : `共 ${items.length} 个文档`,
      actions,
    }),
  );

  if (!items.length) {
    root.append(
      h("div", { class: "empty" },
        h("div", { class: "big" }, trash ? "🗑" : "📄"),
        h("div", {}, trash ? "回收站是空的" : "还没有文档，上传第一张题目图片开始吧"),
        trash ? null : h("div", { style: { marginTop: "16px" } },
          h("button", { class: "btn primary", onclick: () => createAndEnter() }, "＋ 新建文档"),
        ),
      ),
    );
    return;
  }

  for (const project of items) root.append(projectCard(project, trash));
  if (!trash) {
    root.append(
      h("button", {
        class: "fab",
        onclick: () => createAndEnter(),
      }, "＋ 新建文档"),
    );
  }

  // 列表级对账（不阻塞渲染）：有变更才重画一次，避免循环
  cloud.reconcile().then((result) => {
    if (result && result.changed > 0) render(document.getElementById("app"), { trash });
  });
}

async function createAndEnter() {
  const name = await promptModal({ title: "新建文档", placeholder: "文档名（如：护理学基础题库）" });
  if (name === null) return;
  try {
    const project = await api.createProject(name);
    toast("已创建", "ok");
    location.hash = `#/p/${project.id}`;
  } catch (error) {
    toastErr(error);
  }
}

function projectCard(project, trash) {
  const info = trash
    ? `删除于 ${timeLabel(project.deleted_at)}`
    : `${project.question_count} 题 · ${project.batch_count} 批 · ${timeLabel(project.updated_at)}`;
  const card = h("div", { class: "card doc-card", onclick: () => location.hash = `#/p/${project.id}` },
    h("div", { class: "meta" },
      h("div", { class: "name" }, project.name),
      h("div", { class: "info" }, info),
    ),
  );
  if (trash) {
    card.append(
      h("button", { class: "btn small", style: { position: "absolute", right: "8px" }, onclick: (e) => { e.stopPropagation(); restore(project); } }, "恢复"),
    );
    // 彻底删除：恢复键左边独立入口，永远比"恢复"多一次确认
    card.append(
      h("button", {
        class: "btn small danger",
        style: { position: "absolute", right: "64px" },
        onclick: async (e) => {
          e.stopPropagation();
          const ok = await confirmModal({
            title: "彻底删除",
            message: `永久删除「${project.name}」及其 ${project.question_count} 题、全部批次与导出记录？此操作不可恢复，回收站也无法找回。`,
            confirmText: "永久删除",
            danger: true,
          });
          if (!ok) return;
          try {
            await api.purgeProject(project.id);
            cloud.purgeCloudFiles(project.id);
            toast("已彻底删除");
            render(document.getElementById("app"), { trash: true });
          } catch (error) {
            toastErr(error);
          }
        },
      }, "彻底删除"),
    );
    return card;
  }
  const more = h("button", {
    class: "icon-btn more",
    "aria-label": "更多操作",
    onclick: (e) => {
      e.stopPropagation();
      popupMenu(more, [
        { label: "✏️ 重命名", onClick: () => rename(project) },
        { label: "📄 创建副本", onClick: () => duplicate(project) },
        { label: "🗑 删除", danger: true, onClick: () => remove(project) },
      ]);
    },
  }, "⋯");
  card.append(more);
  return card;
}

async function rename(project) {
  const name = await promptModal({ title: "重命名文档", value: project.name });
  if (!name || name === project.name) return;
  try {
    await api.renameProject(project.id, name);
    toast("已重命名", "ok");
    render(document.getElementById("app"), { trash: false });
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
    render(document.getElementById("app"), { trash: false });
  } catch (error) {
    toastErr(error);
  }
}

async function restore(project) {
  try {
    await api.restoreProject(project.id);
    toast("已恢复", "ok");
    render(document.getElementById("app"), { trash: true });
  } catch (error) {
    toastErr(error);
  }
}
