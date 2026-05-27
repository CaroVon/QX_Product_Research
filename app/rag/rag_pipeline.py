from app.search.tavily_search import tavily_search
from app.crawler.firecrawl_crawler import crawl_url
from app.rag.chunker import chunk_text
from app.rag.vector_store import build_vector_store
from app.rag.retriever import retrieve

def build_knowledge_base(query: str):
    search_results = tavily_search(query)
    results = search_results.get("results", [])
    
    all_chunks_with_meta = [] # 变量名改一下，提醒我们现在存的是字典

    for item in results[:3]:
        url = item.get("url")
        print(f"\nCrawling: {url}")

        try:
            crawl_result = crawl_url(url)
            markdown = getattr(crawl_result, "markdown", "")

            if markdown:
                chunks = chunk_text(markdown)
                
                # 【修改点 1：把 URL 打包进数据字典】
                for chunk in chunks:
                    all_chunks_with_meta.append({
                        "content": chunk,
                        "url": url
                    })

                print(f"[OK] Added {len(chunks)} chunks from {url}")

        except Exception as e:
            print(f"[ERROR] {e}")

    # 将带有 Metadata 的字典列表传给底层的向量库
    build_vector_store(all_chunks_with_meta)
    print(f"\n[INFO] Total chunks stored: {len(all_chunks_with_meta)}")

def retrieve_context(query: str, k: int = 5):
    results = retrieve(query, k=k)
    context = ""

    for idx, r in enumerate(results, start=1):
        # 【修改点 2：在送给 LLM 的上下文中，强行暴露出 URL 来源】
        source_url = r.metadata.get("url", "unknown")
        context += f"""
[Chunk {idx} | 来源: {source_url}]

{r.page_content}

"""
    return context


if __name__ == "__main__":
    topic = "AI眼镜行业"
    
    print("========== 1. 重新构建知识库 (注入 Metadata) ==========")
    build_knowledge_base(topic)

    print("\n========== 2. 测试带权重的混合检索 ==========")
    context = retrieve_context("AI眼镜市场规模与竞争格局", k=3)
    print(context)