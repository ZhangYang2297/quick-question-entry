// 样式面板：预设切换 + 高级参数；预览是**服务端渲染的 HTML**，
// 和导出 .docx 读同一份 StyleSpec，看到的就是导出的。

import { api } from "../api.js";
import { h, clear, toast, toastErr, openSheet } from "../ui.js";

const GROUPS = [
  {
    title: "页面",
    path: "page",
    fields: [
      { key: "paper", label: "纸张", type: "select", options: [["A4", "A4"], ["B5", "B5"]] },
      { key: "margin_top_cm", label: "上边距 (cm)", type: "number", step: 0.1, min: 0, max: 6 },
      { key: "margin_bottom_cm", label: "下边距 (cm)", type: "number", step: 0.1, min: 0, max: 6 },
      { key: "margin_left_cm", label: "左边距 (cm)", type: "number", step: 0.1, min: 0, max: 6 },
      { key: "margin_right_cm", label: "右边距 (cm)", type: "number", step: 0.1, min: 0, max: 6 },
      { key: "footer_page_number", label: "页脚页码", type: "bool" },
    ],
  },
  {
    title: "字体",
    path: "font",
    fields: [
      { key: "cjk", label: "中文字体", type: "select", options: [
        ["宋体", "宋体"], ["黑体", "黑体"], ["楷体", "楷体"], ["仿宋", "仿宋"], ["微软雅黑", "微软雅黑"],
      ] },
      { key: "latin", label: "西文字体", type: "text" },
      { key: "size_pt", label: "字号 (pt)", type: "number", step: 0.5, min: 7, max: 22 },
      { key: "color", label: "颜色", type: "color" },
    ],
  },
  {
    title: "题干",
    path: "stem",
    fields: [
      { key: "size_pt", label: "字号 (pt)", type: "number", step: 0.5, min: 7, max: 22 },
      { key: "bold", label: "加粗", type: "bool" },
      { key: "line_spacing", label: "行距（倍）", type: "number", step: 0.1, min: 1, max: 3 },
      { key: "number_format", label: "题号格式", type: "select", options: [
        ["dot", "1."], ["cn_dot", "1、"], ["fullwidth_dot", "1．"], ["prefix", "第1题"],
      ] },
      { key: "align", label: "对齐", type: "select", options: [
        ["left", "左对齐"], ["center", "居中"], ["right", "右对齐"], ["justify", "两端对齐"],
      ] },
    ],
  },
  {
    title: "选项",
    path: "option",
    fields: [
      { key: "size_pt", label: "字号 (pt)", type: "number", step: 0.5, min: 7, max: 22 },
      { key: "line_spacing", label: "行距（倍）", type: "number", step: 0.1, min: 1, max: 3 },
      { key: "left_indent_chars", label: "左缩进（字符）", type: "number", step: 0.5, min: 0, max: 8 },
      { key: "options_per_line", label: "每行选项数", type: "number", step: 1, min: 1, max: 5 },
      { key: "marker", label: "选项标记", type: "select", options: [["dot", "A."], ["cn_dot", "A、"], ["paren", "(A)"]] },
    ],
  },
  {
    title: "表格",
    path: "table",
    fields: [
      { key: "header_bold", label: "表头加粗", type: "bool" },
      { key: "header_background", label: "表头底色", type: "color" },
      { key: "cell_size_pt", label: "单元格字号 (pt)", type: "number", step: 0.5, min: 6, max: 18 },
      { key: "border_width_pt", label: "边框粗细 (pt)", type: "number", step: 0.25, min: 0, max: 3 },
      { key: "border_color", label: "边框颜色", type: "color" },
      { key: "cell_align", label: "单元格对齐", type: "select", options: [["left", "左对齐"], ["center", "居中"], ["right", "右对齐"]] },
    ],
  },
];

export function openStyleSheet(project, onChanged, { batchId = null } = {}) {
  let spec = null;

  const presetChips = h("div", { class: "style-preset-chips" });
  const fieldsNode = h("div");
  const frame = h("iframe", { class: "style-preview-frame", title: "预览" });

  const panel = h("div", { class: "panel" }, presetChips, fieldsNode);
  const previewPane = h("div", { class: "preview-pane" }, frame);
  const layout = h("div", { class: "style-layout" }, panel, previewPane);

  const sheet = openSheet({
    title: "样式与实时预览",
    body: layout,
    onClose: () => { if (onChanged) onChanged(); },
  });

  async function boot() {
    try {
      const presets = await api.stylePresets();
      clear(presetChips);
      for (const item of presets.items) {
        const chip = h("button", {
          class: `chip ${item.name === project.style_name && !spec ? "active" : ""}`,
          onclick: async () => {
            try {
              if (project.id) await api.setPreset(project.id, item.name);
              spec = null;
              for (const other of presetChips.children) other.classList.remove("active");
              chip.classList.add("active");
              drawFields(item.spec);
              await refreshPreview();
              toast(`已应用预设：${item.name}`, "ok");
            } catch (error) {
              toastErr(error);
            }
          },
        }, item.name);
        presetChips.append(chip);
      }
      const current = project.id
        ? await api.getProjectStyle(project.id)
        : { style: spec || {} };
      spec = current.style;
      drawFields(spec);
      await refreshPreview();
    } catch (error) {
      toastErr(error);
    }
  }

  function drawFields(current) {
    clear(fieldsNode);
    for (const group of GROUPS) {
      fieldsNode.append(h("div", { class: "group-title" }, group.title));
      for (const field of group.fields) {
        fieldsNode.append(fieldControl(group, field, current));
      }
    }
    fieldsNode.append(
      h("div", { class: "modal-actions" },
        h("button", {
          class: "btn primary block",
          onclick: async () => {
            if (!project.id) {
              toast("校对草稿的样式试看不需要保存", "err");
              return;
            }
            try {
              await api.setStyleSpec(project.id, spec);
              toast("已保存为本项目的样式", "ok");
            } catch (error) {
              toastErr(error);
            }
          },
        }, "保存为本项目的样式"),
      ),
    );
  }

  function fieldControl(group, field, current) {
    const value = current[group.path][field.key];
    let control;
    if (field.type === "select") {
      control = h("select", {},
        field.options.map(([v, label]) => h("option", { value: v, selected: String(value) === v }, label)));
    } else if (field.type === "bool") {
      return h("div", { class: "field" },
        h("label", { style: { display: "flex", alignItems: "center", gap: "8px", color: "var(--ink-2)" } },
          h("input", {
            type: "checkbox", checked: !!value,
            style: { width: "18px", height: "18px" },
            onchange: (e) => update(group, field, e.target.checked),
          }),
          field.label,
        ),
      );
    } else if (field.type === "color") {
      control = h("input", { type: "color", value: value || "#000000" });
    } else if (field.type === "number") {
      control = h("input", { type: "number", value, step: field.step, min: field.min, max: field.max });
    } else {
      control = h("input", { type: "text", value: value ?? "" });
    }
    control.addEventListener("change", () => {
      let next = control.value;
      if (field.type === "number") next = Number(next);
      update(group, field, next);
    });
    return h("div", { class: "field" }, h("label", {}, field.label), control);
  }

  async function update(group, field, value) {
    spec[group.path][field.key] = value;
    spec.name = spec.name || "自定义";
    await refreshPreview();
  }

  async function refreshPreview() {
    try {
      const result = project.id
        ? await api.previewProject(project.id, spec)
        : await api.previewBatch(batchId, spec);
      frame.srcdoc = wrapPreview(result.html);
    } catch (error) {
      toastErr(error);
    }
  }

  boot();
  return sheet;
}

/** 预览 iframe 的外壳：消除 body 默认边距，宽度模拟纸张。 */
function wrapPreview(html) {
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { margin: 0; padding: 16px; background: #eef1f5; }
  .qqe-doc {
    max-width: 760px; margin: 0 auto; background: #fff; padding: var(--qqe-margin-top) var(--qqe-margin-right) var(--qqe-margin-bottom) var(--qqe-margin-left);
    box-shadow: 0 2px 12px rgba(0,0,0,.1); min-height: 60vh;
  }
</style></head><body><div class="qqe-doc">${html}</div></body></html>`;
}
