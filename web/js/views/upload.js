// 上传页：相册多选（不调摄像头）→ 缩略图调序 → 提交解析 → 按张进度 → 进校对页。

import { api } from "../api.js";
import { h, clear, toast, toastErr, confirmModal } from "../ui.js";
import { topbar } from "../app.js";

export async function render(root, { projectId }) {
  const project = await api.getProject(projectId);
  const meta = await api.meta();
  const maxBatch = meta.max_batch_size || 20;

  clear(root);
  root.append(
    topbar({
      name: "上传图片",
      sub: `正在续加到「${project.name}」· 单批最多 ${maxBatch} 张`,
    }),
  );

  let items = []; // {file, url, id}
  let submitting = false;

  const input = h("input", {
    type: "file",
    accept: "image/*,.pdf",
    multiple: true,
    style: { display: "none" },
    onchange: () => {
      addFiles([...input.files]);
      input.value = "";
    },
  });

  const grid = h("div", { class: "thumb-list" });
  const counter = h("div", { style: { fontSize: "13.5px", color: "var(--muted)", marginTop: "10px" } });
  const bar = h("div", { class: "action-bar" });

  const picker = h("button", { class: "btn primary", style: { flex: 1 }, onclick: () => input.click() },
    "📁 选择图片（相册多选）");

  function refreshBar() {
    clear(bar);
    if (!items.length) {
      bar.append(picker);
      return;
    }
    bar.append(
      h("button", { class: "btn", onclick: () => { items = []; drawGrid(); } }, "清空"),
      h("button", { class: "btn primary", onclick: submit, disabled: submitting }, submitting ? "解析中…" : `开始解析（${items.length} 张）`),
    );
  }

  function addFiles(files) {
    for (const file of files) {
      if (items.length >= maxBatch) {
        toast(`单批最多 ${maxBatch} 张，超出部分未加入。请分批上传，不影响续加。`, "err", 3200);
        break;
      }
      if (!/\.(jpe?g|png|webp|bmp|tiff?|pdf)$/i.test(file.name || "") && !file.type.startsWith("image/")) {
        toast(`不支持的文件：${file.name}`, "err");
        continue;
      }
      items.push({ file, url: URL.createObjectURL(file), id: Math.random().toString(36).slice(2) });
    }
    drawGrid();
  }

  function move(index, delta) {
    const target = index + delta;
    if (target < 0 || target >= items.length) return;
    [items[index], items[target]] = [items[target], items[index]];
    drawGrid();
  }

  function removeAt(index) {
    URL.revokeObjectURL(items[index].url);
    items.splice(index, 1);
    drawGrid();
  }

  let dragFrom = null;
  function drawGrid() {
    clear(grid);
    items.forEach((item, index) => {
      const thumb = h("div", {
        class: "thumb",
        draggable: "true",
        ondragstart: () => { dragFrom = index; thumb.classList.add("dragging"); },
        ondragover: (e) => { e.preventDefault(); thumb.classList.add("drop-target"); },
        ondragleave: () => thumb.classList.remove("drop-target"),
        ondrop: (e) => {
          e.preventDefault();
          thumb.classList.remove("drop-target");
          if (dragFrom === null || dragFrom === index) return;
          const [moved] = items.splice(dragFrom, 1);
          items.splice(index, 0, moved);
          dragFrom = null;
          drawGrid();
        },
        ondragend: () => thumb.classList.remove("dragging"),
      },
        h("img", { src: item.url, alt: item.file.name }),
        h("span", { class: "order-no" }, String(index + 1)),
        h("div", { class: "tools" },
          h("button", { class: "icon-btn", title: "上移", onclick: () => move(index, -1) }, "↑"),
          h("button", { class: "icon-btn", title: "下移", onclick: () => move(index, 1) }, "↓"),
          h("button", { class: "icon-btn del", title: "移除", onclick: () => removeAt(index) }, "✕"),
        ),
        h("div", { class: "fname" }, item.file.name || "图片"),
      );
      grid.append(thumb);
    });
    counter.textContent = items.length
      ? `已选 ${items.length} 张 · 顺序就是题目顺序（可拖动或用 ↑↓ 调整）`
      : "";
    refreshBar();
  }

  async function submit() {
    if (submitting || !items.length) return;
    submitting = true;
    refreshBar();
    try {
      const uploaded = await api.upload(projectId, items.map((item) => item.file));
      // 后端返回顺序 = 提交顺序 = 界面上调好的顺序，直接按它建批次。
      const uploadIds = uploaded.items.map((item) => item.upload_id);
      const batch = await api.createBatch(projectId, uploadIds);
      showProgress(batch.batch_id, uploadIds.length);
    } catch (error) {
      submitting = false;
      refreshBar();
      toastErr(error);
    }
  }

  function showProgress(batchId, total) {
    clear(root);
    root.append(
      topbar({ name: "解析中", sub: `第 1 / 共 ${total} 张` }),
      h("div", { style: { marginTop: "48px", textAlign: "center" } },
        h("div", { style: { fontSize: "40px" } }, "🔍"),
        h("div", { style: { marginTop: "12px", color: "var(--muted)" } }, "正在识别题目结构，请稍候…"),
        h("div", { class: "progress-row", style: { maxWidth: "420px", margin: "20px auto 0" } },
          h("div", { class: "progress-track" }, h("div", { class: "progress-fill", id: "fill" })),
          h("span", { id: "pct", style: { fontSize: "13px", color: "var(--muted)", minWidth: "42px", textAlign: "right" } }, "0%"),
        ),
        h("div", { id: "fail-box", style: { marginTop: "20px" } }),
      ),
      h("div", { class: "action-bar" },
        h("button", {
          class: "btn",
          onclick: async () => {
            const ok = await confirmModal({ title: "放弃本批？", message: "解析结果不会并入文档。", confirmText: "放弃", danger: true });
            if (!ok) return;
            try { await api.discardBatch(batchId); } catch { /* 已结束也无所谓 */ }
            location.hash = `#/p/${projectId}`;
          },
        }, "取消"),
      ),
    );
    poll(batchId, total);
  }

  let polling = true;
  async function poll(batchId, total) {
    for (;;) {
      if (!polling) return;
      let snapshot;
      try {
        snapshot = await api.batchSnapshot(batchId);
      } catch (error) {
        toastErr(error);
        return;
      }
      const pct = Math.round((snapshot.done / Math.max(1, snapshot.total)) * 100);
      const fill = root.querySelector("#fill");
      const pctLabel = root.querySelector("#pct");
      const sub = root.querySelector(".topbar .sub");
      if (fill) fill.style.width = `${pct}%`;
      if (pctLabel) pctLabel.textContent = `${pct}%`;
      if (sub) sub.textContent = `第 ${snapshot.done} / 共 ${snapshot.total} 张`;

      if (snapshot.state === "parsing") {
        await sleep(800);
        continue;
      }
      if (snapshot.state === "failed") {
        toast(snapshot.error || "解析失败", "err", 3000);
        location.hash = `#/b/${batchId}`;
        return;
      }
      if (snapshot.state === "needs_review" || snapshot.state === "confirmed") {
        location.hash = `#/b/${batchId}`;
        return;
      }
      if (snapshot.state === "discarded") return;
      await sleep(800);
    }
  }

  root.append(input, counter, grid, bar);
  drawGrid();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
