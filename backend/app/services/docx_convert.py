"""Word 文档转换服务（LibreOffice headless）：legacy .doc 归一化 + docx → PDF 预览。

两条转换链路共用同一套 LibreOffice 环境约束（字体、profile、串行化），
因此放在同一模块里——分开会让"两份环境配置各自漂移"，而这里的每一条都是踩坑结论。

三条硬约束，都来自实测踩坑（详见 docs/PDF中文字体渲染问题排查经验.md）：

1. **必须显式提供 fontconfig 配置**：LibreOffice 自带的 fontconfig 不含系统字体目录，
   会导致它看不到任何系统中文字体，PDF 里中文全部渲染为空白——而**文本层是正确的**，
   用"能不能提取出中文"完全查不出来。所以字体目录必须由本服务显式指定。
2. **必须隔离 soffice 的 profile**：多个 soffice 进程共用 profile 会锁冲突失败，
   但复用 profile 能让单次转换从 2.5 秒降到 0.74 秒。折中方案是"每进程一个 profile
   目录（名字带 PID）+ 进程内信号量串行化"。
3. **转换后必须做字形自检**：退出码 0、文件非空、文本层可提取，都不能证明用户看得见内容。
   自检落在渲染像素上——统计含中文区域的实际墨迹比例。
"""

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import BizError

# 缓存键版本：转换逻辑或字体配置语义变化时递增，避免复用旧产物
_CACHE_VERSION = "1"

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# 自动探测字体目录的候选（按平台顺序，只取存在的）
_FONT_DIR_CANDIDATES = [
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/Library/Fonts",
    "~/Library/Fonts",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "~/.fonts",
]

# 自动探测 soffice 的候选路径
_SOFFICE_CANDIDATES = [
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
    "/opt/libreoffice/program/soffice",
]

_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """进程内串行化（延迟创建，避免在无事件循环时实例化）。"""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(max(1, settings.PDF_CONVERT_CONCURRENCY))
    return _semaphore


def _resolve_soffice() -> str:
    """定位 soffice 可执行文件：配置 > PATH > 常见安装路径。"""
    if settings.LIBREOFFICE_BIN:
        return settings.LIBREOFFICE_BIN
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    for candidate in _SOFFICE_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise BizError(
        message="未找到 LibreOffice（soffice）。请安装后配置 LIBREOFFICE_BIN，"
        "macOS 可执行 brew install --cask libreoffice"
    )


def _font_dirs() -> list[str]:
    """字体目录：配置优先，未配置则按平台探测存在的目录。

    返回值必须是绝对路径——相对路径会让 fontconfig 静默失效（见 _ensure_fontconfig）。
    """
    if settings.PDF_FONT_DIRS.strip():
        raw = [p.strip() for p in settings.PDF_FONT_DIRS.split(",") if p.strip()]
    else:
        raw = _FONT_DIR_CANDIDATES
    dirs = []
    for item in raw:
        path = Path(item).expanduser().resolve()
        if path.is_dir():
            dirs.append(str(path))
    return dirs


def _cache_dir() -> Path:
    path = Path(settings.PDF_CACHE_DIR).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_fontconfig(dirs: list[str]) -> Path:
    """生成 fontconfig 配置。

    缺了这份配置，LibreOffice 就看不到系统字体，中文会静默丢失——
    这正是把字体目录做成显式配置项的原因。

    **cachedir 与 dir 都必须写绝对路径**：实测相对 cachedir 会让 fontconfig 整份配置失效
    （日志无报错），LibreOffice 退回自带拉丁字体，PDF 中文再次变成空白——症状与
    "没有配置 fontconfig"完全相同，极难排查。
    """
    if not dirs:
        raise BizError(
            message="未找到可用的字体目录，PDF 预览会丢失中文。"
            "请配置 PDF_FONT_DIRS（容器内通常为 /usr/share/fonts 并安装 fonts-noto-cjk）"
        )
    cache = _cache_dir()
    font_cache = cache / "fontconfig-cache"
    font_cache.mkdir(parents=True, exist_ok=True)
    target = cache / "fonts.conf"
    body = "\n".join(f"  <dir>{d}</dir>" for d in dirs)
    target.write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
        "<fontconfig>\n"
        f"{body}\n"
        f"  <cachedir>{font_cache}</cachedir>\n"
        "</fontconfig>\n",
        encoding="utf-8",
    )
    return target


def _ensure_profile(fontconfig: Path) -> Path:
    """每进程独立的 LibreOffice profile（复用可避免每次重建字体缓存）。

    目录名带上 fontconfig 指纹：profile 会缓存字体解析结果，配置变了必须换一个新目录，
    否则会出现"改了配置却不生效"的假象（实测踩过，见经验文档 6.3）。
    """
    fingerprint = hashlib.sha256(fontconfig.read_bytes()).hexdigest()[:8]
    path = Path(settings.PDF_PROFILE_DIR).expanduser().resolve() / f"lo-{os.getpid()}-{fingerprint}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(source: Path, dirs: list[str]) -> str:
    digest = hashlib.sha256()
    digest.update(_CACHE_VERSION.encode())
    digest.update(Path(source).read_bytes())
    digest.update("|".join(dirs).encode())
    return digest.hexdigest()[:32]


def _source_has_cjk(source: Path) -> bool:
    """源文档是否含中文（决定是否需要做字形自检）。"""
    try:
        with zipfile.ZipFile(source) as archive:
            for name in archive.namelist():
                if name.startswith("word/") and name.endswith(".xml"):
                    if _CJK_RE.search(archive.read(name).decode("utf-8", "ignore")):
                        return True
    except (zipfile.BadZipFile, OSError):
        return False
    return False


def _cjk_ink_ratio(pdf_path: Path, dpi: int = 100, dark: int = 200) -> tuple[int, float]:
    """含中文区域的墨迹比例，返回 (含中文的 span 数, 比例)。

    文本层在字形缺失时依然正确，所以只能从渲染像素判断"用户到底看不看得见"。
    """
    import pymupdf

    spans = 0
    ink_area = 0
    ink_pixels = 0
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            rects = [
                span["bbox"]
                for block in page.get_text("dict")["blocks"]
                for line in block.get("lines", [])
                for span in line["spans"]
                if _CJK_RE.search(span["text"])
            ]
            if not rects:
                continue
            spans += len(rects)
            scale = dpi / 72.0
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
            buf, width, height = pix.samples, pix.width, pix.height
            for x0, y0, x1, y1 in rects:
                for y in range(max(0, int(y0 * scale)), min(height, int(y1 * scale) + 1)):
                    row = y * width
                    for x in range(max(0, int(x0 * scale)), min(width, int(x1 * scale) + 1)):
                        ink_area += 1
                        if buf[row + x] < dark:
                            ink_pixels += 1
    if not ink_area:
        return spans, 0.0
    return spans, ink_pixels / ink_area


def _verify_cjk(pdf_path: Path, source: Path) -> None:
    """中文自检：源文档有中文但 PDF 中文区域没有墨迹，说明字形丢失。"""
    if not _source_has_cjk(source):
        return
    spans, ratio = _cjk_ink_ratio(pdf_path)
    if spans and ratio < settings.PDF_CJK_INK_MIN_RATIO:
        raise BizError(
            message=f"PDF 已生成但中文未渲染（墨迹比例 {ratio:.2%}），预览不可用。"
            "通常是 LibreOffice 未加载到中文字体，请检查 PDF_FONT_DIRS 与字体安装"
            "（参见 docs/PDF中文字体渲染问题排查经验.md）"
        )


def _soffice_context() -> tuple[Path, Path]:
    """准备一次转换所需的 fontconfig 与 profile（两条约束的成因见模块 docstring）。"""
    fontconfig = _ensure_fontconfig(_font_dirs())
    return fontconfig, _ensure_profile(fontconfig)


def _run_soffice(
    source: Path,
    outdir: Path,
    convert_to: str,
    produced_name: str,
    fontconfig: Path,
    profile: Path,
) -> Path:
    """同步执行一次转换，返回产物路径（由 asyncio.to_thread 调用，调用方须持有信号量）。

    convert_to 是 LibreOffice 的导出过滤器名（pdf / docx）；produced_name 是它按源文件
    推导出的产物文件名——LibreOffice 会自行决定输出名，所以这里按约定推导后校验，
    不能只看退出码就认为产物可用。
    """
    binary = _resolve_soffice()
    env = os.environ.copy()
    env["FONTCONFIG_FILE"] = str(fontconfig)
    cmd = [
        binary,
        "--headless",
        # 独立 profile：共用会导致锁冲突；参数值必须是 file:// URL
        f"-env:UserInstallation=file://{profile.resolve()}",
        "--convert-to",
        convert_to,
        "--outdir",
        str(outdir),
        str(source),
    ]
    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=settings.PDF_CONVERT_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BizError(
            message=f"文档转换超时（>{settings.PDF_CONVERT_TIMEOUT} 秒），请稍后重试"
        ) from exc
    produced = Path(outdir) / produced_name
    if result.returncode != 0 or not produced.exists():
        detail = (result.stderr or result.stdout or "").strip()[-400:]
        raise BizError(message=f"文档转换失败：{detail or '未产出文件，请检查文件是否损坏'}")
    return produced


async def convert_to_pdf(source: str | Path, *, force: bool = False) -> Path:
    """把 docx 转成 PDF，返回 PDF 路径（带内容哈希缓存）。

    失败时抛 BizError 并把 LibreOffice 的诊断信息带出来，不静默返回空白件。
    """
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise BizError(message=f"待转换文件不存在：{source}")
    if source.suffix.lower() != ".docx":
        raise BizError(message="当前预览仅支持 .docx 文件")

    dirs = _font_dirs()
    cache = _cache_dir()
    target = cache / f"{_cache_key(source, dirs)}.pdf"
    if target.exists() and not force:
        return target

    fontconfig, profile = _soffice_context()

    async with _get_semaphore():
        # 双重检查：等待信号量期间可能已被其它请求转换完成
        if target.exists() and not force:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="docx2pdf-") as workdir:
            produced = await asyncio.to_thread(
                _run_soffice, source, Path(workdir), "pdf", f"{source.stem}.pdf", fontconfig, profile
            )
            shutil.move(str(produced), str(target))

    try:
        _verify_cjk(target, source)
    except BizError:
        # 自检不过的产物必须丢弃，避免下次命中缓存直接把坏件返回
        target.unlink(missing_ok=True)
        raise
    return target


# ===== legacy .doc 归一化 =====
#
# .doc 是 Word 97-2003 的 OLE2 复合文档，与 .docx 的 OOXML（zip 包）是两种格式，
# python-docx / docxtpl / Dify 都只处理 .docx。所以在入口处统一归一化，
# 让下游只面对一种格式，而不是在每个消费方各写一遍兼容。
#
# 实测结论（直连 Dify create_by_file 交叉验证文件名与内容两个变量）：Dify 按 multipart
# 的文件名后缀做白名单校验，.doc 直接 400 invalid_param 且 message 为空——看不出原因；
# 把已经是 .docx 的内容用 .doc 的名字上传同样被拒。所以归一化之后必须连文件名一起换成
# .docx，只换内容不换名等于没换。


def is_legacy_doc(filename: str | Path) -> bool:
    """是否为 Word 97-2003 二进制格式（.doc）。"""
    return Path(filename).suffix.lower() == ".doc"


def _verify_docx(path: Path, source: Path) -> None:
    """结构自检：产物必须是含 word/document.xml 的 OOXML 包。

    只看退出码和文件大小不够——soffice 对损坏输入也可能"成功"产出一个空壳，
    而空壳会以"文档内容为空"的形式混过审查，暴露成假结论而不是报错。
    """
    try:
        with zipfile.ZipFile(path) as archive:
            if "word/document.xml" not in archive.namelist():
                raise KeyError("缺少 word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise BizError(
            message=f"「{source.name}」转换为 .docx 后结构异常（{exc}）。"
            "文件可能已损坏，请先用 Word 打开并另存为 .docx 再上传"
        ) from exc


async def convert_legacy_doc(source: str | Path, dest_dir: str | Path) -> Path:
    """把 .doc 转成 .docx，返回产物路径（产物名为 `<源文件名>.docx`）。

    与 convert_to_pdf 不同，这里不做缓存：归一化只在上传入口发生一次，产物由调用方
    持久化，重复转换同一份文件没有意义。dest_dir 中若已有同名文件会被覆盖，
    因此调用方应保证源文件名唯一（上传落盘时都带 uuid）。
    """
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise BizError(message=f"待转换文件不存在：{source}")

    dest_dir = Path(dest_dir).expanduser().resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{source.stem}.docx"

    fontconfig, profile = _soffice_context()
    async with _get_semaphore():
        await asyncio.to_thread(
            _run_soffice, source, dest_dir, "docx", target.name, fontconfig, profile
        )
    _verify_docx(target, source)
    return target


async def is_available() -> tuple[bool, str]:
    """转换能力是否就绪（供健康检查/前端提示使用）。"""
    try:
        _resolve_soffice()
    except BizError as exc:
        return False, exc.message
    if not _font_dirs():
        return False, "未找到可用的字体目录，PDF 预览会丢失中文，请配置 PDF_FONT_DIRS"
    return True, "ok"


# ===== 预览用光栅化 =====
#
# 预览不把 PDF 交给前端 pdf.js 渲染：pdf.js 处理 LibreOffice 导出的中文 CID 子集时
# 字形映射会错位（汉字被渲染成 `! " # $` 之类的 ASCII 字形），而同一份 PDF 用 MuPDF
# 渲染完全正确。因此由后端用 PyMuPDF 光栅化成 PNG，前端只负责展示图片。
# 代价是预览不可选中文字，换来的是跨平台稳定的中文渲染。

DEFAULT_PREVIEW_DPI = 110


def _page_cache_path(pdf_path: Path, page_no: int, dpi: int) -> Path:
    return _cache_dir() / f"{pdf_path.stem}-p{page_no}-{dpi}.png"


async def preview_meta(source: str | Path, dpi: int = DEFAULT_PREVIEW_DPI) -> dict:
    """预览元信息：页数 + 每页尺寸（点），供前端占位与分页。"""
    import pymupdf

    pdf_path = await convert_to_pdf(source)
    with pymupdf.open(pdf_path) as doc:
        pages = [
            {"page": index + 1, "width": round(page.rect.width, 1), "height": round(page.rect.height, 1)}
            for index, page in enumerate(doc)
        ]
    return {"dpi": dpi, "page_count": len(pages), "pages": pages}


async def render_page(source: str | Path, page_no: int, dpi: int = DEFAULT_PREVIEW_DPI) -> Path:
    """把 PDF 指定页渲染为 PNG（带缓存），返回图片路径。"""
    import pymupdf

    pdf_path = await convert_to_pdf(source)
    target = _page_cache_path(pdf_path, page_no, dpi)
    if target.exists():
        return target

    def _render() -> None:
        with pymupdf.open(pdf_path) as doc:
            if page_no < 1 or page_no > doc.page_count:
                raise BizError(message=f"页码超出范围（共 {doc.page_count} 页）")
            page = doc[page_no - 1]
            pix = page.get_pixmap(dpi=dpi)
            target.write_bytes(pix.tobytes("png"))

    await asyncio.to_thread(_render)
    return target
