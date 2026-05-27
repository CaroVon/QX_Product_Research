import pickle
import jieba
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from sentence_transformers import SentenceTransformer

class LocalEmbeddingModel:
    def __init__(self):
        self.model = SentenceTransformer(
            "/root/autodl-tmp/models/embedding/bge-small-zh-v1.5"
        )

    def embed_documents(self, texts):
        return self.model.encode(texts).tolist()

    def embed_query(self, text):
        return self.model.encode(text).tolist()

# 保持单例
embedding_model = LocalEmbeddingModel()

def jieba_tokenizer(text):
    return list(jieba.cut(text))

# app/rag/retriever.py

def get_source_weight(url: str) -> float:
    """
    信息源分级与权重计算引擎 (Source Ranking Engine)
    """
    if not url or url == "unknown":
        return 1.0 # 未知来源，不奖不惩

    url = url.lower()

    # T0级 (权重 1.5): 绝对权威。PDF报告、政府、交易所、官方白皮书
    if any(ext in url for ext in [".pdf", ".gov", "sse.com.cn", "szse.cn", "hkex.com.hk"]):
        return 1.5
    
    # T1级 (权重 1.2): 深度研报/专业商业媒体
    elif any(domain in url for domain in ["bloomberg", "36kr.com", "caixin.com", "xueqiu.com", "huxiu.com", "yicai.com"]):
        return 1.2
    
    # T3级 (权重 0.5): UGC 社区/自媒体 (易混入公关水文或主观情绪，重度降权)
    elif any(domain in url for domain in ["zhihu.com", "bilibili.com", "weibo.com", "tieba.baidu.com", "xiaohongshu.com"]):
        return 0.5
    
    # T2级 (权重 1.0): 其他普通新闻网站
    return 1.0

def reciprocal_rank_fusion(vector_results, bm25_results, k=60):
    """
    引入 Source Ranking 的加强版 RRF 算法
    """
    fused_scores = {}
    doc_map = {}

    # 处理向量检索结果
    for rank, doc in enumerate(vector_results, start=1):
        # 以内容和URL的组合作为唯一键，防止不同URL引用同一段话被去重吃掉
        url = doc.metadata.get("url", "unknown")
        doc_key = doc.page_content + "|" + url  
        doc_map[doc_key] = doc
        
        # 核心：基础排名分 × 来源置信度乘数
        source_weight = get_source_weight(url)
        base_score = 1 / (rank + k)
        fused_scores[doc_key] = fused_scores.get(doc_key, 0.0) + (base_score * source_weight)

    # 处理 BM25 检索结果
    for rank, doc in enumerate(bm25_results, start=1):
        url = doc.metadata.get("url", "unknown")
        doc_key = doc.page_content + "|" + url
        doc_map[doc_key] = doc
        
        source_weight = get_source_weight(url)
        base_score = 1 / (rank + k)
        fused_scores[doc_key] = fused_scores.get(doc_key, 0.0) + (base_score * source_weight)

    # 根据叠加权重后的最终分倒序排列
    reranked_results = [
        doc_map[doc_key] 
        for doc_key, score in sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
    ]
    return reranked_results


def retrieve(query: str, k: int = 5):
    """对外暴露的统一混合检索接口"""
    
    # 1. 执行纯向量检索 (扩大召回池到 k*2)
    db = Chroma(persist_directory="./chroma_db", embedding_function=embedding_model)
    vector_retriever = db.as_retriever(search_kwargs={"k": k * 2})
    vector_results = vector_retriever.invoke(query)

    # 2. 执行 BM25 关键词检索 (扩大召回池到 k*2)
    try:
        with open("./bm25_db/docs.pkl", "rb") as f:
            docs = pickle.load(f)
        bm25_retriever = BM25Retriever.from_documents(docs, preprocess_func=jieba_tokenizer)
        bm25_retriever.k = k * 2
        bm25_results = bm25_retriever.invoke(query)
    except Exception as e:
        print(f"[WARN] BM25 语料加载失败 ({e})，降级为纯向量检索。")
        bm25_results = []

    # 3. 融合排序并截断前 k 个
    final_results = reciprocal_rank_fusion(vector_results, bm25_results)
    
    return final_results[:k]


if __name__ == "__main__":
    results = retrieve("Micro-OLED", k=3)
    print("\n========== HYBRID RETRIEVAL ==========\n")
    for r in results:
        print(r.page_content[:200])
        print("\n-----------------\n")