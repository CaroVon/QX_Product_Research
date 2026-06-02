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
PRODUCT_RESEARCHER_SYSTEM_PROMPT = """你是一名在世界顶级科技公司工作超过 15 年的 **资深产品经理 / 工业设计师 / 用户体验研究专家**。
你曾主导过多款获得红点设计奖 (Red Dot) 和 iF 设计奖的消费电子产品从 0 到 1 的全流程。

你的每一次分析都深深根植于：
- 用户真实的行为数据与使用习惯 (UX Research)
- CMF (色彩/材质/表面处理) 工业设计语言
- 人机工程学 (Ergonomics) 与交互直觉
- 供应链可实现性 (DFM) 与成本结构
- 竞品的差异化定位与定价心理学

【撰写铁律 —— 不可违反】
1. **拒绝空洞套话**：禁止出现 "赋能" "抓手" "对齐" "底层逻辑" 等无信息量的词汇。
   每一段话必须包含至少一个具体的、可验证的数据点或设计决策逻辑。
2. **脚注溯源（极其重要）**：如果你所写的一句话参考了【参考资料】中的信息，
   必须在该句句尾（句号之前）插入对应的脚注角标，例如 [^1] 或 [^2][^3]。
   这是学术级严谨度的底线，绝不可省略。
3. **Markdown 排版美学**：
   - 善用 **粗体** 强调关键结论
   - 使用无序列表 (-) 呈现并列要点
   - 每个段落不超过 5 行，保持呼吸感
   - 重要数据单独成段，前后留空行
4. **语气与视角**：始终以第一人称 "我们" 来书写，
   体现这是一支真正在做产品决策的团队。例如："我们选择 6.1 英寸屏幕而非 6.7 英寸，
   是基于单手握持的拇指热区数据..."
5. **产品化输出**：每个章节应读起来像一份产品 PRD (Product Requirement Document)
   中的核心论证段落，而非宏观行业白皮书。聚焦在产品本身的设计、体验、市场定位，
   避免泛泛的宏观趋势描述。"""


# ══════════════════════════════════════════════════════════
# 多模态绘图关键词（用于路由到生图策略）
# ══════════════════════════════════════════════════════════
_IMAGE_SECTION_KEYWORDS = ["生图", "图鉴", "概念图"]


def _is_image_section(section_title: str) -> bool:
    """判断是否为多模态绘图章节。"""
    return any(kw in section_title for kw in _IMAGE_SECTION_KEYWORDS)


def _write_image_section(topic: str, section_title: str) -> str:
    """
    多模态绘图章节——调用硅基流动 FLUX.1 生成 16:9 概念图。
    失败时输出 graceful degradation 提示。
    """
    safe = _safe_topic(topic)
    llm = get_llm()

    logger.info("→ [🎨 多模态绘图] 正在为章节【%s】生成 FLUX.1 概念图...", section_title)
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
            f"> *图注：由硅基流动 FLUX.1 工业设计引擎以 16:9 横版构图渲染的高精度产品概念图。"
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
    """
    文本章节——RAG 检索 + LLM 深度撰写 + 脚注引用解析。
    """
    llm = get_llm()
    logger.info("→ [📝 文本撰写] 正在深度撰写章节【%s】...", section_title)

    docs = retrieve(f"{topic} {section_title}", k=5, project_id=project_id)
    context_str, ref_map = build_context_with_citations(docs)

    prompt = f"""{PRODUCT_RESEARCHER_SYSTEM_PROMPT}

【产品研究主题】: {topic}
【当前撰写章节】: {section_title}

【参考资料（含脚注编号）】:
{context_str}

请以产品经理/工业设计师的视角，完成本章节的深度撰写。
记住：每一个基于参考资料的观点都必须带脚注角标 [^n]，
每一个分析判断都必须有具体的产品设计依据。
直接输出 Markdown 格式的章节内容。"""

    response = llm.invoke(prompt)
    raw_content = response.content
    final_content = resolve_and_append_citations(raw_content, ref_map)

    # 确保章节以 ## 标题开头
    if not final_content.strip().startswith("##"):
        final_content = f"## {section_title}\n\n" + final_content

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
