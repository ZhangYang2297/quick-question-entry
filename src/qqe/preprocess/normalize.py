"""图片归一化：EXIF 矫正 + 尺寸归一（+ 可选纠偏）。

纠偏是可选增强：VLM 对轻微倾斜本就有鲁棒性，先保证主链路稳定。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

MAX_SIDE = 2000


def normalize_image(src: Path, dst: Path, *, max_side: int = MAX_SIDE) -> Path:
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        long_side = max(image.size)
        if long_side > max_side:
            scale = max_side / long_side
            new_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
            image = image.resize(new_size, Image.LANCZOS)
        image.save(dst, format="PNG")
    return dst


def estimate_skew_angle(
    image: Image.Image, *, max_angle: float = 8.0, step: float = 0.5, sample_width: int = 800
) -> float:
    """用投影轮廓法估计倾斜角（返回需要旋转的角度，顺时针为正）。

    原理：把图像二值化后，文字行的水平投影在摆正时方差最大。
    """
    gray = image.convert("L")
    if gray.width > sample_width:
        ratio = sample_width / gray.width
        gray = gray.resize((sample_width, max(1, int(gray.height * ratio))), Image.BILINEAR)

    ink = (255.0 - np.asarray(gray, dtype=np.float32)) / 255.0
    binary = (ink > 0.5).astype(np.uint8) * 255

    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(-max_angle, max_angle + step / 2, step):
        rotated = np.asarray(
            Image.fromarray(binary).rotate(float(angle), resample=Image.BILINEAR, expand=False),
            dtype=np.float32,
        )
        score = float(np.var(rotated.sum(axis=1)))
        if score > best_score:
            best_score, best_angle = score, float(angle)
    return best_angle
