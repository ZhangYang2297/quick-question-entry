"""FastAPI 应用装配。

**依赖注入点**：`create_app(model=..., db_path=...)`。
测试传 `FakeVisionModel` 与临时数据库，生产从 `.env` 读配置 —— 应用代码不分叉。
"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from qqe.api.jobs import JobConflict, JobManager, JobNotFound
from qqe.api.routes import batches, exports, projects, questions, styles
from qqe.domain.schema import page_parse_json_schema
from qqe.domain.style import list_presets
from qqe.parser.batch import MAX_BATCH_SIZE
from qqe.project.service import InvalidOrderError, ProjectService
from qqe.providers.base import VisionModel
from qqe.store import (
    BatchNotFound,
    ExportNotFound,
    ProjectNotFound,
    QuestionNotFound,
    Store,
    UploadNotFound,
)

API_VERSION = "0.3.0"

# 前端是**无构建步骤**的原生 SPA：改完刷新即可，不用 node/npm。
# 同源托管的好处是生产环境不需要 CORS，也不会出现"接口在 8000、页面在 5173"的错配。
DEFAULT_WEB_DIR = Path(__file__).resolve().parents[3] / "web"

_ERROR_STATUS: dict[type[BaseException], int] = {
    ProjectNotFound: 404,
    QuestionNotFound: 404,
    BatchNotFound: 404,
    UploadNotFound: 404,
    ExportNotFound: 404,
    JobNotFound: 404,
    JobConflict: 409,
    InvalidOrderError: 400,
    ValueError: 400,
}


def _make_handler(status_code: int):
    def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={"detail": str(exc) or exc.__class__.__name__, "error": exc.__class__.__name__},
        )

    return handler


@asynccontextmanager
async def _lifespan(app: FastAPI):
    yield
    app.state.jobs.shutdown()
    if app.state.created_store:
        app.state.store.close()


def create_app(
    *,
    store: Store | None = None,
    service: ProjectService | None = None,
    model: VisionModel | None = None,
    jobs: JobManager | None = None,
    db_path: str | Path | None = None,
    uploads_dir: str | Path | None = None,
    out_dir: str | Path | None = None,
    web_dir: str | Path | None = None,
) -> FastAPI:
    app = FastAPI(title="快速录题", version=API_VERSION, docs_url="/api/docs", lifespan=_lifespan)

    created_store = store is None
    if store is None:
        store = Store(db_path or Path("data") / "qqe.db")
    if service is None:
        service = ProjectService(store, out_dir=out_dir or Path("out"))

    if jobs is None:
        if model is None:
            from qqe.config import Settings
            from qqe.providers import build_model

            model = build_model(Settings.load())
        jobs = JobManager(model, schema=page_parse_json_schema())

    app.state.store = store
    app.state.service = service
    app.state.jobs = jobs
    app.state.uploads_dir = Path(uploads_dir or Path("data") / "uploads")
    app.state.created_store = created_store

    # 前端开发期跨域（生产同源部署时可关掉）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (
        projects.router,
        batches.router,
        questions.router,
        exports.router,
        styles.router,
    ):
        app.include_router(router, prefix="/api")

    for exception_type, status_code in _ERROR_STATUS.items():
        app.add_exception_handler(exception_type, _make_handler(status_code))

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": API_VERSION}

    @app.get("/api/meta")
    def meta():
        """前端启动时读一次：可用样式与单批上限。"""
        return {"styles": list_presets(), "max_batch_size": MAX_BATCH_SIZE}

    _mount_web(app, Path(web_dir) if web_dir else DEFAULT_WEB_DIR)
    return app


def compute_static_version(web_dir: Path) -> str:
    """前端内容指纹：任一文件变化都会改变版本号 → 静态 URL 全变 → 旧缓存自动失效。

    这解决的是"用户浏览器缓存了历史上某次发布瞬间的坏文件"的问题——
    响应头层面的 no-cache 对已缓存条目不生效，只有换 URL 才可靠。
    """
    digest = hashlib.sha256()
    for path in sorted(web_dir.rglob("*")):
        if not path.is_file() or path.suffix not in {".js", ".css", ".svg", ".html"}:
            continue
        digest.update(path.relative_to(web_dir).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


class _VersionedStatic(StaticFiles):
    """支持 /static/<version>/... 前缀：版本段仅用于缓存失效，映射到 web 根目录。"""

    def __init__(self, version: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._prefix = f"{version}/"

    async def get_response(self, path: str, scope):  # type: ignore[override]
        # get_path 经 os.path.normpath，Windows 下分隔符是 "\\" 且可能带前导斜杠
        normalized = path.replace("\\", "/").lstrip("/")
        if normalized.startswith(self._prefix):
            return await super().get_response(normalized[len(self._prefix) :], scope)
        return await super().get_response(path, scope)


def _mount_web(app: FastAPI, web_dir: Path) -> None:
    """同源托管前端。目录不存在时（纯后端部署）安静跳过，不影响接口。"""
    index = web_dir / "index.html"
    if not index.exists():
        return
    version = compute_static_version(web_dir)

    def render_index() -> HTMLResponse:
        html = index.read_text(encoding="utf-8").replace("__STATIC_V__", version)
        return HTMLResponse(html)

    app.mount("/static", _VersionedStatic(version, directory=str(web_dir)), name="static")

    @app.get("/", include_in_schema=False)
    def index_page():
        return render_index()

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        icon = web_dir / "favicon.svg"
        if icon.exists():
            return FileResponse(icon, media_type="image/svg+xml")
        return JSONResponse(status_code=204, content=None)

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon_svg():
        icon = web_dir / "favicon.svg"
        if icon.exists():
            return FileResponse(icon, media_type="image/svg+xml")
        return JSONResponse(status_code=204, content=None)

    # SPA 回退：必须注册在所有 API/静态路由之后。前端资源用版本化相对路径引用，
    # 因此深路径不能直接出 HTML（资源会错位到子目录），一律重定向回根路径并
    # 保留查询串（sharecode 等）；/api 与 /static 下的未知路径仍返回 404 JSON。
    @app.get("/{spa_path:path}", include_in_schema=False)
    def spa_fallback(spa_path: str, request: Request):
        if spa_path.startswith(("api/", "static/")) or spa_path == "favicon.ico":
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        if spa_path == "index.html":
            return render_index()
        query = request.url.query
        return RedirectResponse(f"/?{query}" if query else "/", status_code=307)

    # 每次都协商缓存（ETag 仍生效，304 廉价）；版本化 URL 是缓存失效的主手段。
    @app.middleware("http")
    async def _revalidate_static(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path == "/index.html" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response


__all__ = ["create_app"]
