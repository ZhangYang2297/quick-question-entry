// 校对页：确认前的一切都发生在草稿上。确认并入后新题追加到文档末尾。
//
// 语法纪律：模板字符串不嵌套、跨行表达式一律拆成独立语句，
// 保证 ES 模块（严格模式）解析与浏览器行为完全一致。

import { api, TYPE_LABELS } from "../api.js";
import { h, clear, toast, toastErr, confirmModal, openSheet, viewer } from "../ui.js";
import { topbar } from "../app.js";

const QUESTION_FIELDS = ["type", "stem", "options", "tables", "group_title", "source_label"];

const UNTYPED = { options: [], tables: [], group_title: null, source_label: null };

export async function render(root, { batchId }) {
  let snapshot = await api.batchSnapshot(batchId);
  if (snapshot.state === "confirmed") {
    toast("本批已并入文档", "ok");
    location.hash = "#/p/" + snapshot.project_id;
    return;
  }
  if (snapshot.state === "discarded") {
    toast("本批已放弃");
    location.hash = "#/p/" + snapshot.project_id;
    return;
  }

  let project = null;
  try {
    project = await api.getProject(snapshot.project_id);
  } catch {
    project = null; // 项目名取不到不影响校对
  }
  const existingCount = project ? project.question_count : 0;

  const state = { showAll: false, projectQuestions: [] };

  const subNode = h("span");
  const parseBar = h("div");
  const listNode = h("div");
  const bar = h("div", { class: "action-bar", id: "review-bar" });

  function goDoc() {
    location.hash = "#/p/" + snapshot.project_id;
  }

  function questions() {
    return snapshot.questions || [];
  }

  // ---- 原图回看：按 source_file 对应上传图的显示名找 upload_order ----

  function imageUrlOf(question) {
    const images = snapshot.images || [];
    for (const img of images) {
      if (img.name === question.source_file) {
        return api.batchImage(batchId, img.upload_order, img.page_index || 0);
      }
    }
    return null;
  }

  // ---- 渲染 ---------------------------------------------------------------

  function drawSub() {
    const docName = project ? project.name : "";
    const part = "第 " + (snapshot.done || 0) + " / " + snapshot.total + " 张 · " + questions().length + " 题";
    const extra = existingCount ? " · 文档已有 " + existingCount + " 题" : "";
    clear(subNode);
    subNode.append(docName ? docName + " · " + part + extra : part + extra);
  }

  function drawParseBar() {
    clear(parseBar);
    if (snapshot.state !== "parsing") return;
    const done = snapshot.done || 0;
    const total = snapshot.total || 0;
    const pct = total ? Math.round((done / total) * 100) : 0;
    parseBar.append(
      h("div", { class: "card", style: { marginTop: "12px", padding: "14px" } },
        h("div", { style: { fontSize: "14px", color: "var(--muted)", marginBottom: "8px" } },
          "解析中… " + done + "/" + total),
        h("div", { class: "progress-row" },
          h("div", { class: "progress-track" },
            h("div", { class: "progress-fill", style: { width: pct + "%" } })),
        ),
      ),
    );
  }

  function drawFailed() {
    const failed = snapshot.failed || [];
    if (!failed.length || snapshot.state === "parsing") return;
    parseBar.append(
      h("div", { class: "card", style: { marginTop: "12px", padding: "12px 14px", borderColor: "#ffd591", background: "#fffdf5" } },
        h("div", { style: { fontSize: "14px", fontWeight: "600", marginBottom: "6px" } },
          "⚠️ " + failed.length + " 张图解析失败"),
        h("div", {},
          failed.map((fail) =>
            h("div", { style: { display: "flex", alignItems: "center", gap: "8px", padding: "6px 0" } },
              h("span", { style: { flex: 1, minWidth: 0, fontSize: "13px", color: "var(--muted)" } },
                "第 " + (fail.upload_order + 1) + " 张：" + (fail.error || "未知错误")),
              h("button", {
                class: "btn small",
                onclick: () => retryImage(fail.upload_order),
              }, "重试这张"),
            ))),
        failed.length > 1
          ? h("button", { class: "btn small", onclick: () => retryImage(null) }, "重试全部失败图片")
          : null,
      ),
    );
  }

  async function retryImage(uploadOrder) {
    try {
      await api.retryBatch(batchId, uploadOrder === null ? undefined : uploadOrder);
      toast("已重新提交解析");
      snapshot = await api.batchSnapshot(batchId);
      drawAll();
    } catch (error) {
      toastErr(error);
    }
  }

  function drawExcluded() {
    const excluded = snapshot.excluded || [];
    if (!excluded.length) return;
    const details = h("div", { style: { display: "none", marginTop: "8px" } });
    const arrow = h("span", { "aria-hidden": "true" }, "▸");
    const toggle = h("div", {
      class: "card", style: { marginTop: "12px", padding: "10px 14px", cursor: "pointer" },
      role: "button", tabindex: "0",
      onclick: toggleOpen,
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") toggleOpen(); },
    },
      h("span", { class: "badge warn" }, "已自动排除 " + excluded.length + " 道不完整题目"),
      h("span", { style: { fontSize: "13px", color: "var(--muted)", marginLeft: "8px" } }, "点击查看与恢复"),
      h("span", { style: { float: "right" } }, arrow),
    );
    function toggleOpen() {
      const open = details.style.display === "none";
      details.style.display = open ? "block" : "none";
      arrow.textContent = open ? "▾" : "▸";
    }
    for (const item of excluded) {
      details.append(
        h("div", { style: { display: "flex", alignItems: "center", gap: "8px", padding: "8px 0", borderBottom: "1px solid var(--line-2)" } },
          h("div", { style: { flex: 1, minWidth: 0 } },
            h("div", { style: { fontSize: "13.5px", overflowWrap: "anywhere" } },
              item.stem || "（空）"),
            h("div", { style: { fontSize: "12px", color: "var(--muted)" } },
              (TYPE_LABELS[item.type] || item.type) + " · " + (item.options || []).length + " 个选项"),
          ),
          h("button", {
            class: "btn small",
            onclick: (e) => { e.stopPropagation(); restoreExcluded(item); },
          }, "恢复"),
        ),
      );
    }
    parseBar.append(h("div", {}, toggle, details));
  }

  // 恢复到草稿：把残题补全（不足两个选项就补齐占位选项）后插回草稿末尾
  async function restoreExcluded(item) {
    const options = (item.options || []).length >= 2
      ? item.options
      : [...(item.options || []),
        { label: "A", text: "选项 A（请修改）" },
        { label: "B", text: "选项 B（请修改）" }];
    try {
      const added = await api.addDraft(batchId, {
        type: item.type,
        stem: item.stem,
        options: options,
        tables: item.tables || [],
        source_label: item.source_label,
      });
      const created = added.items[added.items.length - 1];
      await api.patchDraft(batchId, created.id, { is_fragment: false });
      toast("已恢复到草稿末尾，请补全内容", "ok");
      snapshot = await api.batchSnapshot(batchId);
      drawAll();
    } catch (error) {
      toastErr(error);
    }
  }

  function drawShowAllToggle() {
    if (!existingCount) return;
    listNode.append(
      h("div", { class: "card", style: { marginTop: "12px", padding: "10px 14px" } },
        h("label", { style: { display: "flex", alignItems: "center", gap: "8px", fontSize: "14px", color: "var(--ink-2)" } },
          h("input", {
            type: "checkbox",
            checked: state.showAll ? "" : null,
            style: { width: "18px", height: "18px" },
            onchange: (e) => { state.showAll = e.target.checked; drawProjectQuestions(); },
          }),
          "查看全部（含已确认的 " + existingCount + " 题）",
        ),
      ),
    );
  }

  function drawProjectQuestions() {
    const holder = listNode.querySelector("#doc-questions");
    if (holder) holder.remove();
    if (!state.showAll) return;
    const box = h("div", { id: "doc-questions" });
    const list = state.projectQuestions;
    if (!list.length) {
      box.append(h("div", { style: { fontSize: "13px", color: "var(--muted)", padding: "10px 4px" } }, "文档暂无已确认题目"));
    }
    list.forEach((question) => {
      box.append(
        h("div", { class: "card", style: { marginTop: "10px", padding: "12px 14px", opacity: "0.75" } },
          h("div", { style: { display: "flex", gap: "8px", alignItems: "baseline" } },
            h("span", { style: { fontWeight: "600" } }, String(question.order)),
            h("span", { style: { fontSize: "13px", color: "var(--muted)" } }, "已确认"),
          ),
          questionCardBody(question),
        ),
      );
    });
    listNode.append(box);
  }

  async function toggleProjectQuestions(show) {
    if (!show || state.projectQuestions.length) {
      drawProjectQuestions();
      return;
    }
    try {
      const detail = await api.getProject(snapshot.project_id);
      state.projectQuestions = detail.questions || [];
    } catch (error) {
      toastErr(error);
      state.showAll = false;
    }
    drawProjectQuestions();
  }

  function questionCardBody(question) {
    const parts = [h("div", { style: { fontSize: "14.5px", overflowWrap: "anywhere", whiteSpace: "pre-wrap" } },
      question.stem || "（空题干）")];
    for (const option of question.options || []) {
      parts.push(h("div", { style: { fontSize: "13.5px", color: "var(--ink-2)", marginTop: "2px" } },
        option.label + ". " + (option.text || "")));
    }
    return h("div", { style: { marginTop: "6px" } }, parts);
  }

  function drawList() {
    clear(listNode);
    drawShowAllToggle();

    const list = questions();
    if (!list.length && !(snapshot.excluded || []).length && snapshot.state === "needs_review") {
      listNode.append(h("div", { class: "empty" },
        h("div", { class: "big" }, "🫙"),
        h("div", {}, "这批没有识别出完整题目。可重试失败的图片，或放弃本批。"),
      ));
    }

    list.forEach((question, index) => {
      listNode.append(draftCard(question, index));
    });
  }

  function draftCard(question, index) {
    const warnings = question.warnings || [];
    return h("div", {
      class: "card q-card" + (warnings.length ? " has-warn" : ""),
      "data-qid": question.id,
      draggable: "true",
      ondragstart: (e) => {
        e.dataTransfer.setData("text/plain", question.id);
        e.currentTarget.classList.add("dragging");
      },
      ondragend: (e) => e.currentTarget.classList.remove("dragging"),
      ondragover: (e) => e.preventDefault(),
      ondrop: (e) => {
        e.preventDefault();
        const draggedId = e.dataTransfer.getData("text/plain");
        if (draggedId && draggedId !== question.id) moveTo(draggedId, question.id);
      },
    },
      h("div", { class: "head" },
        h("span", { class: "no" }, String(index + 1)),
        questionCardViewLite(question),
        h("div", { class: "move-col" },
          h("button", { class: "icon-btn", "aria-label": "上移", title: "上移", onclick: () => moveBy(index, -1) }, "↑"),
          h("button", { class: "icon-btn", "aria-label": "下移", title: "下移", onclick: () => moveBy(index, 1) }, "↓"),
          h("button", { class: "icon-btn", "aria-label": "编辑本题", title: "编辑", onclick: () => openEditor(question, index) }, "✏️"),
        ),
      ),
      h("div", { class: "foot" },
        h("span", { class: "badge" }, TYPE_LABELS[question.type] || question.type),
        warnings.map((warning) => h("span", { class: "badge warn" }, warning)),
        imageButton(question),
        h("button", {
          class: "btn small", style: { marginLeft: "auto" },
          onclick: () => openEditor(question, index),
        }, "编辑"),
      ),
    );
  }

  function questionCardViewLite(question) {
    const body = questionCardBody(question);
    const label = question.source_label ? "（原题号 " + question.source_label + "）" : "";
    return h("div", { style: { flex: 1, minWidth: 0 } }, body,
      label ? h("div", { style: { fontSize: "12px", color: "var(--muted)", marginTop: "4px" } }, label) : null);
  }

  function imageButton(question) {
    const url = imageUrlOf(question);
    if (!url) return null;
    return h("button", { class: "btn small", onclick: () => viewer(url) }, "🖼 原图");
  }

  async function moveBy(index, delta) {
    const ids = questions().map((question) => question.id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    const moved = ids[index];
    ids[index] = ids[target];
    ids[target] = moved;
    await applyReorder(ids);
  }

  function moveTo(draggedId, targetId) {
    const ids = questions().map((question) => question.id);
    const from = ids.indexOf(draggedId);
    const to = ids.indexOf(targetId);
    if (from < 0 || to < 0) return;
    ids.splice(from, 1);
    ids.splice(to, 0, draggedId);
    applyReorder(ids);
  }

  async function applyReorder(ids) {
    try {
      const result = await api.reorderDraft(batchId, ids);
      snapshot.questions = result.items;
      drawList();
    } catch (error) {
      toastErr(error);
    }
  }

  function drawBar() {
    clear(bar);
    if (snapshot.state === "parsing") {
      bar.append(h("span", { style: { color: "var(--muted)", fontSize: "14px" } }, "解析完成后可校对…"));
      return;
    }
    bar.append(
      h("button", { class: "btn small", onclick: addQuestion }, "＋ 补录一题"),
      h("button", { class: "btn danger", onclick: discardBatch }, "放弃本批"),
      h("button", { class: "btn primary", onclick: confirmBatch }, "确认并入（" + questions().length + " 题）"),
    );
  }

  async function discardBatch() {
    const ok = await confirmModal({
      title: "放弃本批次",
      message: "将丢弃本批所有草稿题，文档中已确认的题目不受影响。",
      confirmText: "放弃",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.discardBatch(batchId);
      toast("已放弃本批");
      goDoc();
    } catch (error) {
      toastErr(error);
    }
  }

  async function confirmBatch() {
    if (!questions().length) {
      toast("没有可并入的题目", "err");
      return;
    }
    try {
      await api.confirmBatch(batchId);
      toast("已并入文档，编号自动接续", "ok");
      goDoc();
    } catch (error) {
      toastErr(error);
    }
  }

  async function addQuestion() {
    try {
      const result = await api.addDraft(batchId, {
        type: "single_choice", stem: "", options: [], tables: [],
      });
      snapshot = await api.batchSnapshot(batchId);
      drawAll();
      const created = result.items[result.items.length - 1];
      const fresh = snapshot.questions.find((q) => q.id === created.id);
      if (fresh) openEditor(fresh, snapshot.questions.indexOf(fresh));
    } catch (error) {
      toastErr(error);
    }
  }

  // ---------- 全屏编辑层 ----------

  function openEditor(question, index) {
    const editor = buildEditor(question, index);
    document.getElementById("overlay-root").append(editor.node);
  }

  function buildEditor(question, index) {
    const draft = JSON.parse(JSON.stringify(question));
    if (!draft.options) draft.options = [];
    if (!draft.tables) draft.tables = [];

    const node = h("div", { class: "editor-full", role: "dialog", "aria-label": "编辑题目" });
    const form = h("div");
    const close = () => node.remove();

    function drawForm() {
      clear(form);
      form.append(
        h("div", { class: "field" },
          h("label", { for: "edit-type" }, "题型"),
          h("select", {
            id: "edit-type",
            onchange: (e) => { draft.type = e.target.value; },
          }, Object.keys(TYPE_LABELS).map((value) =>
            h("option", { value: value, selected: draft.type === value ? "" : null }, TYPE_LABELS[value]))),
        ),
        h("div", { class: "field" },
          h("label", { for: "edit-stem" }, "题干"),
          h("textarea", { id: "edit-stem" }, draft.stem || ""),
        ),
        h("div", { class: "group-title" }, "选项"),
        optionsBlock(),
        h("div", { style: { display: "flex", gap: "8px", marginBottom: "14px" } },
          h("button", { class: "btn small", onclick: () => { draft.options.push({ label: nextLabel(draft.options), text: "" }); drawForm(); } }, "＋ 加选项"),
        ),
        tablesBlock(),
      );
    }

    function optionsBlock() {
      const rows = [];
      draft.options.forEach((option, optIndex) => {
        const labelInput = h("input", {
          type: "text", value: option.label, style: { flex: "0 0 64px" },
          "aria-label": "选项 " + (optIndex + 1) + " 标号",
          oninput: (e) => { option.label = e.target.value; },
        });
        const textInput = h("input", {
          type: "text", value: option.text, style: { flex: 1 },
          "aria-label": "选项 " + (optIndex + 1) + " 内容",
          oninput: (e) => { option.text = e.target.value; },
        });
        rows.push(h("div", { class: "field" },
          h("div", { class: "row" },
            labelInput, textInput,
            h("button", {
              class: "icon-btn", "aria-label": "删除选项 " + (optIndex + 1), title: "删除选项",
              onclick: () => { draft.options.splice(optIndex, 1); drawForm(); },
            }, "🗑"),
          ),
        ));
      });
      if (!draft.options.length) {
        rows.push(h("div", { style: { fontSize: "13px", color: "var(--muted)", marginBottom: "10px" } },
          "暂无选项（判断题可留空）"));
      }
      return rows;
    }

    function tablesBlock() {
      const blocks = [];
      draft.tables.forEach((table, tableIndex) => {
        const caption = table.caption ? "表格 " + (tableIndex + 1) + "：" + table.caption : "表格 " + (tableIndex + 1);
        const rowsText = (table.rows || []).map((row) => row.join(" | ")).join("\n");
        const input = h("textarea", {
          style: { minHeight: "100px", width: "100%", fontFamily: "monospace", fontSize: "13px" },
          "aria-label": caption + " 内容",
        }, rowsText);
        table._rowsInput = input;
        blocks.push(
          h("div", { class: "card", style: { padding: "12px", marginTop: "8px" } },
            h("div", { style: { fontSize: "13px", color: "var(--muted)", marginBottom: "6px" } }, caption),
            input,
            h("div", { style: { marginTop: "8px", fontSize: "12.5px", color: "var(--muted)" } },
              "每行一条记录，单元格用 | 分隔。列数与表头不一致的行保存时会被忽略。"),
          ),
        );
      });
      return blocks;
    }

    function collectTables() {
      return draft.tables.map((table) => {
        if (table._rowsInput) {
          const headers = table.headers || [];
          table.rows = table._rowsInput.value
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean)
            .map((line) => line.split("|").map((cell) => cell.trim()))
            .filter((row) => row.length === headers.length);
        }
        const clean = {};
        for (const key of Object.keys(table)) {
          if (key !== "_rowsInput") clean[key] = table[key];
        }
        return clean;
      });
    }

    async function save() {
      draft.stem = form.querySelector("#edit-stem").value;
      const payload = { options: draft.options, tables: collectTables() };
      for (const field of QUESTION_FIELDS) {
        if (field === "options" || field === "tables") continue;
        payload[field] = draft[field];
      }
      try {
        await api.patchDraft(batchId, question.id, payload);
        snapshot = await api.batchSnapshot(batchId);
        close();
        drawAll();
        toast("已保存", "ok");
      } catch (error) {
        toastErr(error);
      }
    }

    async function removeQuestion() {
      const ok = await confirmModal({
        title: "删除本题",
        message: "从本批草稿中删除这道题。",
        confirmText: "删除",
        danger: true,
      });
      if (!ok) return;
      try {
        await api.deleteDraft(batchId, question.id);
        snapshot = await api.batchSnapshot(batchId);
        close();
        drawAll();
        toast("已删除", "ok");
      } catch (error) {
        toastErr(error);
      }
    }

    node.append(
      h("div", { class: "editor-bar" },
        h("button", { class: "back", "aria-label": "返回校对", onclick: close }, "‹"),
        h("div", { class: "title" }, "编辑第 " + (index + 1) + " 题"),
      ),
      h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: "12px" } },
        h("button", { class: "btn small", onclick: () => splitQuestion(question, index, close) }, "✂️ 拆分为两题"),
        index < questions().length - 1
          ? h("button", { class: "btn small", onclick: () => mergeWithNext(question, index, close) }, "🔗 与下一题合并")
          : null,
        h("button", { class: "btn small danger", onclick: removeQuestion }, "🗑 删除本题"),
      ),
      form,
      h("div", { class: "modal-actions", style: { position: "sticky", bottom: "calc(10px + var(--safe-bottom))", background: "var(--bg)", padding: "10px 0" } },
        h("button", { class: "btn", onclick: close }, "取消"),
        h("button", { class: "btn primary", onclick: save }, "保存"),
      ),
    );

    drawForm();
    return { node, close };
  }

  /** 拆分：题干里单独写一行 --- 作为分割线，前半留在原题，后半生成新题。 */
  async function splitQuestion(question, index, closeEditor) {
    const spec = await askSplit(question);
    if (!spec) return;
    try {
      await api.patchDraft(batchId, question.id, {
        type: question.type,
        stem: spec.head,
        options: question.options || [],
        tables: question.tables || [],
        group_title: question.group_title,
      });
      await api.addDraft(batchId, {
        type: question.type === "true_false" ? "true_false" : "single_choice",
        stem: spec.tail,
        options: [],
        tables: [],
        group_title: question.group_title,
      }, index + 1);
      snapshot = await api.batchSnapshot(batchId);
      closeEditor();
      drawAll();
      toast("已拆分，请在列表里补全新题内容", "ok");
    } catch (error) {
      toastErr(error);
    }
  }

  function askSplit(question) {
    return new Promise((resolve) => {
      const textarea = h("textarea", {
        style: { minHeight: "180px", width: "100%" },
        "aria-label": "拆分内容",
      }, (question.stem || "").replace(/\n---\n/g, "\n") + "\n---\n");
      const sheet = openSheet({
        title: "拆分为两题",
        onClose: () => resolve(null),
        body: h("div", {},
          h("p", { style: { fontSize: "13.5px", color: "var(--muted)", margin: "0 0 8px" } },
            "把光标移到要拆开的位置，用单独一行 --- 隔开：前半留在原题，后半成为新题（拆完记得补选项）。"),
          textarea,
          h("div", { class: "modal-actions" },
            h("button", { class: "btn", onclick: () => { sheet.close(); resolve(null); } }, "取消"),
            h("button", {
              class: "btn primary",
              onclick: () => {
                const parts = textarea.value.split("\n---\n");
                const head = parts[0].trim();
                const tail = parts.slice(1).join("\n").trim();
                if (!tail) {
                  toast("没有找到 --- 分隔线或后半段为空", "err");
                  return;
                }
                sheet.close();
                resolve({ head: head, tail: tail });
              },
            }, "拆分"),
          ),
        ),
      });
    });
  }

  async function mergeWithNext(question, index, closeEditor) {
    const next = questions()[index + 1];
    if (!next) return;
    const ok = await confirmModal({
      title: "与下一题合并",
      message: "把「" + truncate(next.stem, 20) + "」合并进本题（常用于跨页被截断的一道题）。",
      confirmText: "合并",
    });
    if (!ok) return;
    try {
      const mergedOptions = (question.options || []).slice();
      (next.options || []).forEach((option, offset) => {
        mergedOptions.push({ label: nextLabel(question.options || [], offset), text: option.text });
      });
      const mergedTables = (question.tables || []).concat(next.tables || []);
      await api.patchDraft(batchId, question.id, {
        type: question.type,
        stem: (question.stem || "") + "\n" + (next.stem || ""),
        options: mergedOptions,
        tables: mergedTables,
        group_title: question.group_title,
      });
      await api.deleteDraft(batchId, next.id);
      snapshot = await api.batchSnapshot(batchId);
      closeEditor();
      drawAll();
      toast("已合并", "ok");
    } catch (error) {
      toastErr(error);
    }
  }

  function nextLabel(options, offset) {
    const count = (options || []).length + (offset || 0);
    return String.fromCharCode(65 + count);
  }

  function truncate(text, length) {
    const clean = String(text || "").replace(/\s+/g, " ").trim();
    if (clean.length <= length) return clean;
    return clean.slice(0, length) + "…";
  }

  // ---- 装配与轮询 ---------------------------------------------------------

  function drawAll() {
    drawSub();
    clear(parseBar);
    drawParseBar();
    drawFailed();
    drawExcluded();
    drawList();
    drawBar();
  }

  clear(root);
  root.append(
    topbar({
      back: true,
      name: "校对本批",
      sub: "",
      actions: [subNode],
    }),
  );
  root.append(parseBar, listNode, bar);
  drawAll();

  if (snapshot.state === "parsing") {
    const timer = setInterval(async () => {
      try {
        const fresh = await api.batchSnapshot(batchId);
        if (fresh.state !== snapshot.state || fresh.done !== snapshot.done) {
          snapshot = fresh;
          drawAll();
        }
        if (fresh.state !== "parsing") {
          clearInterval(timer);
          if (fresh.state === "needs_review" && !snapshot.questions.length) {
            snapshot = fresh;
            drawAll();
          }
        }
      } catch {
        clearInterval(timer);
        toast("进度刷新失败，请手动刷新页面", "err");
      }
    }, 1200);
  }
}
