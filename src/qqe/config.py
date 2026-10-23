"""集中读取环境配置。业务代码不直接读 os.environ。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GLM_MODELS = ("glm-4.6v-flash", "glm-4.6v")
DEFAULT_GLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def _parse_models(raw: str | None) -> tuple[str, ...]:
    """GLM_MODELS="a,b" → ("a", "b")；空值回落到「免费优先 + 付费兜底」。"""
    if not raw:
        return DEFAULT_GLM_MODELS
    models = tuple(part.strip() for part in raw.split(",") if part.strip())
    return models or DEFAULT_GLM_MODELS


@dataclass(frozen=True)
class Settings:
    provider: str = "fake"
    max_concurrency: int = 4
    page_timeout: int = 60
    glm_api_key: str | None = None
    qwen_api_key: str | None = None
    # 模型链：按顺序尝试，第一个可用即用；免费模型忙了自动降级到付费
    glm_models: tuple[str, ...] = field(default_factory=lambda: DEFAULT_GLM_MODELS)
    glm_base_url: str = DEFAULT_GLM_BASE_URL
    glm_max_tokens: int = 8192

    @classmethod
    def load(cls, env_file: Path | None = None) -> Settings:
        load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)
        return cls(
            provider=os.getenv("QQE_PROVIDER", "fake"),
            max_concurrency=int(os.getenv("QQE_MAX_CONCURRENCY", "4")),
            page_timeout=int(os.getenv("QQE_PAGE_TIMEOUT", "60")),
            glm_api_key=os.getenv("GLM_API_KEY") or None,
            qwen_api_key=os.getenv("QWEN_API_KEY") or None,
            glm_models=_parse_models(os.getenv("GLM_MODELS")),
            glm_base_url=os.getenv("GLM_BASE_URL") or DEFAULT_GLM_BASE_URL,
            glm_max_tokens=int(os.getenv("GLM_MAX_TOKENS", "8192")),
        )
