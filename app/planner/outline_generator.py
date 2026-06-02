"""
============================================================
产品研究大纲生成器 —— 由 LLM 动态生成，聚焦产品本身
============================================================
"""
from app.llm.client import get_llm


PRODUCT_OUTLINE_SYSTEM = """你是一名资深产品战略总监，擅长为新产品立项撰写结构化的产品研究报告大纲。

你的大纲必须聚焦在 **产品本身** 的设计、体验、定位与竞争力上，而非泛泛的宏观行业趋势。
每个章节标题必须以 "## " 开头（Markdown 二级标题）。

大纲应覆盖以下维度（根据具体产品灵活调整顺序和数量，6-8 个章节为宜）：
- 产品定位与用户画像 (Product Positioning & Persona)
- 核心功能与交互设计 (Core Features & Interaction Design)
- CMF 设计语言分析 (Color / Material / Finishing)
- 竞品深度拆解 (Competitive Teardown)
- 技术架构与可实现性 (Technical Feasibility & DFM)
- 定价策略与商业模式 (Pricing & Business Model)
- 产品概念图鉴 (可选，用于 AI 绘图章节)
- 使用场景与用户体验旅程 (Usage Scenarios & UX Journey)

要求：直接输出 Markdown 格式的大纲，以 "# <产品名>" 开头，
后跟 "## X. 章节名" 的列表。不要输出任何解释性文字。"""


def generate_outline(topic: str) -> str:
    """
    调用 LLM 为给定的产品主题动态生成研究大纲。
    取代原有的固定 6 大章节模板。
    """
    llm = get_llm()

    user_prompt = f"请为产品「{topic}」生成一份产品研究报告大纲。\n\n要求：7-8 个章节，聚焦产品设计、用户体验与竞争定位。"

    response = llm.invoke([
        {"role": "system", "content": PRODUCT_OUTLINE_SYSTEM},
        {"role": "user", "content": user_prompt},
    ])

    outline = response.content.strip()

    # 确保以 # 标题开头
    if not outline.startswith("#"):
        outline = f"# {topic}\n\n" + outline

    return outline


if __name__ == "__main__":
    topic = "AI眼镜行业"
    outline = generate_outline(topic)
    print(outline)
