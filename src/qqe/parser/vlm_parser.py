"""调用模型并把原始文本解析成 PageParse。JSON 容错解析在这里，不在 Provider 里。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import ValidationError

from qqe.domain.models import PageParse
from qqe.parser.prompt import SYSTEM_PROMPT
from qqe.providers.base import VisionModel

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class ParseError(Exception):
    """模型响应无法转成结构化结果。"""


def extract_json(raw: str) -> dict:
    """从模型响应中尽力提取 JSON 对象。

    真实模型（尤其是带思考链的 4.6V-Flash）常出现三种脏输出：
    代码块包裹、前后夹带说明文字、**JSON 后面又跟了一段废话或第二个 JSON**。
    所以这里用 raw_decode 只吃第一个完整对象，剩下的垃圾直接丢弃。
    """
    text = (raw or "").strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    start = text.find("{")
    if start == -1:
        raise ParseError("响应中找不到 JSON 对象")

    try:
        payload, _end = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ParseError(f"JSON 解析失败：{exc}") from exc
    if not isinstance(payload, dict):
        raise ParseError("响应顶层不是 JSON 对象")
    return payload


def _normalize_payload(payload: dict) -> dict:
    """把常见的轻微走形拉回契约，避免无意义的重试。"""
    groups = payload.get("groups")
    if isinstance(groups, list):
        payload["groups"] = [
            g if isinstance(g, str) else str(g.get("title") or g.get("name") or "") for g in groups
        ]
    return payload


def _ensure_page_contract(payload: dict) -> None:
    """顶层必须是 PageParse（含 questions），否则交给自修复重试。

    真实翻车案例：模型忽略外层契约、直接吐出一道题（顶层有 stem/options 但没有 questions），
    此时 PageParse 会静默构造出「0 道题」的结果 —— 比报错更危险，必须拦下。
    """
    if "questions" in payload:
        return
    if any(key in payload for key in ("stem", "options", "type")):
        raise ParseError("顶层缺少 questions：模型只返回了单道题，未按 PageParse 契约输出")
    raise ParseError("顶层缺少 questions 字段，不符合 PageParse 契约")


def parse_page_text(raw: str) -> PageParse:
    payload = _normalize_payload(extract_json(raw))
    _ensure_page_contract(payload)
    try:
        return PageParse.model_validate(payload)
    except ValidationError as exc:
        raise ParseError(f"不符合输出契约：{exc}") from exc


def parse_page(
    model: VisionModel,
    image_path: Path,
    *,
    schema: dict,
    system_prompt: str = SYSTEM_PROMPT,
    feedback: str | None = None,
) -> PageParse:
    raw = model.complete_json(
        system_prompt=system_prompt,
        image_path=image_path,
        json_schema=schema,
        feedback=feedback,
    )
    return parse_page_text(raw)
