from app.llm.client import get_llm


def generate_outline(topic: str):
    """
    基于核心升级诉求，强制约束生成固定且规范的 6 大核心产品研报章节。
    """
    outline = """
## 1. 产品设计理念
## 2. 使用场景
## 3. 现有产品分析
## 4. 市场分析
## 5. 人的使用习惯
## 6. 产品概念简易图鉴
"""
    return outline.strip()


if __name__ == "__main__":

    topic = "AI眼镜行业"

    outline = generate_outline(topic)

    print(outline)
