"""把领域模型导出为 JSON Schema，供 VLM 强制结构化输出使用。"""

from __future__ import annotations

import json

from qqe.domain.models import PageParse


def page_parse_json_schema() -> dict:
    """模型输出契约的 JSON Schema（不含 order / upload_order / page_index）。"""
    schema = PageParse.model_json_schema()
    schema["title"] = "PageParse"
    return schema


def page_parse_json_schema_text() -> str:
    return json.dumps(page_parse_json_schema(), ensure_ascii=False, indent=2)
