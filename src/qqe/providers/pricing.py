"""模型价格表（元 / 百万 tokens），用于单张成本核算。

价格来自智谱开放平台定价页（2026-10 抓取）。**只用于估算**，以账单为准。
新增模型必须在这里登记价格，否则成本核算返回 None（不猜，不静默按 0 算）。
"""

from __future__ import annotations

# model -> (输入单价, 输出单价)，单位：元 / 百万 tokens
PRICES_CNY_PER_MTOK: dict[str, tuple[float, float]] = {
    # 视觉理解
    "glm-4.6v": (1.0, 3.0),
    "glm-4.6v-flash": (0.0, 0.0),
    "glm-4.6v-flashx": (0.15, 1.5),
    "glm-4.5v": (2.0, 6.0),
    "glm-4v-plus-0111": (4.0, 4.0),
    "glm-4v-flash": (0.0, 0.0),
    "glm-4.1v-thinking-flash": (0.0, 0.0),
}


def estimate_cost_cny(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """估算单次调用成本（元）。未登记价格的模型返回 None。"""
    price = PRICES_CNY_PER_MTOK.get(model)
    if price is None:
        return None
    input_price, output_price = price
    return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000
