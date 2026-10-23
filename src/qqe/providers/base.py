"""Provider 抽象。业务代码只依赖这个协议，不碰任何厂商 SDK / URL。"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class VisionModel(Protocol):
    name: str

    def complete_json(
        self,
        *,
        system_prompt: str,
        image_path: Path,
        json_schema: dict,
        feedback: str | None = None,
    ) -> str:
        """调用视觉模型，返回**原始文本**（期望是 JSON）。

        feedback 用于自修复重试：把上一次的校验错误回喂给模型。
        Provider 只负责搬运，不做 JSON 校验 —— 那是 parser 层的职责。
        """
        ...
