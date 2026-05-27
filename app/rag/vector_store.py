import os
import pickle
from langchain_chroma import Chroma
from langchain_core.documents import Document
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

embedding_model = LocalEmbeddingModel()


def build_vector_store(chunk_data_list):
    """
    接收带有元数据的切片列表
    chunk_data_list 格式要求: [{"content": "...", "url": "https://..."}]
    """
    docs = []
    for item in chunk_data_list:
        # 这里提取纯文本用于生成向量，提取 url 放入 metadata 用于后续打分
        doc = Document(
            page_content=item.get("content", ""), 
            metadata={"url": item.get("url", "unknown")}
        )
        docs.append(doc)
    
    # 1. 持久化存储到 Chroma (用于向量检索)
    vector_store = Chroma.from_documents(
        documents=docs,
        embedding=embedding_model,
        persist_directory="./chroma_db"
    )
    
    # 2. 持久化原始 Chunks 到本地 (用于 BM25 检索)
    import os, pickle
    os.makedirs("./bm25_db", exist_ok=True)
    with open("./bm25_db/docs.pkl", "wb") as f:
        pickle.dump(docs, f)
        
    print("[INFO] Vector Store 和 BM25 本地语料均已构建完毕 (包含 Metadata)。")
    return vector_store

if __name__ == "__main__":
    sample_chunks = [
        "AI glasses market is growing rapidly.",
        "Meta and RayBan launched smart glasses.",
        "AI wearable devices are becoming popular."
    ]
    db = build_vector_store(sample_chunks)