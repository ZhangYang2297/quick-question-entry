// 界面基础件：DOM 构建、toast、确认弹窗、菜单、底部抽屉、大图查看。

export function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, value);
  }
  append(node, children);
  return node;
}

function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

export function toast(message, kind = "", ms = 2200) {
  const root = document.getElementById("toast-root");
  const node = h("div", { class: `toast ${kind}` }, message);
  root.append(node);
  setTimeout(() => node.remove(), ms);
}

export const toastErr = (error) => toast(error && error.message ? error.message : String(error), "err", 3000);

export function confirmModal({ title, message, confirmText = "确定", danger = false }) {
  return new Promise((resolve) => {
    const close = (result) => {
      mask.remove();
      resolve(result);
    };
    const mask = h("div", { class: "modal-mask", onclick: (e) => { if (e.target === mask) close(false); } },
      h("div", { class: "modal", role: "dialog" },
        h("h3", {}, title),
        h("div", { style: { color: "var(--ink-2)", fontSize: "15px" } }, message),
        h("div", { class: "modal-actions" },
          h("button", { class: "btn", onclick: () => close(false) }, "取消"),
          h("button", { class: `btn ${danger ? "danger solid" : "primary"}`, onclick: () => close(true) }, confirmText),
        ),
      ),
    );
    document.getElementById("overlay-root").append(mask);
  });
}

export function promptModal({ title, placeholder = "", value = "", confirmText = "保存" }) {
  return new Promise((resolve) => {
    let input;
    const close = (result) => { mask.remove(); resolve(result ? input.value.trim() : null); };
    const mask = h("div", { class: "modal-mask", onclick: (e) => { if (e.target === mask) close(false); } },
      h("div", { class: "modal", role: "dialog" },
        h("h3", {}, title),
        (input = h("input", { type: "text", value, placeholder, maxlength: 60 })),
        h("div", { class: "modal-actions" },
          h("button", { class: "btn", onclick: () => close(false) }, "取消"),
          h("button", { class: "btn primary", onclick: () => close(true) }, confirmText),
        ),
      ),
    );
    document.getElementById("overlay-root").append(mask);
    input.focus();
    input.select();
  });
}

/** 弹出菜单（长按 / ⋯ 按钮）。items: [{label, danger, onClick}] */
export function popupMenu(anchor, items) {
  const rect = anchor.getBoundingClientRect();
  const menu = h("div", { class: "menu" },
    items.map((item) =>
      h("button", {
        class: item.danger ? "danger" : "",
        onclick: () => { menu.remove(); mask.remove(); item.onClick(); },
      }, item.label),
    ),
  );
  const mask = h("div", {
    class: "sheet-mask",
    style: { background: "transparent" },
    onclick: () => { menu.remove(); mask.remove(); },
  });
  document.getElementById("overlay-root").append(mask, menu);
  const top = Math.min(rect.bottom + 6, window.innerHeight - menu.offsetHeight - 12);
  const left = Math.min(Math.max(12, rect.right - menu.offsetWidth), window.innerWidth - menu.offsetWidth - 12);
  Object.assign(menu.style, { top: `${Math.max(12, top)}px`, left: `${left}px` });
}

/** 底部抽屉（桌面端自动居中为弹窗）。返回 {close}。 */
export function openSheet({ title, body, onClose }) {
  const root = document.getElementById("overlay-root");
  const sheet = h("div", { class: "sheet" },
    h("div", { class: "grabber" }),
    h("div", { class: "sheet-head" },
      h("h3", {}, title),
      h("button", { class: "icon-btn", onclick: () => close() }, "✕"),
    ),
    body,
  );
  const mask = h("div", { class: "sheet-mask", onclick: (e) => { if (e.target === mask) close(); } });
  const close = () => {
    sheet.remove();
    mask.remove();
    if (onClose) onClose();
  };
  root.append(mask, sheet);
  return { close, node: sheet };
}

export function viewer(imageUrl) {
  const node = h("div", { class: "image-viewer", onclick: () => node.remove() }, h("img", { src: imageUrl, alt: "原图" }));
  document.getElementById("overlay-root").append(node);
}

export function timeLabel(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  const hm = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  if (sameDay) return `今天 ${hm}`;
  return `${date.getMonth() + 1}月${date.getDate()}日 ${hm}`;
}

export function questionCardView(question, { sourceLabel = true } = {}) {
  const opts = (question.options || []).map((option) =>
    h("div", { class: "opt" }, `${option.label}．${option.text}`),
  );
  const tables = (question.tables || []).map((table) => {
    const head = table.headers || [];
    return h("div", { class: "q-table-wrap" },
      h("table", { class: "q-table" },
        head.length ? h("thead", {}, h("tr", {}, head.map((cell) => h("th", {}, cell)))) : null,
        h("tbody", {},
          (table.rows || []).map((row) => h("tr", {}, row.map((cell) => h("td", {}, cell)))),
        ),
      ),
    );
  });
  return h("div", { class: "body" },
    h("div", { class: "stem" }, question.stem || "（空题干）"),
    opts.length ? h("div", { class: "opts" }, opts) : null,
    tables,
    sourceLabel && question.source_label
      ? h("div", { class: "src", style: { marginTop: "6px" } }, `来自原图第 ${question.source_label} 题`)
      : null,
  );
}
