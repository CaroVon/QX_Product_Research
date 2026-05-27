import os
from app.llm.client import get_llm, generate_image
from app.rag.retriever import retrieve
from app.rag.citation_utils import build_context_with_citations, resolve_and_append_citations

def write_section(topic: str, section_title: str):
    llm = get_llm()
    
    # 分流控制：如果是生图/图鉴章节，直接切入多模态工业绘图工作流
    if any(keyword in section_title for keyword in ["生图", "图鉴", "概念图"]):
        print(f" -> [🎨 多模态绘图] 正在为章节【{section_title}】激发绘图大模型...")
        image_relative_path = f"outputs/images/{topic}_concept.png"
        
        # 让高级语言模型先转化为极具工业美学细节的英文图像 Prompt
        prompt_generator = f"请为主题为 '{topic}' 的前沿科技产品，撰写一段用于文生图模型的英文工业设计细节提示词(Prompt)。要求包含材质、高科技感、线条流线型。直接输出英文提示词，严禁包含任何多余文字或解释。"
        img_prompt = llm.invoke(prompt_generator).content.strip()
        
        # 调用图片生成引擎
        success = generate_image(img_prompt, image_relative_path)
        
        if success:
            # WeasyPrint 渲染本地图片需要正确的路径结构，使用相对路径完美适配 Markdown 和 HTML
            return f"## {section_title}\n\n本章节内容由多模态绘图引擎实时渲染生成。以下是基于上述所有行业分析、用户习惯推演出的前沿产品概念设计：\n\n![{topic}概念图](../{image_relative_path})\n\n> *图注：由多模态 FLUX 工业设计引擎绘制的高精度产品透视概念图。*\n"
        else:
            return f"## {section_title}\n\n[⚠️ 视觉概念图生成失败，请检查全流程网络及 API 额度]\n"

    # 正常的文本章节：走深度检索增强(RAG)高精度溯源编写路线
    print(f" -> [📝 文本撰写] 正在深度撰写章节【{section_title}】...")
    docs = retrieve(f"{topic} {section_title}", k=4)
    context_str, ref_map = build_context_with_citations(docs)
    
    prompt = f"""
你是一名享誉业内的资深行业研究员与产品战略专家。请基于提供的最新【参考资料】，完成研报章节的深度撰写。

【报告主题】: {topic}
【当前撰写章节】: {section_title}

【高品质行研规范】:
1. 摒弃空洞辞藻：必须充满翔实的技术指标、商业现状或用户行为习惯的定性与定量分析。
2. 严苛数据溯源：若一句话引用了参考资料的内容，必须在其句尾（句号前）添加对应的脚注角标，例如 [^1]。
3. 排版赏心悦目：善于利用 Markdown 粗体、逻辑列表或分段来确保极佳的可读性。

【参考资料】:
{context_str}

请开始完成本章深度撰写：
"""
    response = llm.invoke(prompt)
    raw_content = response.content
    final_content = resolve_and_append_citations(raw_content, ref_map)
    
    if not final_content.strip().startswith("##"):
        final_content = f"## {section_title}\n\n" + final_content
        
    return final_content