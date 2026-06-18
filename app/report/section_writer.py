"""
============================================================
产品研究报告章节撰写器
—— 人设：资深产品经理 / 工业设计师 / 用户体验专家
   严格保留脚注角标引用规则 [^1] 与 Markdown 排版要求
============================================================
"""
import logging
import re

from app.llm.client import get_llm, generate_image
from app.rag.retriever import retrieve
from app.rag.citation_utils import build_context_with_citations, resolve_and_append_citations

logger = logging.getLogger(__name__)


def _safe_topic(topic: str) -> str:
    """移除文件名非法字符，确保与 workflow.py 路径一致。"""
    return re.sub(r'[\\/:*?"<>|]', '_', topic)


# ══════════════════════════════════════════════════════════
# 核心 System Prompt —— 产品研究 Persona
# ══════════════════════════════════════════════════════════
PRODUCT_RESEARCHER_SYSTEM_PROMPT = """你是一名顶级商业咨询顾问。请基于提供的参考资料，为产品路演 PPT 撰写当前章节的 Markdown 内容。

【绝对格式红线】（触发将导致系统崩溃）：
必须 100% 遵守 Markdown 语法，严禁输出任何“好的”、“这是基于...”、“为您撰写”等对话寒暄语或解释性废话。你的输出必须直接以 `## 章节标题` 作为第一个字符！

【排版规则】：
1. 核心洞察置顶：每个章节（## 标题）下方，必须紧跟一个 Markdown 引用块（>），用2-3句话总结本页的核心商业洞察（Executive Summary）。
2. 杜绝长篇大论：不要写超过3行的段落！必须使用大量无序列表（-）或有序列表（1.）来拆解逻辑。
3. 关键信息加粗：使用 **加粗** 突出核心数据和专有名词。
4. 结构化对比：如果涉及多维度对比或BOM成本，强制输出 Markdown 表格。
5. 引用规范：必须使用 [^n] 格式标注数据来源。
"""


# ══════════════════════════════════════════════════════════
# 多模态绘图关键词（用于路由到生图策略）
# ══════════════════════════════════════════════════════════
_IMAGE_SECTION_KEYWORDS = ["生图", "图鉴", "概念图"]


def _is_image_section(section_title: str) -> bool:
    """判断是否为多模态绘图章节。"""
    return any(kw in section_title for kw in _IMAGE_SECTION_KEYWORDS)


def _write_image_section(topic: str, section_title: str) -> str:
    """
    多模态绘图章节——调用硅基流动图像生成模型生成 16:9 概念图。
    失败时输出 graceful degradation 提示。
    """
    safe = _safe_topic(topic)
    llm = get_llm()

    logger.info("→ [🎨 多模态绘图] 正在为章节【%s】生成概念图...", section_title)
    image_relative_path = f"outputs/images/{safe}_concept.png"

    # 让 LLM 生成英文工业设计级 Prompt
    prompt_generator = (
        f"你是一位资深工业设计师。请为主题为 '{topic}' 的前沿科技产品，"
        f"撰写一段用于 AI 文生图模型的英文视觉描述 (Prompt)。\n"
        f"要求：包含材质 (Material)、造型线条 (Form Language)、光影氛围 (Lighting Mood)、"
        f"摄影视角 (Camera Angle)。横版 16:9 构图。\n"
        f"直接输出英文 Prompt，严禁任何多余文字或解释。"
    )
    img_prompt = llm.invoke(prompt_generator).content.strip()

    success = generate_image(img_prompt, image_relative_path)

    if success:
        return (
            f"## {section_title}\n\n"
            f"本章节由多模态工业设计绘图引擎实时渲染生成。"
            f"以下是基于前述产品分析推演出的前沿概念设计：\n\n"
            f"![{topic}概念图](../{image_relative_path})\n\n"
            f"> *图注：由硅基流动 AI 图像引擎以 16:9 横版构图渲染的高精度产品概念图。"
            f"材质、光感与造型均基于前述 CMF 设计语言推演。*\n"
        )
    else:
        return (
            f"## {section_title}\n\n"
            f"[⚠️ 视觉概念图生成失败——请检查硅基流动 API Key 与网络连接。"
            f"如未配置，请在 .env 中设置 SILICONFLOW_API_KEY。]\n"
        )


def _write_text_section(
    topic: str,
    section_title: str,
    project_id: str | None = None,
) -> str:
    llm = get_llm()
    logger.info("→ [📝 文本撰写] 正在深度撰写章节【%s】...", section_title)

    docs = retrieve(f"{topic} {section_title}", k=5, project_id=project_id)
    context_str, ref_map = build_context_with_citations(docs)

    prompt = f"""{PRODUCT_RESEARCHER_SYSTEM_PROMPT}

【产品研究主题】: {topic}
【当前撰写章节】: {section_title}

【参考资料】:
{context_str}

请直接输出 Markdown 内容，务必从 `## {section_title}` 开始，不要有任何前缀。"""

    response = llm.invoke(prompt)
    raw_content = response.content
    
    # 核心修复：硬截断前缀寒暄语
    # 找到第一个 '## ' 的索引，截取从这里开始的所有内容
    match_idx = raw_content.find("##")
    if match_idx != -1:
        raw_content = raw_content[match_idx:]
    else:
        # 如果模型甚至忘了写 ##，我们手动帮它补上并去除首尾空白
        raw_content = f"## {section_title}\n\n" + raw_content.strip()

    final_content = resolve_and_append_citations(raw_content, ref_map)
    return final_content


def write_section(
    topic: str,
    section_title: str,
    project_id: str | None = None,
) -> str:
    """
    撰写单个章节。

    根据章节标题关键词自动路由：
    - 多模态绘图章节 → 图像生成引擎
    - 文本章节 → RAG 检索 + LLM 深度撰写

    Args:
        topic:         产品研究主题
        section_title: 当前章节标题
        project_id:    项目 UUID（用于 per-project 向量库隔离）

    Returns:
        Markdown 格式的章节内容。
    """
    if _is_image_section(section_title):
        return _write_image_section(topic, section_title)
    else:
        return _write_text_section(topic, section_title, project_id=project_id)
