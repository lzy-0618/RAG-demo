# PDF 中文字体渲染问题排查经验

> 排查日期：2026-09-14　|　场景：LibreOffice headless 把 .docx 转 PDF，用于合同/规章制度的预览
> 结论一句话：**LibreOffice 自带的 fontconfig 配置不含系统字体目录，导致它看不到任何系统中文字体，PDF 里中文全部渲染为空白——而文本层却是正确的，用文本提取完全查不出来。**
> 相关设计：`docs/合同模板导入与合同生成实现思路.md` 第 4.1 节

---

## 1. 现象：一个会被误判为「成功」的失败

用 `soffice --headless --convert-to pdf` 转换一份中文合同：

- 命令**退出码 0**，无报错；
- PDF **正常产出**，文件大小正常（19KB）；
- **文本层完全正确**——用 PyMuPDF 提取，能把「甲方（采购方）：某钢股份有限公司」一字不差地读出来，可搜索、可复制。

但如果把 PDF 渲染成图片看一眼，**第一行往后所有中文都是空白的**，页面上只剩数字和英文（`Q235B 3.0mm`、`500`、`2,350,000`、`2026-10-15`）。

这就是这个 bug 最阴险的地方：**任何基于"文本能不能提取出来"的检查都会判定它正常**。如果预览功能按"文件生成了就算成功"来实现，前端会把一份空白合同展示给用户，而日志里没有任何异常。合同场景下这等于把错误直接送到用户面前。

---

## 2. 定位：用受控实验缩小范围

不猜，直接做实验。用同一段中文（`中文测试 Chinese <字体名>`）生成三份只差字体声明的 .docx，分别转换，再看每份 PDF 里**实际生效的字体**：

| 文档声明的字体 | PDF 中实际使用的字体 | 结果 |
| --- | --- | --- |
| `Liberation Serif`（LibreOffice 自带） | `LiberationSerif` | ✅ 正常 |
| `Helvetica`（macOS 系统字体） | `LinuxLibertineG` | ❌ 被顶替 |
| `Songti SC`（macOS 系统中文字体） | `LinuxLibertineG` | ❌ 被顶替 |

一张表就把范围锁死了：**连 `Helvetica` 这种必然存在的系统字体都用不上**，说明不是"某个中文字体缺失"，而是**这个 LibreOffice 看不到任何系统字体，只认它自带的几个字体**。

查看实际生效字体用的是 PyMuPDF 的 span 级信息：

```python
import pymupdf
doc = pymupdf.open("out.pdf")
for block in doc[0].get_text("dict")["blocks"]:
    for line in block.get("lines", []):
        for span in line["spans"]:
            print(span["font"], "|", span["text"][:40])
```

而 LibreOffice 自带的 Linux Libertine / Caladea / FrankRuhlHofshi **全部没有中日韩字形**，于是中文渲染为空白。

### 根因

LibreOffice 使用**自带的 fontconfig 配置**来枚举字体，而该配置里没有 macOS 的字体目录。运行日志里的这几行是直接佐证（当时被忽略了）：

```
Fontconfig warning: adding <cachedir prefix="xdg">fontconfig</cachedir>
Fontconfig warning: no <cachedir> elements found. Check configuration.
```

### 已排除的干扰项

排查过程中逐一验证并排除了三个"看起来很像原因"的方向，避免走弯路：

| 猜测 | 验证方式 | 结果 |
| --- | --- | --- |
| 沙箱/权限阻断了 CoreText 访问 | 用非沙箱方式重跑同一转换 | ❌ 同样复现，不是权限问题 |
| `com.apple.quarantine` 隔离标记限制资源访问 | `xattr -dr com.apple.quarantine` 后重测 | ❌ 无效（去隔离仍是好习惯，但不是原因） |
| 原文档没显式声明字体 | 检查 `rFonts`，发现走的是主题字体 | ❌ 不是必要条件，显式声明 `Songti SC` 一样中招 |

---

## 3. 解决：显式提供 fontconfig 配置

给 LibreOffice 指定一份包含系统字体目录的配置，通过 `FONTCONFIG_FILE` 环境变量传入：

```xml
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>/System/Library/Fonts</dir>
  <dir>/System/Library/Fonts/Supplemental</dir>
  <dir>/Library/Fonts</dir>
  <dir>~/Library/Fonts</dir>
  <cachedir>/tmp/lo-fc-cache</cachedir>
</fontconfig>
```

改完后同一个文件重新转换，字体变成 `STSongti-SC-Regular` / `HiraginoSans-W7` / `ArialUnicodeMS`，中文与版式全部正常。

```bash
FONTCONFIG_FILE=/path/to/fonts.conf soffice --headless \
  -env:UserInstallation=file:///tmp/lo-profile \
  --convert-to pdf --outdir /tmp/out input.docx
```

**关键点**：不要把字体目录硬编码。macOS 用上面的系统目录，Linux 容器里要换成 `/usr/share/fonts` 并安装中文字体包（如 `fonts-noto-cjk`），所以字体目录必须是可配置项。

---

## 4. 验证：怎么证明"字形真的在"

因为文本层不可信，验证必须落到**像素**上。做法是：找出所有含中文的 span，取它们的 bbox，把 bbox 映射到渲染后的灰度位图上，统计墨迹（暗像素）比例。

```python
import pymupdf

def cjk_ink_ratio(pdf_path, dpi=100, dark=200):
    """返回 (含中文的 span 数, 采样面积, 墨迹比例)。"""
    doc = pymupdf.open(pdf_path)
    total_area = total_ink = cjk_spans = 0
    for page in doc:
        rects = [s["bbox"] for b in page.get_text("dict")["blocks"]
                 for l in b.get("lines", []) for s in l["spans"]
                 if any('\u4e00' <= ch <= '\u9fff' for ch in s["text"])]
        if not rects:
            continue
        cjk_spans += len(rects)
        scale = dpi / 72.0
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        buf, w, h = pix.samples, pix.width, pix.height
        for x0, y0, x1, y1 in rects:
            for y in range(max(0, int(y0 * scale)), min(h, int(y1 * scale) + 1)):
                row = y * w
                for x in range(max(0, int(x0 * scale)), min(w, int(x1 * scale) + 1)):
                    total_area += 1
                    if buf[row + x] < dark:
                        total_ink += 1
    return cjk_spans, total_area, (total_ink / total_area if total_area else 0.0)
```

实测判别效果（阈值取 0.5%）：

| 样本 | 含中文 span | 采样面积 | 墨迹比例 | 判定 |
| --- | --- | --- | --- | --- |
| 坏件（无 fontconfig） | 14 | 22601 | **0.10%** | 失败 |
| 好件（带 fontconfig） | 52 | 39976 | **31.90%** | 通过 |

两者相差两个数量级，阈值取 `0.5%` 是非常安全的分离点。这个方法比"检查 PDF 里有没有中文字体名"更可靠，因为它不依赖字体命名，直接验证"用户到底看不看得见"。

---

## 5. 顺带发现的两个性能/稳定性结论

排查中用 `soffice` 的 `-env:UserInstallation` 参数做了对比实验，两个结论直接决定了转换服务的实现方式：

| 策略 | 单次耗时 | 说明 |
| --- | --- | --- |
| 每次调用新建临时 profile | ~2.5 秒 | 每次都要重建字体缓存 |
| 复用固定 profile | **~0.74 秒** | 字体缓存可复用，快 3 倍以上 |

但复用 profile 有前提：**多个 soffice 进程共用同一个 profile 会因锁冲突而失败**。因此正确做法是「**每进程一个独立 profile 目录 + 进程内信号量串行化**」——profile 目录名带上进程 PID（多 worker 场景下互不干扰），进程内同一时刻只跑一个转换。这样既拿到复用的性能，又避开锁冲突。

---

## 6. 落地实现时又踩到的三个坑

把排查结论写成 `backend/app/services/docx_convert.py` 的过程中，同类症状又出现了三次，成因各不相同。这三个坑都值得记住，因为**症状几乎一样**（中文消失或错位），但修法完全不同。

### 6.1 相对路径的 `<cachedir>` 会让整份 fontconfig 静默失效

第一版转换服务用 `Path("var/pdf-cache")` 这种相对路径拼 fonts.conf，写出的是：

```xml
<fontconfig>
  <dir>/System/Library/Fonts</dir>          <!-- 绝对，正确 -->
  <cachedir>var/pdf-cache/fontconfig-cache</cachedir>  <!-- 相对，致命 -->
</fontconfig>
```

结果是：**字体目录明明写对了，中文照样全丢**。和"完全没配 fontconfig"的症状一模一样，日志里没有任何报错。改成绝对路径后立刻恢复。

> **结论：fonts.conf 里的 `<dir>` 与 `<cachedir>` 一律写绝对路径**（用 `Path(...).resolve()`）。这条被自检抓住了——如果只信"转换命令成功"，这个 bug 会一路带到线上。

### 6.2 pdf.js 会把 LibreOffice 导出的中文渲染成 ASCII 字形

PDF 生成正确（MuPDF 渲染完全正常，中文、字体、版式都对），但把同一份 PDF 交给浏览器里的 **pdf.js** 渲染，中文变成了错位的符号：

```
第一条 采购标的：热轧卷板 Q235B 3.0mm，数量 500 吨。
→ 第一条 采购标的：热轧卷板 Q235B 3.0mm  ! " 500 # $
```

`数`→`!`、`量`→`"`、`吨`→`#`、`。`→`$`，全是连续的低位 ASCII 码。这是 CID 子集字体**字形索引映射错位**的典型特征：pdf.js 没能正确解析 LibreOffice 导出的 CID→GID 映射，于是退化成把字符码当字形索引用。

尝试过的方向（都没解决）：把预览副本的字体统一改写为 TrueType 轮廓（排除了 CFF 轮廓的因素）、强制 PDF/A、检查 `/ToUnicode`——pdf.js 依然错位。**注意 pdf.js 全程没有任何 warning**，属于静默错误。

> **结论：预览不走前端 pdf.js，改为后端光栅化。** 用 PyMuPDF 把 PDF 每页渲染成 PNG（`page.get_pixmap(dpi=110)`），前端只展示 `<img>`。代价是预览里不能选中文字，换来的是跨平台稳定的中文渲染；顺带还去掉了 1.3MB 的 pdfjs 前端包。PDF 本身仍然生成，留作下载用途。

### 6.3 复用 profile 的字体缓存会保留旧的字体替换结果

排查 6.2 时曾把预览副本的字体统一改成 `Songti SC`，转换出来却仍是拉丁字体（`LinuxLibertineG`）。原因不是配置错，而是**复用的 LibreOffice profile 里缓存了上一版 fontconfig 的字体解析结果**——同样的配置配一个全新 profile 立刻正常。

> **结论：profile 目录名要带上 fontconfig 的指纹（如内容哈希）**，配置变了就换新 profile，避免"改了配置不生效"这种最耗时的假象。

---

## 7. 可复用的经验清单

1. **"命令成功"不等于"结果可用"**。文档转换、渲染这类任务的退出码只说明进程没崩，不说明产出物是对的。凡是产出物要给人看的环节，都要对产出物本身做断言，而不是对过程做断言。
2. **文本层正常不能证明字形存在**。PDF 的文本层与字形是两回事，字体缺失时文本层照旧正确。要做"内容是否可见"的验证，必须落到渲染像素上。
3. **受控实验比猜测快得多**。同一段内容 + 单一变量（字体）做成矩阵，一次就能把"是不是某个字体缺失"和"是不是完全看不到系统字体"区分开。
4. **不要忽略运行时日志里的 warning**。那几行 `Fontconfig warning` 从一开始就在输出，如果早看一眼，能省掉一大半排查时间。
5. **外部工具依赖系统资源时，资源可见性必须显式配置**。不能假设 headless 的工具能像桌面环境一样拿到系统字体。字体目录、缓存目录这些都应该做成配置项，并在部署到容器时重新确认。
6. **给失败留一个"看得见"的出口**。这次自检失败时应该抛出明确的错误（提示字体未配置），而不是静默返回一份空白 PDF。
7. **配置文件的路径一律绝对化**。相对路径在不同工作目录、不同调用方下含义不同，而这类工具往往**静默降级**而不是报错（见 6.1）。
8. **"生产端正确"不等于"消费端正确"**。同一份 PDF，MuPDF 渲染正常、pdf.js 渲染错位。产出端自检只能证明产物本身没问题，**任何跨渲染器的展示路径都要在真实渲染器里验证一次**（见 6.2）。
9. **缓存要让配置变更失效**。字体缓存、转换结果、profile 都可能把旧配置的结果固化下来，键里必须包含配置指纹，否则"改了不生效"会伪装成"改错了"（见 6.3）。
