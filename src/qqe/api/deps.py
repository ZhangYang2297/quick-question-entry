"""FastAPI 依赖：服务实例、当前用户、归属校验。

鉴权现在是**可替换的薄层**：默认从 `X-User-Id` 头取用户，未带则视为 "local"。
接入云服务登录态时，只需替换 `current_user` 的实现，路由层无需改动。
"""

from __future__ import annotations

from fastapi import Header, Request

from qqe.api.jobs import JobManager
from qqe.project.service import ProjectService


def current_user(x_user_id: str | None = Header(default=None)) -> str:
    return (x_user_id or "local").strip() or "local"


def get_service(request: Request) -> ProjectService:
    return request.app.state.service


def get_jobs(request: Request) -> JobManager:
    return request.app.state.jobs
