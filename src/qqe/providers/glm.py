"""智谱 GLM 视觉模型 Provider。

三个真实世界里必须处理的点（都是实测逼出来的）：
1. **免费模型经常 429 / 1305「访问量过大」** —— 必须重试 + 退避，并提供付费模型兜底。
2. **glm-4v-flash 的 max_tokens 上限只有 1024** —— 双栏书页会被截断，只能用于截图类稀疏图；
   发超限值会被直接判非法，所以要按模型钳制。
3. **智谱 4.5V/4.6V 默认开思考链** —— 本项目只要 instruct 结果，必须显式关掉。
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from qqe.providers.pricing import estimate_cost_cny

DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
# 免费优先，付费兜底：flash 是免费的，但它一忙就必须有后备
DEFAULT_MODELS: tuple[str, ...] = ("glm-4.6v-flash", "glm-4.6v")
# 各模型的最大输出 token 上限（发超限会直接 400）
MODEL_MAX_OUTPUT_TOKENS: dict[str, int] = {"glm-4v-flash": 1024, "glm-4.1v-thinking-flash": 1024}
# 超过这个大小就先压缩（智谱单图 base64 上限约 5MB）
MAX_IMAGE_BYTES = 4 * 1024 * 1024

_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
_BUSY_CODES = {"1305", "1302", "1303", "1304"}


class ModelBusyError(RuntimeError):
    """所有候选模型都繁忙/不可用 —— 属于可重试的临时故障。"""


class ModelRequestError(RuntimeError):
    """请求本身有问题（Key 无效、参数非法）—— 重试没有意义。"""


@dataclass
class CallRecord:
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_cny: float | None = None
    attempts: int = 1


@dataclass
class GlmVisionModel:
    api_key: str
    models: Sequence[str] = DEFAULT_MODELS
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 180.0
    max_tokens: int = 8192
    max_retries: int = 3
    backoff_seconds: float = 1.5
    client: httpx.Client | None = None
    sleep: Callable[[float], None] = time.sleep
    calls: list[CallRecord] = field(default_factory=list)
    # 整条模型链失败后再整体重来几轮（免费模型和网关抖动常常是同时发生的）
    chain_rounds: int = 2

    name = "glm"

    # ---- 对外接口 -------------------------------------------------------
    def complete_json(
        self,
        *,
        system_prompt: str,
        image_path: Path,
        json_schema: dict,
        feedback: str | None = None,
    ) -> str:
        user_text = self._build_user_text(json_schema, feedback)
        image_b64 = encode_image(Path(image_path))

        errors: list[str] = []
        for round_index in range(1, self.chain_rounds + 1):
            for model in self.models:
                try:
                    return self._call_with_retry(model, system_prompt, user_text, image_b64)
                except ModelRequestError as exc:
                    errors.append(f"{model}: {exc}")
                    if "api key" in str(exc).lower():
                        raise
                except ModelBusyError as exc:
                    errors.append(f"{model}: {exc}")
            if round_index < self.chain_rounds:
                self.sleep(self.backoff_seconds * 4 * round_index)
        raise ModelBusyError("全部候选模型均不可用 → " + " | ".join(errors))

    @property
    def last_call(self) -> CallRecord | None:
        return self.calls[-1] if self.calls else None

    @property
    def total_cost_cny(self) -> float:
        return sum(c.cost_cny or 0.0 for c in self.calls)

    # ---- 内部实现 -------------------------------------------------------
    def _call_with_retry(
        self, model: str, system_prompt: str, user_text: str, image_b64: str
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                content, usage = self._post(model, system_prompt, user_text, image_b64)
            except ModelBusyError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
                    continue
                break
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            self.calls.append(
                CallRecord(
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_cny=estimate_cost_cny(model, prompt_tokens, completion_tokens),
                    attempts=attempt,
                )
            )
            return content
        raise ModelBusyError(str(last_error))

    def _post(
        self, model: str, system_prompt: str, user_text: str, image_b64: str
    ) -> tuple[str, dict]:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_b64}},
                        {"type": "text", "text": user_text},
                    ],
                },
            ],
            "temperature": 0.1,
            "max_tokens": min(self.max_tokens, MODEL_MAX_OUTPUT_TOKENS.get(model, self.max_tokens)),
            "response_format": {"type": "json_object"},
            # 只要 instruct 结果，不要思考链
            "thinking": {"type": "disabled"},
        }
        client = self.client or httpx.Client(timeout=self.timeout)
        owns_client = self.client is None
        try:
            response = client.post(
                self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        except httpx.HTTPError as exc:  # 网络抖动按临时故障处理
            raise ModelBusyError(f"网络错误：{exc}") from exc
        finally:
            if owns_client:
                client.close()

        if response.status_code == 429:
            raise ModelBusyError("HTTP 429 频率/并发受限")
        if response.status_code in {401, 403}:
            raise ModelRequestError(f"api key 无效或无权限（HTTP {response.status_code}）")
        if response.status_code >= 500:
            raise ModelBusyError(f"服务端错误 HTTP {response.status_code}")

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ModelBusyError(f"响应不是 JSON（HTTP {response.status_code}）") from exc

        error = data.get("error")
        if error:
            code = str(error.get("code", ""))
            message = str(error.get("message", ""))
            if code in _BUSY_CODES:
                raise ModelBusyError(f"{code} {message}")
            raise ModelRequestError(f"{code} {message}")

        choices = data.get("choices") or []
        if not choices:
            raise ModelBusyError("响应缺少 choices")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if not content.strip():
            raise ModelBusyError("模型返回空内容")
        return content, data.get("usage") or {}

    @staticmethod
    def _build_user_text(json_schema: dict, feedback: str | None) -> str:
        parts = [
            "请按下面这个 JSON Schema 输出本页结果，只输出一个 JSON 对象：",
            json.dumps(json_schema, ensure_ascii=False),
        ]
        if feedback:
            parts.append("上一次输出存在以下问题，请修正后重新输出完整 JSON：\n" + feedback)
        return "\n\n".join(parts)


def encode_image(path: Path) -> str:
    """把图片读成 base64（智谱接受裸 base64，不需要 data: 前缀）。"""
    raw = Path(path).read_bytes()
    if len(raw) > MAX_IMAGE_BYTES:
        raise ModelRequestError(
            f"图片过大（{len(raw) / 1024 / 1024:.1f}MB），请先压缩到 4MB 以内：{path.name}"
        )
    return base64.b64encode(raw).decode()
