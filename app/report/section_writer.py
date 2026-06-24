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
from app.llm.prompts import PromptFactory
from app.rag.retriever import retrieve
from app.rag.citation_utils import build_context_with_citations, resolve_and_append_citations

logger = logging.getLogger(__name__)


def _safe_topic(topic: str) -> str:
    """移除文件名非法字符，确保与 workflow.py 路径一致。"""
    return re.sub(r'[\\/:*?"<>|]', '_', topic)




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
    template_type: str = "product",
    search_depth: int = 10,
) -> str:
    llm = get_llm()
    logger.info("→ [📝 文本撰写] 正在深度撰写章节【%s】(template=%s, k=%d)...", section_title, template_type, search_depth)

    retriever_k = max(5, search_depth)  # 最少获取 5 篇
    docs = retrieve(f"{topic} {section_title}", k=retriever_k, project_id=project_id)
    context_str, ref_map = build_context_with_citations(docs)

    sys_prompt = PromptFactory.get_section_prompt(template_type)

    prompt = f"""{sys_prompt}

【产品研究主题】: {topic}
【当前撰写章节】: {section_title}

【参考资料】:
{context_str}

请直接输出 Markdown 内容，务必从 `## {section_title}` 开始，不要有任何前缀。

【格式严控要求（为 PPT 排版优化）】：
1. 必须使用 Markdown 格式。
2. 严禁长篇大论！每个段落不得超过 3 行（约 80 字），多用 Bullet points (无序列表 - ) 进行观点拆解。
3. 如有数据对比，强制使用 Markdown 表格输出。
4. 你的输出将直接转化为幻灯片，请保持内容的高度概括性和排版呼吸感。
5. 【最高优先级：数据表格规范】如果涉及到对比数据，必须使用标准 Markdown 表格语法（使用 `|` 分隔）。
绝不允许使用逗号分隔的 CSV 格式！
绝不允许使用引号 `" "` 包围单元格内容！
绝不允许输出 "The following table:" 这类前缀废话！
示例格式：
| 品牌型号 | 核心技术 | 价格 |
| :--- | :--- | :--- |
| 产品A | 追腰技术 | 1000元 |"""

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
    template_type: str = "product",
    search_depth: int = 10,
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
        template_type: 模板类型（"product" 或 "design"），
                       透传给 PromptFactory 选择对应的 System Prompt
        search_depth:  搜索强度 (5-20)，控制检索资料数量

    Returns:
        Markdown 格式的章节内容。
    """
    if _is_image_section(section_title):
        return _write_image_section(topic, section_title)
    else:
        return _write_text_section(
            topic, section_title,
            project_id=project_id,
            template_type=template_type,
            search_depth=search_depth,
        )
