"""假模型：让 M0/M1 全流程离线可测，不需要任何 API Key。"""

from __future__ import annotations

from pathlib import Path


class FakeVisionModel:
    name = "fake"

    def __init__(
        self,
        responses: dict[str, list[str] | str] | None = None,
        default: str | None = None,
    ) -> None:
        self._responses: dict[str, list[str]] = {
            key: (value if isinstance(value, list) else [value])
            for key, value in (responses or {}).items()
        }
        self._default = default
        self.calls: list[str] = []

    def complete_json(
        self,
        *,
        system_prompt: str,
        image_path: Path,
        json_schema: dict,
        feedback: str | None = None,
    ) -> str:
        file_name = Path(image_path).name
        self.calls.append(file_name)
        queue = self._responses.get(file_name)
        if not queue:
            if self._default is None:
                raise LookupError(f"FakeVisionModel 未为 {file_name} 配置响应")
            return self._default
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0]


# 离线演示用：不调模型也能跑通「图片 → Word」的整条链路
DEMO_PAGE_JSON = """{
  "title": "离线演示文档",
  "groups": ["一、单项选择题"],
  "questions": [
    {
      "source_label": "1",
      "type": "single_choice",
      "stem": "（离线演示）这道题由 --fake 生成，用于验证「图片 → 题目 → Word」链路是否通畅。",
      "options": [
        {"label": "A", "text": "占位选项一"},
        {"label": "B", "text": "占位选项二"}
      ],
      "column": 0
    },
    {
      "source_label": "2",
      "type": "true_false",
      "stem": "（离线演示）判断题占位题干，判断题天然没有选项。",
      "options": [],
      "column": 0
    }
  ]
}"""


def demo_model() -> FakeVisionModel:
    """所有图片都返回同一份演示结果 —— 只用来验证链路，不用来评测质量。"""
    return FakeVisionModel(default=DEMO_PAGE_JSON)
