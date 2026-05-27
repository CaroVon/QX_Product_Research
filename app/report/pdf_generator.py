import os
import re
import markdown2
from weasyprint import HTML

def markdown_to_pdf(md_path: str, pdf_path: str):
    """
    升级为印刷级两阶段 HTML-to-PDF 工作流（全面抛弃低颜值、难排版的 ReportLab）。
    严格遵循 WeasyPrint 规范：全页面背景满铺、完全杜绝 display:flex/grid、采用绝对定位与经典表格。
    """
    print(f"[🎨 印刷级渲染] 正在解析 {md_path} 并调用 WeasyPrint 转化高阶研报 PDF...")
    
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
        
    # 提取第一个 H1 标题作为封面大标题
    title_match = re.search(r'^#\s+(.+)', md_content, re.MULTILINE)
    report_title = title_match.group(1).strip() if title_match else "行业深度研究报告"
    
    # 移除原始代码中的大标题，避免在内容页重复呈现
    clean_md = re.sub(r'^#\s+.+', '', md_content, count=1)
    
    # 转换为标准的富文本 HTML
    html_body = markdown2.markdown(clean_md, extras=['tables', 'fenced-code-blocks', 'footnotes'])
    
    # 注入符合顶级咨询机构（麦肯锡/罗兰贝格）视觉水准的精美 CSS 样式
    premium_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        /* 页面整体视效与边距规范 */
        @page {{
            size: A4;
            margin: 30mm 20mm 25mm 20mm;
            background-color: #fafbfc; /* 优雅微米白底色，规避刺眼纯白 */
            @top-center {{
                content: "行业前沿深度洞察与产品设计报告";
                font-family: 'Noto Sans CJK SC', 'WenQuanYi Zen Hei', 'PingFang SC', 'Microsoft YaHei', sans-serif;
                font-size: 8.5pt;
                color: #718096;
                border-bottom: 0.5px solid #e2e8f0;
                padding-bottom: 4mm;
                margin-bottom: 10mm;
                width: 100%;
            }}
            @bottom-right {{
                content: "第 " counter(page) " 页";
                font-family: 'Noto Sans CJK SC', 'WenQuanYi Zen Hei', 'PingFang SC', sans-serif;
                font-size: 9pt;
                color: #a0aec0;
            }}
        }}
        
        /* 针对首张封面页的定制化覆盖（背景颜色自动填充整页包括页边距，移除 margin:0 以保持流布局） */
        @page :first {{
            background-color: #1a2238; /* 奢华古典深蓝 */
            @top-center {{ content: normal; border-bottom: none; }}
            @bottom-right {{ content: normal; }}
        }}
        
        *, *::before, *::after {{ box-sizing: border-box; }}
        
        body {{
            font-family: 'Times New Roman', 'Noto Sans CJK SC', 'WenQuanYi Zen Hei', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            color: #2d3748;
            line-height: 1.7;
            font-size: 10.5pt;
            margin: 0;
            padding: 0;
        }}
        
        /* 封面区域布局 (改为正常块级流，配合 page-break-after 绝对防止重叠) */
        .cover {{
            display: block;
            height: 242mm; /* A4 总高 297mm - 上边距 30mm - 下边距 25mm = 242mm 刚好填满第一页内容区 */
            padding-top: 30mm;
            color: #ffffff;
            page-break-after: always; /* 核心：指示 WeasyPrint 在此块后强制换页 */
            position: relative;
        }}
        
        .cover-tag {{
            display: inline-block;
            font-size: 9pt;
            text-transform: uppercase;
            letter-spacing: 2px;
            color: #60a5fa;
            border: 1px solid #60a5fa;
            padding: 3px 8px;
            margin-bottom: 12mm;
        }}
        
        .cover-title {{
            font-size: 32pt;
            font-weight: bold;
            line-height: 1.25;
            color: #ffffff;
            margin-bottom: 8mm;
            font-family: 'Noto Sans CJK SC', 'WenQuanYi Zen Hei', 'PingFang SC', sans-serif;
        }}
        
        .cover-divider {{
            width: 30mm;
            height: 4px;
            background-color: #3b82f6;
            margin-bottom: 10mm;
        }}
        
        .cover-subtitle {{
            font-size: 14pt;
            color: #9ca3af;
        }}
        
        .cover-footer {{
            position: absolute;
            bottom: 10mm; /* 由于取消了绝对定位，这里的 bottom 是相对于 .cover 底部 */
            left: 0;
            font-size: 10pt;
            color: #9ca3af;
            line-height: 2;
        }}
        
        /* 报告正文精美样式 */
        .report-content {{
            padding-top: 5mm;
        }}
        
        h2 {{
            font-size: 15pt;
            color: #1e3a8a;
            font-family: 'Noto Sans CJK SC', 'WenQuanYi Zen Hei', 'PingFang SC', sans-serif;
            border-left: 4.5px solid #3b82f6;
            padding-left: 10px;
            margin-top: 28pt;
            margin-bottom: 14pt;
            page-break-inside: avoid;
            page-break-after: avoid; /* 杜绝标题变成孤行落页尾 */
        }}
        
        p {{
            margin-top: 0;
            margin-bottom: 12pt;
            text-align: justify;
            text-indent: 21pt; /* 完美的中文首行双字符缩进 */
        }}
        
        /* 强力插入的工业设计图鉴样式 */
        img {{
            max-width: 90%;
            display: block;
            margin: 25pt auto;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
            box-shadow: 0 10px 25px rgba(0,0,0,0.05);
        }}
        
        blockquote {{
            margin: 18pt 0;
            padding: 12pt 18pt;
            background-color: #f1f5f9;
            border-left: 4px solid #475569;
            color: #334155;
            border-radius: 0 6px 6px 0;
            page-break-inside: avoid;
        }}
        
        ul, ol {{
            margin-bottom: 12pt;
            padding-left: 20pt;
        }}
        
        li {{
            margin-bottom: 4pt;
        }}
        
        /* 严炼级角标脚注展现 */
        .footnotes {{
            margin-top: 45pt;
            border-top: 1px dashed #cbd5e1;
            padding-top: 15pt;
            font-size: 9.5pt;
            color: #64748b;
        }}
    </style>
</head>
<body>
    <div class="cover">
        <div class="cover-tag">INTELLIGENT REPORT</div>
        <div class="cover-title">{report_title}</div>
        <div class="cover-divider"></div>
        <div class="cover-subtitle">深度产品行研与视觉概念设计方案书</div>
        
        <div class="cover-footer">
            <strong>出品机构：</strong> 智能产品前沿战略研究院<br>
            <strong>核心引擎：</strong> 智谱/硅基大模型多模态全流程管道<br>
            <strong>数据溯源：</strong> 混合 RAG 多向并发权威链路
        </div>
    </div>
    
    <div class="report-content">
        {html_body}
    </div>
</body>
</html>
"""
    
    # 写入临时 HTML 进行媒介转换
    temp_html_path = md_path.replace(".md", ".html")
    with open(temp_html_path, 'w', encoding='utf-8') as f:
        f.write(premium_html)
        
    # 调用 WeasyPrint 进行完美转换
    HTML(filename=temp_html_path).write_pdf(pdf_path)
    print(f"[OK] Premium Printed PDF successfully created at: {pdf_path}")