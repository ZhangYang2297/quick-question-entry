// 导出面板：全量（默认）/ 仅本次新增；导出历史可重下。

import { api } from "../api.js";
import * as cloud from "../cloud.js";
import { h, clear, toast, toastErr, confirmModal, openSheet, timeLabel } from "../ui.js";

/** 下载一份导出记录：登录了云账号就先试云端（换设备也能下），失败回退本地后端。 */
export async function downloadExport(projectId, record) {
  try {
    const blob = await cloud.downloadExport(projectId, record);
    if (blob) {
      const url = URL.createObjectURL(blob);
      api.downloadFile(url, record.file_name);
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      return;
    }
  } catch {
    // 云端取不到就走本地
  }
  api.downloadFile(record.download_url, record.file_name);
}

export function openExportSheet(project, onChanged) {
  const historyNode = h("div");
  const batchSelect = h("select", { style: { width: "100%", minHeight: "44px" } });

  const sheet = openSheet({
    title: "导出 Word",
    body: h("div", {},
      h("div", { class: "field" },
        h("label", { style: { display: "flex", alignItems: "center", gap: "10px", fontSize: "15px", color: "var(--ink)" } },
          h("input", { type: "radio", name: "export-mode", value: "full", checked: true, style: { width: "18px", height: "18px" } }),
          h("span", {},
            h("b", {}, "全量导出"), h("div", { style: { fontSize: "12.5px", color: "var(--muted)" } },
              `导出整份文档的全部 ${project.question_count} 题（推荐）`)),
        ),
      ),
      h("div", { class: "field" },
        h("label", { style: { display: "flex", alignItems: "center", gap: "10px", fontSize: "15px", color: "var(--ink)" } },
          h("input", { type: "radio", name: "export-mode", value: "incremental", style: { width: "18px", height: "18px" } }),
          h("span", {},
            h("b", {}, "仅本次新增"),
            h("div", { style: { fontSize: "12.5px", color: "var(--muted)" } },
              "只导出某一批新加的题，题号从 1 重算 —— 是给你自己贴进已有文件用的，不是往旧文件里追加")),
        ),
      ),
      h("div", { class: "field", id: "batch-pick", style: { display: "none" } },
        h("label", {}, "选择批次"),
        batchSelect,
      ),
      h("div", { class: "modal-actions" },
        h("button", { class: "btn primary block", onclick: doExport }, "导出并下载"),
      ),
      h("div", { class: "group-title" }, "导出历史"),
      historyNode,
    ),
  });

  const merged = project.batches.filter((batch) => batch.state === "merged");
  for (const batch of merged) {
    batchSelect.append(h("option", { value: batch.seq }, `第 ${batch.seq} 批（${batch.question_count} 题）`));
  }
  const radios = sheet.node.querySelectorAll('input[name="export-mode"]');
  radios.forEach((radio) =>
    radio.addEventListener("change", () => {
      sheet.node.querySelector("#batch-pick").style.display =
        radio.value === "incremental" && radio.checked ? "block" : "none";
    }));

  drawHistory();

  async function drawHistory() {
    clear(historyNode);
    try {
      const result = await api.listExports(project.id);
      if (!result.items.length) {
        historyNode.append(h("div", { style: { fontSize: "13.5px", color: "var(--muted)", padding: "6px 0 2px" } }, "还没有导出记录"));
        return;
      }
      for (const record of [...result.items].reverse()) {
        historyNode.append(
          h("div", { style: { display: "flex", alignItems: "center", gap: "10px", padding: "9px 0", borderBottom: "1px solid var(--line-2)" } },
            h("div", { style: { flex: 1, minWidth: 0 } },
              h("div", { style: { fontSize: "14px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, record.file_name),
              h("div", { style: { fontSize: "12px", color: "var(--muted)" } },
                `${record.mode === "incremental" ? "仅新增" : "全量"} · ${record.question_count} 题 · ${timeLabel(record.created_at)}`),
            ),
            h("button", {
              class: "btn small",
              onclick: () => downloadExport(project.id, record),
            }, "下载"),
          ),
        );
      }
    } catch (error) {
      toastErr(error);
    }
  }

  async function doExport() {
    const mode = [...radios].find((radio) => radio.checked).value;
    if (mode === "incremental" && !batchSelect.options.length) {
      toast("还没有已并入的批次，无法仅导出新增", "err");
      return;
    }
    if (mode === "full" && !project.question_count) {
      const ok = await confirmModal({
        title: "文档是空的",
        message: "还没有题目，导出会得到一份空 Word。仍要继续吗？",
        confirmText: "继续导出",
      });
      if (!ok) return;
    }
    try {
      const record = await api.createExport(project.id, mode, mode === "incremental" ? Number(batchSelect.value) : null);
      api.downloadFile(record.download_url, record.file_name);
      toast("已导出，正在下载", "ok");
      // 导出文件同步一份到云端（失败不影响本地下载）；顺带触发文档对账
      api
        .blob(record.download_url)
        .then((blob) => cloud.saveExport(project.id, record, blob))
        .then(() => cloud.reconcile())
        .catch(() => {});
      drawHistory();
      if (onChanged) onChanged();
    } catch (error) {
      toastErr(error);
    }
  }

  return sheet;
}
