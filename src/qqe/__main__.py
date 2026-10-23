"""离线 CLI：一条命令完成「图片/PDF → Word」。

    python -m qqe run 图1.jpg 图2.jpg -o 输出.docx --style 标准试卷版 --review
    python -m qqe run 新图.jpg  -o 输出.docx --project 我的题库.qqe.json   # 续加
    python -m qqe run 图片目录  -o 输出.docx --fake                        # 离线演示

**顺序只取决于参数顺序**（目录模式按文件名自然序，仅作为便利排序）。
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections.abc import Sequence
from pathlib import Path

from qqe.config import Settings
from qqe.domain.style import DEFAULT_PRESET, get_preset, list_presets
from qqe.orchestrator.pipeline import PipelineResult, run_pipeline
from qqe.parser.batch import BatchResult
from qqe.preprocess.loader import IMAGE_SUFFIXES, PDF_SUFFIXES
from qqe.providers import build_model
from qqe.providers.fake import demo_model

SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | PDF_SUFFIXES

TYPE_LABELS = {
    "single_choice": "单选",
    "multi_choice": "多选",
    "true_false": "判断",
    "fill_blank": "填空",
    "short_answer": "简答",
    "term_define": "名词",
    "case_analysis": "案例",
}


def _natural_key(name: str) -> tuple:
    """目录模式的便利排序：`第2页` 排在 `第10页` 前面。

    注意：这**只**用于「用户给了一个目录、没给显式顺序」的兜底，
    绝不参与领域层任何排序（题目顺序的唯一真相是上传顺序）。
    """
    parts = re.split(r"(\d+)", name)
    return tuple((0, int(part)) if part.isdigit() else (1, part.lower()) for part in parts if part)


def expand_inputs(items: Sequence[str], order_file: Path | None = None) -> list[Path]:
    """把命令行参数展开成**有序**的文件列表。"""
    if order_file is not None:
        base = Path(order_file).resolve().parent
        paths: list[Path] = []
        for raw in Path(order_file).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            candidate = Path(line)
            if not candidate.is_absolute():
                candidate = base / candidate
            if not candidate.is_file():
                raise FileNotFoundError(f"顺序清单里的文件不存在：{candidate}")
            paths.append(candidate)
        if not paths:
            raise ValueError(f"顺序清单是空的：{order_file}")
        return paths

    paths = []
    for item in items:
        path = Path(item)
        if path.is_dir():
            found = sorted(
                (
                    child
                    for child in path.iterdir()
                    if child.is_file() and child.suffix.lower() in SUPPORTED_SUFFIXES
                ),
                key=lambda child: _natural_key(child.name),
            )
            paths.extend(found)
        elif path.is_file():
            paths.append(path)
        else:
            raise FileNotFoundError(f"路径不存在：{path}")
    if not paths:
        raise ValueError("没有找到可处理的图片或 PDF")
    return paths


def _clip(text: str, width: int = 46) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def _display_width(text: str) -> int:
    """终端里中文占两格，按显示宽度算列对齐才不会歪。"""
    return sum(2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def format_review(batch: BatchResult) -> str:
    """校对视图：order 与 source_label 必须同时可见（前者是输出顺序，后者用于溯源）。"""
    lines: list[str] = []
    questions = batch.question_set.questions
    lines.append(f"解析结果：共 {len(questions)} 题（{len(batch.outcomes)} 张图）")
    if batch.question_set.title:
        lines.append(f"文档标题：{batch.question_set.title}")
    lines.append("")
    lines.append(f"{_pad('序号', 6)}{_pad('源题号', 10)}{_pad('题型', 8)}题干")
    for question in questions:
        label = question.source_label or "-"
        kind = TYPE_LABELS.get(str(question.type), str(question.type))
        flag = " ⚠" if question.warnings else ""
        lines.append(
            f"{_pad(str(question.order), 6)}{_pad(label, 10)}{_pad(kind, 8)}"
            f"{_clip(question.stem)}{flag}"
        )

    if batch.excluded:
        lines.append("")
        lines.append(f"已排除残题 {len(batch.excluded)} 道（不完整，不进入导出）：")
        for question in batch.excluded:
            reason = question.fragment_reason or "不完整"
            lines.append(f"  - [{reason}] {_clip(question.stem)}")

    if batch.failed:
        lines.append("")
        lines.append(f"解析失败 {len(batch.failed)} 页（不影响其他页）：")
        for failed in batch.failed:
            lines.append(
                f"  - 第{failed.upload_order + 1}张/第{failed.page_index + 1}页：{failed.error}"
            )
    return "\n".join(lines)


def _confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return True  # 非交互环境（管道/定时任务）默认继续
    return input(prompt).strip().lower() in {"", "y", "yes", "是"}


def _cmd_run(args: argparse.Namespace) -> int:
    settings = Settings.load()
    if args.fake or settings.provider == "fake":
        model = demo_model()
    else:
        model = build_model(settings)

    paths = expand_inputs(args.paths, args.order_file)
    style = get_preset(args.style) if args.style else None

    review_hook = None
    if args.review:

        def review_hook(batch: BatchResult) -> bool:
            print(format_review(batch))
            print()
            return args.yes or _confirm("确认并入文档并导出？[Y/n] ")

    result = run_pipeline(
        paths,
        model=model,
        out_path=Path(args.output),
        style=style,
        project_path=Path(args.project) if args.project else None,
        project_name=args.name,
        max_concurrency=args.concurrency or settings.max_concurrency,
        on_review=review_hook,
    )
    _print_summary(result)
    return 0 if result.ok else 1


def _print_summary(result: PipelineResult) -> None:
    if not result.ok:
        print(f"\n[失败] 状态 {result.state}：{result.error}", file=sys.stderr)
        if result.batch and result.batch.excluded:
            print(f"       本次还有 {len(result.batch.excluded)} 道残题被排除", file=sys.stderr)
        return

    added = 0
    if result.document and result.batch_seq:
        added = sum(
            1 for q in result.document.question_set.questions if q.batch_seq == result.batch_seq
        )
    print("\n[完成]")
    print(
        f"  文档题数：{result.question_count} 题（本批新增 {added} 题，批次 #{result.batch_seq}）"
    )
    if result.docx_path:
        print(f"  输出文件：{result.docx_path}")
    if result.project_path:
        print(f"  项目文件：{result.project_path}（下次续加用 --project 指定它）")
    print(f"  耗时 {result.elapsed_s}s · 花费 ¥{result.cost_cny:.4f}")
    if result.batch and result.batch.failed:
        print(f"  注意：{len(result.batch.failed)} 页解析失败，已跳过（详见 --review 输出）")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qqe", description="快速录题：图片 → 结构化题目 → Word")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="解析图片/PDF 并导出 Word")
    run.add_argument("paths", nargs="+", help="图片或 PDF 文件；也可以是目录")
    run.add_argument("-o", "--output", default="out.docx", help="输出的 .docx 路径")
    run.add_argument("--style", choices=list_presets(), default=None, help="样式预设")
    run.add_argument("--project", help="文档项目 JSON；传入已存在的文件即为续加")
    run.add_argument("--name", help="新建文档时的名称")
    run.add_argument(
        "--order-file",
        type=Path,
        help="显式顺序清单（每行一个文件路径），用于目录模式覆盖自然序",
    )
    run.add_argument("--review", action="store_true", help="导出前打印解析结果供确认")
    run.add_argument("-y", "--yes", action="store_true", help="跳过确认提示")
    run.add_argument("--concurrency", type=int, default=None, help="并发解析张数（默认 4）")
    run.add_argument("--fake", action="store_true", help="离线演示：不调用任何模型")
    run.set_defaults(func=_cmd_run)

    styles = sub.add_parser("styles", help="列出可用样式预设")
    styles.set_defaults(func=lambda _args: _cmd_styles())

    serve = sub.add_parser("serve", help="启动 HTTP 服务（文档项目 / 续加 / 导出）")
    serve.add_argument("--host", default="127.0.0.1", help="监听地址（默认只本机）")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--db", default="data/qqe.db", help="SQLite 数据库路径")
    serve.add_argument("--uploads", default="data/uploads", help="上传文件存放目录")
    serve.add_argument("--out", default="out", help="导出 .docx 存放目录")
    serve.add_argument(
        "--fake",
        action="store_true",
        help="演示模式：用内置假模型，不联网、不产生费用（适合调前端）",
    )
    serve.set_defaults(func=_cmd_serve)
    return parser


def _cmd_serve(args) -> int:
    import os

    import uvicorn  # 局部 import：不用服务时不必加载

    from qqe.api import create_app

    model = None
    if args.fake:
        from qqe.providers.demo import DemoVisionModel

        model = DemoVisionModel()

    # 托管平台通过 PORT 环境变量注入端口并要求监听 0.0.0.0；
    # 本地开发仍以 --host/--port 参数为准。
    port = int(os.environ["PORT"]) if "PORT" in os.environ else args.port
    host = "0.0.0.0" if "PORT" in os.environ else args.host

    app = create_app(
        db_path=args.db,
        uploads_dir=args.uploads,
        out_dir=args.out,
        model=model,
    )
    print(f"页面：http://{host}:{port}/")
    print(f"接口文档：http://{host}:{port}/api/docs")
    uvicorn.run(app, host=host, port=port)
    return 0


def _cmd_styles() -> int:
    print("可用样式预设：")
    for name in list_presets():
        marker = "（默认）" if name == DEFAULT_PRESET else ""
        print(f"  - {name}{marker}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"[参数错误] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
