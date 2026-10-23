"""模型 Provider 工厂：换模型只改配置。"""

from __future__ import annotations

from qqe.config import Settings
from qqe.providers.base import VisionModel
from qqe.providers.fake import FakeVisionModel
from qqe.providers.glm import GlmVisionModel, ModelBusyError, ModelRequestError

__all__ = [
    "FakeVisionModel",
    "GlmVisionModel",
    "ModelBusyError",
    "ModelRequestError",
    "VisionModel",
    "build_model",
]


def build_model(settings: Settings) -> VisionModel:
    if settings.provider == "fake":
        return FakeVisionModel()
    if settings.provider == "glm":
        if not settings.glm_api_key:
            raise ModelRequestError("QQE_PROVIDER=glm 但 GLM_API_KEY 未配置（检查 .env）")
        return GlmVisionModel(
            api_key=settings.glm_api_key,
            models=settings.glm_models,
            base_url=settings.glm_base_url,
            max_tokens=settings.glm_max_tokens,
            timeout=float(settings.page_timeout * 3),
        )
    raise NotImplementedError(f"尚未接入的 Provider：{settings.provider}")
