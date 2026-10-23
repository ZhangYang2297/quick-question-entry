"""把用户上传的一批文件展开成有序的图片引用列表。

两条硬约定：
1. **顺序由调用方传入的列表决定**，绝不按文件名重排。上传顺序 = 最终题目编号顺序的依据。
2. **文件名不参与任何判断**。真实用户上传的是微信截图（`微信图片_20261019172341.jpg`）、
   相册导出的一长串哈希名，甚至同名文件来自不同目录。所以这里只把文件名当「展示用标签」，
   内部一律用 upload_order / page_index 定位，连 PDF 拆页的中间产物也不用原名命名。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:  # PyMuPDF ≥1.24 推荐 `pymupdf`，旧版只有 `fitz`
    import pymupdf as fitz
except ImportError:  # pragma: no cover - 仅在旧版 PyMuPDF 上走到
    import fitz

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
PDF_SUFFIXES = {".pdf"}
PDF_DPI = 200


@dataclass(frozen=True)
class ImageRef:
    upload_order: int  # 排序第一键
    page_index: int  # 排序第二键
    path: Path
    display_name: str | None = None  # 仅供界面展示，不参与任何逻辑

    @property
    def key(self) -> tuple[int, int]:
        return (self.upload_order, self.page_index)


def _render_pdf(path: Path, upload_order: int, work_dir: Path) -> list[ImageRef]:
    doc = fitz.open(path)
    refs: list[ImageRef] = []
    try:
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            pixmap = page.get_pixmap(dpi=PDF_DPI)
            # 用序号命名而不是原名：原名可能含特殊字符、超长、或与其他批次重名
            out_path = work_dir / f"u{upload_order:03d}_p{page_index + 1:03d}.png"
            pixmap.save(out_path)
            refs.append(
                ImageRef(
                    upload_order=upload_order,
                    page_index=page_index,
                    path=out_path,
                    display_name=f"{path.name} 第{page_index + 1}页",
                )
            )
    finally:
        doc.close()
    return refs


def load_images(paths: list[Path], *, work_dir: Path) -> list[ImageRef]:
    """按传入顺序展开为 ImageRef 列表；PDF 会被拆成多页。"""
    work_dir.mkdir(parents=True, exist_ok=True)
    refs: list[ImageRef] = []
    for upload_order, raw_path in enumerate(paths):
        path = Path(raw_path)
        suffix = path.suffix.lower()
        if suffix in PDF_SUFFIXES:
            refs.extend(_render_pdf(path, upload_order, work_dir))
        elif suffix in IMAGE_SUFFIXES:
            refs.append(
                ImageRef(
                    upload_order=upload_order,
                    page_index=0,
                    path=path,
                    display_name=path.name,
                )
            )
        else:
            raise ValueError(f"不支持的文件类型：{path}")
    return refs
