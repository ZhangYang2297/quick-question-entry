// API 封装：统一错误处理与用户标识。
// 单用户阶段用 X-User-Id: local；接入登录后只改这里，视图层不动。

const USER_ID = localStorage.getItem("qqe_user") || "local";

async function request(method, path, body, options = {}) {
  const init = {
    method,
    headers: { "X-User-Id": USER_ID },
  };
  if (body !== undefined && !(body instanceof FormData)) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  } else if (body instanceof FormData) {
    init.body = body;
  }
  const response = await fetch(path, init);
  if (response.status === 204) return null;
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload && (payload.detail || payload.error) ? payload.detail : `请求失败（${response.status}）`;
    const error = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    error.status = response.status;
    throw error;
  }
  return payload;
}

function get(path) { return request("GET", path); }
function post(path, body) { return request("POST", path, body); }
function put(path, body) { return request("PUT", path, body); }
function patch(path, body) { return request("PATCH", path, body); }
function del(path) { return request("DELETE", path); }

function uploadFiles(projectId, files) {
  const form = new FormData();
  for (const file of files) form.append("files", file, file.name || "image");
  return request("POST", `/api/projects/${projectId}/uploads`, form);
}

function downloadFile(url, fileName) {
  // 单用户阶段接口不强制鉴权头，直接用隐式下载；
  // 接入登录后改为 fetch + blob。
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName || "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export const api = {
  get, post, put, patch, del, uploadFiles, downloadFile,
  meta: () => get("/api/meta"),
  health: () => get("/api/health"),

  listProjects: () => get("/api/projects"),
  listTrash: () => get("/api/projects?trash=true"),
  createProject: (name) => post("/api/projects", name ? { name } : {}),
  getProject: (id) => get(`/api/projects/${id}`),
  renameProject: (id, name) => patch(`/api/projects/${id}`, { name }),
  setPreset: (id, styleName) => put(`/api/projects/${id}/style`, { style_name: styleName }),
  setStyleSpec: (id, spec) => put(`/api/projects/${id}/style`, { spec }),
  getProjectStyle: (id) => get(`/api/projects/${id}/style`),
  duplicateProject: (id) => post(`/api/projects/${id}/duplicate`, {}),
  deleteProject: (id) => del(`/api/projects/${id}`),
  restoreProject: (id) => post(`/api/projects/${id}/restore`),
  purgeProject: (id) => del(`/api/projects/${id}/purge`),

  stylePresets: () => get("/api/styles"),
  previewProject: (id, spec) => post(`/api/projects/${id}/preview`, spec ? { spec } : {}),
  previewBatch: (batchId, spec) => post(`/api/batches/${batchId}/preview`, spec ? { spec } : {}),

  upload: uploadFiles,
  createBatch: (projectId, uploadIds) => post(`/api/projects/${projectId}/batches`, { upload_ids: uploadIds }),
  batchSnapshot: (id) => get(`/api/batches/${id}`),
  draftQuestions: (id) => get(`/api/batches/${id}/questions`),
  patchDraft: (batchId, qid, fields) => patch(`/api/batches/${batchId}/questions/${qid}`, fields),
  deleteDraft: (batchId, qid) => del(`/api/batches/${batchId}/questions/${qid}`),
  addDraft: (batchId, question, position) => {
    const query = position === undefined || position === null ? "" : `?position=${position}`;
    return post(`/api/batches/${batchId}/questions${query}`, question);
  },
  reorderDraft: (batchId, ids) => post(`/api/batches/${batchId}/reorder`, { question_ids: ids }),
  retryBatch: (batchId, uploadOrder) =>
    post(`/api/batches/${batchId}/retry`, uploadOrder === undefined ? {} : { upload_order: uploadOrder }),
  confirmBatch: (batchId) => post(`/api/batches/${batchId}/confirm`),
  discardBatch: (batchId) => post(`/api/batches/${batchId}/discard`),
  batchImage: (batchId, uploadOrder, page = 0) =>
    `/api/batches/${batchId}/images/${uploadOrder}?page=${page}`,

  restoreExcluded: (projectId, qid) => post(`/api/projects/${projectId}/excluded/${qid}/restore`),
  patchQuestion: (qid, fields) => patch(`/api/questions/${qid}`, fields),
  deleteQuestion: (qid) => del(`/api/questions/${qid}`),
  reorderQuestions: (projectId, ids) => post(`/api/projects/${projectId}/questions/reorder`, { question_ids: ids }),

  createExport: (projectId, mode, batchSeq) =>
    post(`/api/projects/${projectId}/exports`, { mode, ...(batchSeq ? { batch_seq: batchSeq } : {}) }),
  listExports: (projectId) => get(`/api/projects/${projectId}/exports`),

  // 云同步支撑：整份项目快照的导出与导入（同 id 覆盖）
  snapshot: (id) => get(`/api/projects/${id}/snapshot`),
  importSnapshot: (snap) => post("/api/projects/import", snap),
  blob: async (path) => {
    const response = await fetch(path, { headers: { "X-User-Id": USER_ID } });
    if (!response.ok) throw new Error(`下载失败（${response.status}）`);
    return response.blob();
  },
};

export const TYPE_LABELS = {
  single_choice: "单选题",
  multi_choice: "多选题",
  true_false: "判断题",
  fill_blank: "填空题",
  short_answer: "简答题",
  term_define: "名词解释",
  case_analysis: "案例分析",
};
