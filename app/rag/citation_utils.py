import re

def build_context_with_citations(retrieved_docs):
    """
    阶段一：构建带编号的上下文 (URL 去重处理)
    如果检索出 5 个 Chunk，其中 3 个来自同一个 URL，则它们共享同一个编号。
    
    返回:
        context_str (str): 喂给 LLM 的字符串，长这样 "[参考资料 1] \n 内容..."
        ref_map (dict): {1: "https://...", 2: "https://..."} 供最后拼接使用
    """
    context_str = ""
    ref_map = {}
    url_to_id = {}
    current_id = 1

    for doc in retrieved_docs:
        url = doc.metadata.get("url", "unknown")
        
        # URL 去重：如果这个 URL 之前没见过，分配一个新 ID
        if url not in url_to_id:
            url_to_id[url] = current_id
            ref_map[current_id] = url
            current_id += 1
            
        ref_id = url_to_id[url]
        
        context_str += f"[^{ref_id}] {doc.page_content}\n\n"

    return context_str, ref_map

def resolve_and_append_citations(llm_output, ref_map):
    """
    阶段三：解析角标并组装底部脚注定义

    参数:
        llm_output (str): LLM 生成的 Markdown 原始报告
        ref_map (dict): 阶段一生成的 ID 到 URL 的映射字典

    注意：不再追加 ### 📚 参考资料 标题，因为前端 Canvas 有专门的
    页尾引用区域渲染引用信息。此处仅追加 Markdown 脚注定义行，
    供前端 extractCitations() 提取后渲染到页尾。
    """
    # 使用正则找出文中所有类似 [^1], [^2] 的数字编号
    # 兼容处理 LLM 可能偶尔写成的 [1] 格式
    used_refs = set(re.findall(r'\[\^?(\d+)\]', llm_output))

    if not used_refs:
        return llm_output  # 如果 LLM 没用任何引用，直接返回原文本

    # 构建脚注定义（纯 Markdown footnote 语法，不带 h3 标题）
    footer = "\n\n---\n"

    # 将提取到的字符串编号转为整数并排序
    sorted_ref_ids = sorted([int(r) for r in used_refs])

    for ref_id in sorted_ref_ids:
        if ref_id in ref_map:
            url = ref_map[ref_id]
            # Markdown 脚注定义格式（前端 extractCitations 依赖此格式提取）
            footer += f"[^{ref_id}]: {url}\n"

    return llm_output + footer