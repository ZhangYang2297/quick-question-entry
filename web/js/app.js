// 哈希路由 + 页面装配。页面模块只管渲染自己的内容区。

import { h, clear, toastErr } from "./ui.js";
import { api } from "./api.js";
import * as cloud from "./cloud.js";
import * as list from "./views/list.js";
import * as doc from "./views/doc.js";
import * as upload from "./views/upload.js";
import * as review from "./views/review.js";

const app = document.getElementById("app");

function parseHash() {
  const hash = location.hash.replace(/^#/, "") || "/";
  const [path, query] = hash.split("?");
  const parts = path.split("/").filter(Boolean);
  // 注意：first/second 必须取 parts[0]/parts[1]。此前写成 [, first, second]
  // 会把文档 id 当成路由段，导致 /p、/b、/trash 全部路由被兜底弹回首页。
  const first = parts[0];
  const second = parts[1];
  return { parts, first, second, query: new URLSearchParams(query || "") };
}

export function go(hash) {
  location.hash = hash;
}

/** 页面顶栏（返回键 + 常驻标题 + 右侧操作）。 */
export function topbar({ back = true, name = "", sub = "", actions = [] }) {
  return h("div", { class: "topbar" },
    back ? h("button", { class: "back", "aria-label": "返回", onclick: () => history.back() }, "‹") : h("span"),
    h("div", { class: "titles" },
      h("div", { class: "name" }, name),
      sub ? h("div", { class: "sub" }, sub) : null,
    ),
    h("div", { class: "actions" }, actions),
  );
}

async function dispatch() {
  const { parts, first, second } = parseHash();
  try {
    if (!first) {
      await list.render(app, { trash: false });
    } else if (first === "trash") {
      await list.render(app, { trash: true });
    } else if (first === "p" && second && parts[2] === "upload") {
      await upload.render(app, { projectId: second });
    } else if (first === "p" && second) {
      await doc.render(app, { projectId: second });
    } else if (first === "b" && second) {
      await review.render(app, { batchId: second });
    } else {
      go("#/");
    }
  } catch (error) {
    clear(app);
    app.append(
      topbar({ back: false, name: "出错了" }),
      h("div", { class: "empty" },
        h("div", { class: "big" }, "⚠️"),
        h("div", {}, error.message || "页面加载失败"),
        h("div", { style: { marginTop: "16px" } },
          h("button", { class: "btn primary", onclick: () => go("#/") }, "回到文档列表"),
        ),
      ),
    );
  }
}

window.addEventListener("hashchange", dispatch);

(async function boot() {
  try {
    await api.health();
  } catch (error) {
    clear(app);
    app.append(h("div", { class: "empty" },
      h("div", { class: "big" }, "📴"),
      h("div", {}, "连不上服务，请确认后端已启动后刷新"),
    ));
    return;
  }
  // 云初始化放在路由分发**之前**：登录回调必须先于任何页面渲染被处理
  try {
    await cloud.init();
  } catch (error) {
    toastErr(error);
  }
  dispatch();
})();
