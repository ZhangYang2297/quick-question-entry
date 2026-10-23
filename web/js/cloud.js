// 云同步（可选模块）：默认未配置，应用以纯本地模式运行（本地 FastAPI + SQLite
// 即完整功能）。接入云端时提供同名接口即可：init / signIn / signOut /
// reconcile（文档快照对账）/ saveExport / downloadExport / purgeCloudFiles。
//
// 架构约定：本地后端始终是唯一工作副本，云只是持久化副本；
// 同步粒度 = 整份文档快照，按 updated_at 新者胜；云不可用时绝不阻塞本地流程。

import { h, toast, toastErr, popupMenu } from "./ui.js";

let syncing = false;
const listeners = new Set();

export function available() {
  return false;
}

export function signedIn() {
  return false;
}

export function userName() {
  return "";
}

export function onStatus(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function emit(status, extra = {}) {
  for (const fn of listeners) {
    try {
      fn({ status, ...extra });
    } catch {
      // 监听器异常不影响本地流程
    }
  }
}

/** 应用启动时调用一次：未配置云端时保持纯本地模式。 */
export async function init() {
  emit("signed-out");
  return null;
}

export async function signIn() {
  throw new Error("云端同步未配置，当前为纯本地模式");
}

export async function signOut() {
  emit("signed-out");
}

/**
 * 对账本地 ↔ 云端。未配置云端时无事可做。
 * 接入实现后约定：返回 { changed }，>0 有变更（调用方刷新列表），
 * -1 表示本次对账失败；文档粒度新者胜。
 */
export async function reconcile() {
  if (syncing) return { changed: 0 };
  syncing = true;
  emit("syncing");
  syncing = false;
  emit("signed-out");
  return { changed: 0 };
}

// ---- 导出文件存储（可选） ----------------------------------------------

/** 导出的 docx 传一份到云端；未配置时返回 false（本地下载不受影响）。 */
export async function saveExport(_projectId, _record, _blob) {
  return false;
}

/** 优先从云端取导出文件；未配置时返回 null，调用方回退本地文件。 */
export async function downloadExport(_projectId, _record) {
  return null;
}

/** 彻底删除文档后清理云端文件（尽力而为，失败不影响本地删除）。 */
export async function purgeCloudFiles(_projectId) {
  return;
}

// ---- 顶栏云状态按钮 ----------------------------------------------------

export function cloudButton() {
  const btn = h(
    "button",
    {
      class: "btn small ghost",
      onclick: () => toastErr(new Error("云端同步未配置，当前为纯本地模式")),
      disabled: true,
    },
    "☁️ 本地模式",
  );

  onStatus(() => {
    btn.textContent = "☁️ 本地模式";
    btn.disabled = true;
  });
  void toast;
  void popupMenu;
  return btn;
}
