"""演示用假模型：不花钱、不联网，用来把前端整条链路跑通。

设计约束：
- 输出必须过 `PageParse` 契约与校验层，所以校对页、表格、残题过滤都能真跑到；
- **不读文件名**：内容只由调用序号决定，和真实用户那些一长串哈希名无关；
- 题目内容固定可预期，方便人眼检查"编号是否按上传顺序"。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

_STEMS = [
    "患者，男性，68岁，因急性心肌梗死入院。护士进行心电监护时发现频发室性期前收缩，首要的护理措施是",
    "患者，女性，54岁，行胃大部切除术后第3天。护士观察其切口敷料，下列处理正确的是",
    "护士为一位慢性阻塞性肺疾病患者进行氧疗指导，下列叙述正确的是",
    "关于无菌技术操作原则，下列说法错误的是",
]
_OPTIONS = [
    ("A", "立即通知医生并准备除颤"),
    ("B", "加快补液速度"),
    ("C", "协助患者取平卧位"),
    ("D", "给予高流量吸氧"),
]


class DemoVisionModel:
    """每次调用返回 1~2 道题，第二页额外给一道带表格的题。"""

    name = "demo"

    def __init__(self) -> None:
        self._counter = 0
        self._lock = threading.Lock()
        self.calls: list[str] = []

    def complete_json(
        self,
        *,
        system_prompt: str,
        image_path: Path,
        json_schema: dict,
        feedback: str | None = None,
    ) -> str:
        self.calls.append(Path(image_path).name)
        with self._lock:
            index = self._counter
            self._counter += 1

        questions: list[dict] = [
            {
                "type": "single_choice",
                "stem": _STEMS[index % len(_STEMS)],
                "options": [{"label": label, "text": text} for label, text in _OPTIONS],
                "source_label": str(index + 1),
            }
        ]
        if index % 3 == 2:
            questions.append(
                {
                    "type": "true_false",
                    "stem": f"第 {index + 1} 页补充：判断下列说法是否正确——长期卧床患者应每 2 小时翻身一次。",
                    "source_label": str(index + 2),
                }
            )
        if index % 4 == 1:
            questions.append(
                {
                    "type": "single_choice",
                    "stem": "根据下表所示的体温变化，该患者最可能出现的护理问题是",
                    "options": [{"label": label, "text": text} for label, text in _OPTIONS[:3]],
                    "tables": [
                        {
                            "caption": "体温记录",
                            "headers": ["时间", "体温(℃)", "脉搏(次/分)"],
                            "rows": [["08:00", "38.6", "98"], ["12:00", "39.1", "106"]],
                        }
                    ],
                    "source_label": str(index + 3),
                }
            )
        return json.dumps({"questions": questions}, ensure_ascii=False)


__all__ = ["DemoVisionModel"]
