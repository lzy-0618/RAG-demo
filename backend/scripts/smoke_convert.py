"""docx → PDF 转换冒烟测试：验证预览链路可用（含中文字形自检）。

用法（在 backend/ 下执行）：
    .venv/bin/python scripts/smoke_convert.py [docx 路径 ...]
不传路径时用 outputs/ 下最新的 .docx 作为样本。
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.exceptions import BizError  # noqa: E402
from app.services import docx_convert  # noqa: E402


def _pick_samples(argv: list[str]) -> list[Path]:
    if argv:
        return [Path(p) for p in argv]
    outputs = Path("outputs")
    found = sorted(outputs.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not found:
        print("outputs/ 下没有 .docx 样本，请显式传入文件路径")
        sys.exit(2)
    return found[:2]


async def main() -> int:
    available, reason = await docx_convert.is_available()
    print(f"转换能力：{'就绪' if available else '不可用'}（{reason}）")
    if not available:
        return 1

    print(f"字体目录：{docx_convert._font_dirs()}")
    failed = 0
    for sample in _pick_samples(sys.argv[1:]):
        started = time.perf_counter()
        try:
            first = await docx_convert.convert_to_pdf(sample)
            cost = time.perf_counter() - started
            again = await docx_convert.convert_to_pdf(sample)
            spans, ratio = docx_convert._cjk_ink_ratio(first)
            print(
                f"✅ {sample.name}\n"
                f"   PDF: {first}（{first.stat().st_size / 1024:.1f} KB，耗时 {cost:.2f}s，"
                f"缓存命中={again == first}）\n"
                f"   中文自检：含中文 span {spans} 个，墨迹比例 {ratio:.2%}"
            )
        except BizError as exc:
            failed += 1
            print(f"❌ {sample.name}\n   {exc.message}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
