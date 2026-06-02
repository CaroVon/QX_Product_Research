"""
============================================================
横版 PPT 风格 PDF 生成器 —— 基于 WeasyPrint 高级 CSS 排版
============================================================

将 Markdown 分析报告转化为 16:9 横版路演级 PDF:
  - 真正 16:9 横版页面 (320mm × 180mm，比例 1.778:1)
  - 杂志级沉浸式封面 (全屏概念图 + 暗色遮罩)
  - 🆕 CSS 高级渐变兜底封面（生图失败时自动启用）
  - PPT 大字号排版体系 (正文 ≥ 14pt)
  - 强制单页单主题 (h2 → page-break-before)
  - 页眉章节导航 + 页脚页码（滑动编号）
  - 纯 Block 布局，完全杜绝 flex/grid
  - 商业汇报标准：合理留白、清晰层级、专业配色
"""

import os
import re
import markdown2
from weasyprint import HTML


# ══════════════════════════════════════════════════════════
# 品牌色彩系统 (苹果极简白 + 深空灰 + 科技亮蓝)
# ══════════════════════════════════════════════════════════
COLOR = {
    "bg_dark":     "#0f1117",   # 深空灰封面背景
    "bg_body":     "#f5f6f8",   # 正文页极淡灰白底
    "overlay":     "rgba(0, 0, 0, 0.55)",  # 封面暗色遮罩
    "accent":      "#2d7cf6",   # 科技亮蓝 (点缀色)
    "accent_dim":  "#1a5dc4",   # 深蓝 (页眉分割线)
    "h2_color":    "#1a1f2e",   # 标题深色
    "body_text":   "#2c3038",   # 正文色
    "muted":       "#8899bb",   # 次要文字
    "divider":     "#dce3ed",   # 细分割线
    "white":       "#ffffff",
    "header_bg":   "#0d1117",   # 页眉深色条 (正文页)
}


# ══════════════════════════════════════════════════════════
# Helper：将 topic 安全化为文件名 / 标题片段
# ══════════════════════════════════════════════════════════
def _safe_topic(topic: str) -> str:
    """移除文件名非法字符，用于图片路径拼接。"""
    return re.sub(r'[\\/:*?"<>|]', '_', topic)


# ══════════════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════════════
def markdown_to_pdf(md_path: str, pdf_path: str, cover_image: str = ""):
    """
    将 Markdown 分析报告渲染为横版 PPT 风格 PDF。

    Args:
        md_path:      Markdown 文件路径
        pdf_path:     PDF 输出路径
        cover_image:  (可选) 封面概念图的绝对/相对路径。
                      若文件存在则用于封面全屏背景，
                      🆕 若不存在则使用 CSS 高级渐变兜底。
    """
    print(f"[PPT PDF] 横版路演级 PDF 渲染启动...")

    # ── 1. 读取 Markdown ──────────────────────────────────
    with open(md_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    # ── 2. 提取标题 + 清洗 ────────────────────────────────
    title_match = re.search(r"^#\s+(.+)", md_content, re.MULTILINE)
    report_title = title_match.group(1).strip() if title_match else "行业深度研究报告"

    # 移除 H1 (封面已承载)，保留正文用于幻灯片内容
    clean_md = re.sub(r"^#\s+.+", "", md_content, count=1).strip()

    # ── 3. Markdown → HTML ────────────────────────────────
    html_body = markdown2.markdown(
        clean_md,
        extras=["tables", "fenced-code-blocks", "footnotes", "strike"],
    )

    # ── 4. 封面图逻辑 ─────────────────────────────────────
    # 检测 cover_image 是否存在，不存在则回退 CSS 渐变封面
    has_cover_bg = bool(cover_image) and os.path.isfile(cover_image)
    if has_cover_bg:
        abs_img = os.path.abspath(cover_image).replace("\\", "/")
        print(f"[PPT PDF] 封面背景图: {abs_img}")
    else:
        if cover_image:
            print(f"[PPT PDF] 封面图未找到 ({cover_image})，使用 CSS 渐变兜底")
        else:
            print(f"[PPT PDF] 未提供封面图，使用 CSS 高级渐变兜底封面")

    # ── 5. 构建 PPT 风格 HTML + CSS ───────────────────────
    premium_html = _build_html(report_title, html_body, has_cover_bg, cover_image)

    # ── 6. 写入临时 HTML → WeasyPrint → PDF ───────────────
    temp_html_path = md_path.replace(".md", ".html")
    with open(temp_html_path, "w", encoding="utf-8") as f:
        f.write(premium_html)

    HTML(filename=temp_html_path).write_pdf(pdf_path)
    print(f"[PPT PDF ✓] 横版路演 PDF 已生成: {pdf_path}")


# ══════════════════════════════════════════════════════════
# HTML 骨架 + 完整 CSS 构建
# ══════════════════════════════════════════════════════════
def _build_html(
    title: str, body_html: str, has_bg: bool, img_path: str
) -> str:
    """
    组装完整的 HTML 文档（封面 .cover + 正文 .slide-deck）。
    所有 CSS 规则遵循 WeasyPrint 兼容的 Block 布局范式。
    """

    cover_html = _build_cover(title, has_bg, img_path)

    # 移除 body_html 中可能残留的第一个 h1 (避免与封面重复)
    body_html = re.sub(r"<h1[^>]*>.*?</h1>", "", body_html, count=1, flags=re.DOTALL)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
    /* ========================================================
    【页面基础】—— 真正 16:9 横版 = 320mm × 180mm
    比例 1.778:1，完美适配现代宽屏显示器和投影
    ======================================================== */
    @page {{
        size: 320mm 180mm;
        margin: 0 16mm 10mm 16mm;
        background-color: {COLOR["bg_body"]};

        @top-left {{
            content: string(chapter);
            font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif;
            font-size: 8pt;
            font-weight: 600;
            color: {COLOR["accent"]};
            letter-spacing: 1.5px;
            text-transform: uppercase;
            padding-left: 2mm;
        }}
        @top-right {{
            content: "产品深度研究 · 路演方案";
            font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif;
            font-size: 7pt;
            color: {COLOR["muted"]};
            letter-spacing: 1px;
            padding-right: 2mm;
        }}
        @top-center {{
            content: "";
            border-bottom: 0.6px solid {COLOR["accent"]};
            width: 100%;
        }}

        @bottom-left {{
            content: counter(page) " /";
            font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
            font-size: 8pt;
            color: {COLOR["muted"]};
            padding-top: 4mm;
        }}
        @bottom-right {{
            content: "CONFIDENTIAL · 产品前沿战略研究院";
            font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
            font-size: 7pt;
            color: {COLOR["muted"]};
            letter-spacing: 0.5px;
            padding-top: 4mm;
        }}
    }}

    /*
     * 封面页特殊规则：移除页眉页脚，铺满整页
     */
    @page cover {{
        size: 320mm 180mm;
        background-color: {COLOR["bg_dark"]};
        margin: 0;
        @top-left   {{ content: none; }}
        @top-right  {{ content: none; }}
        @top-center {{ content: none; border-bottom: none; }}
        @bottom-left  {{ content: none; }}
        @bottom-right {{ content: none; }}
    }}

    /* ========================================================
    【全局重置】—— 保证跨平台字体一致性
    ======================================================== */
    *, *::before, *::after {{ box-sizing: border-box; }}

    body {{
        font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC',
                     'WenQuanYi Zen Hei', 'Helvetica Neue', sans-serif;
        color: {COLOR["body_text"]};
        line-height: 1.85;
        font-size: 14pt;
        margin: 0;
        padding: 0;
    }}

    /* ========================================================
    【封面】—— 杂志级沉浸式开屏
    ======================================================== */
    .cover {{
        display: block;
        position: relative;
        width: 100%;
        height: 180mm;
        page: cover;
        page-break-after: always;
        overflow: hidden;
        color: {COLOR["white"]};
    }}

    .cover-bg-img {{
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        z-index: 0;
        object-fit: cover;
    }}

    .cover-overlay {{
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        z-index: 1;
        background-color: {COLOR["overlay"]};
    }}

    /*
     * CSS 科技感渐变兜底封面
     */
    .cover-gradient-bg {{
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        z-index: 0;
        background:
            linear-gradient(135deg, #0d1117 0%, #0f1a2e 30%, #0d1525 60%, #0a0e14 100%);
    }}

    .cover-content {{
        position: relative;
        z-index: 2;
        padding: 24mm 28mm 0 28mm;
        height: 100%;
    }}

    .cover-tag {{
        display: inline-block;
        font-size: 9pt;
        font-weight: 500;
        letter-spacing: 3px;
        text-transform: uppercase;
        color: {COLOR["accent"]};
        border: 1.2px solid {COLOR["accent"]};
        padding: 4px 12px;
        margin-bottom: 14mm;
    }}

    .cover-title {{
        font-size: 34pt;
        font-weight: 700;
        line-height: 1.2;
        color: {COLOR["white"]};
        margin-bottom: 6mm;
        letter-spacing: 2px;
    }}

    .cover-divider {{
        width: 45mm;
        height: 4px;
        background-color: {COLOR["accent"]};
        margin-bottom: 10mm;
    }}

    .cover-subtitle {{
        font-size: 14pt;
        color: #bcc8e0;
        letter-spacing: 1px;
        margin-bottom: 2mm;
    }}

    .cover-footer {{
        position: absolute;
        bottom: 14mm;
        left: 28mm;
        font-size: 9pt;
        color: {COLOR["muted"]};
        line-height: 2;
        z-index: 2;
    }}

    /* ========================================================
    【正文幻灯片区域】—— slide-deck
    每张 "幻灯片" = 一个 h2 章节块，强制分页
    ======================================================== */
    .slide-deck {{
        display: block;
        padding-top: 4mm;
        max-width: 100%;
    }}

    /*
     * h2 核心规则：强制 page-break-before → 每个章节从新页开始。
     * 这是实现 "PPT 翻页感" 的关键。
     */
    h2 {{
        font-size: 20pt;
        font-weight: 700;
        color: {COLOR["h2_color"]};
        font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif;
        border-left: 5px solid {COLOR["accent"]};
        padding-left: 12px;
        margin-top: 0;
        margin-bottom: 16pt;
        line-height: 1.35;
        string-set: chapter self;
        page-break-before: always;
        page-break-inside: avoid;
        page-break-after: avoid;
    }}

    h3 {{
        font-size: 16pt;
        font-weight: 600;
        color: {COLOR["h2_color"]};
        margin-top: 20pt;
        margin-bottom: 12pt;
        page-break-inside: avoid;
        page-break-after: avoid;
    }}

    h4 {{
        font-size: 14.5pt;
        font-weight: 600;
        color: {COLOR["body_text"]};
        margin-top: 16pt;
        margin-bottom: 10pt;
    }}

    p {{
        margin-top: 0;
        margin-bottom: 14pt;
        text-align: justify;
        text-indent: 0;
        orphans: 3;
        widows: 3;
    }}

    ul, ol {{
        margin-top: 8pt;
        margin-bottom: 16pt;
        padding-left: 22pt;
    }}

    li {{
        margin-bottom: 8pt;
        font-size: 14pt;
        line-height: 1.75;
    }}

    blockquote {{
        display: block;
        margin: 20pt 0;
        padding: 14pt 18pt;
        background-color: {COLOR["white"]};
        border-left: 4px solid {COLOR["accent"]};
        border-radius: 0 4px 4px 0;
        color: {COLOR["body_text"]};
        font-size: 13.5pt;
        line-height: 1.75;
        page-break-inside: avoid;
    }}

    img {{
        max-width: 85%;
        display: block;
        margin: 20pt auto;
        border-radius: 6px;
        border: 0.5px solid {COLOR["divider"]};
        box-shadow: 0 6px 20px rgba(0, 0, 0, 0.06);
        page-break-inside: avoid;
    }}

    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 18pt 0;
        font-size: 12pt;
        page-break-inside: avoid;
    }}
    th {{
        background-color: {COLOR["header_bg"]};
        color: {COLOR["white"]};
        padding: 8pt 10pt;
        font-weight: 600;
        text-align: left;
        font-size: 11pt;
    }}
    td {{
        padding: 7pt 10pt;
        border-bottom: 0.5px solid {COLOR["divider"]};
        background-color: {COLOR["white"]};
    }}

    pre {{
        background-color: #1e2233;
        color: #c8d6e5;
        padding: 14pt 16pt;
        border-radius: 4px;
        font-size: 10pt;
        line-height: 1.6;
        overflow-x: auto;
        page-break-inside: avoid;
    }}
    code {{
        font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
        font-size: 9.5pt;
    }}

    .footnotes {{
        margin-top: 40pt;
        border-top: 1px dashed {COLOR["muted"]};
        padding-top: 14pt;
        font-size: 10pt;
        color: {COLOR["muted"]};
    }}

    hr {{
        border: none;
        height: 1px;
        background-color: {COLOR["divider"]};
        margin: 24pt 0;
    }}
</style>
</head>
<body>

    {cover_html}

    <div class="slide-deck">
        {body_html}
    </div>

</body>
</html>"""


# ══════════════════════════════════════════════════════════
# 封面 HTML 构建
# ══════════════════════════════════════════════════════════
def _build_cover(title: str, has_bg: bool, img_path: str) -> str:
    """
    构建杂志级封面 HTML 片段。
    - 有背景图时：全屏图 + 暗色遮罩 + 白色文字
    - 无背景图时：CSS 高级渐变 + 暗色遮罩 + 白色文字
    """

    if has_bg:
        abs_img = os.path.abspath(img_path).replace("\\", "/")
        bg_html = (
            f'<img class="cover-bg-img" src="file:///{abs_img}" '
            f'alt="封面概念图">'
        )
        overlay_html = '<div class="cover-overlay"></div>'
    else:
        # 🆕 CSS 渐变兜底：深空灰 + 亮蓝光晕 + 紫色点缀
        bg_html = '<div class="cover-gradient-bg"></div>'
        overlay_html = '<div class="cover-overlay"></div>'

    return f"""
    <div class="cover">
        {bg_html}
        {overlay_html}
        <div class="cover-content">
            <div class="cover-tag">PRODUCT DEEP RESEARCH</div>
            <div class="cover-title">{title}</div>
            <div class="cover-divider"></div>
            <div class="cover-subtitle">产品深度研究路演方案</div>
        </div>
        <div class="cover-footer">
            <strong>出品机构</strong>&nbsp; 产品前沿战略研究院<br>
            <strong>核心引擎</strong>&nbsp; 硅基流动 FLUX.1 多模态视觉管道<br>
            <strong>数据溯源</strong>&nbsp; 混合 RAG 多向并发权威检索链路
        </div>
    </div>"""


# ══════════════════════════════════════════════════════════
# CLI 调试入口
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3:
        md_in = sys.argv[1]
        pdf_out = sys.argv[2]
        img = sys.argv[3] if len(sys.argv) > 3 else ""
    else:
        md_in = "outputs/AI眼镜行业_report.md"
        pdf_out = "outputs/AI眼镜行业_report_ppt.pdf"
        img = ""

    markdown_to_pdf(md_in, pdf_out, cover_image=img)
