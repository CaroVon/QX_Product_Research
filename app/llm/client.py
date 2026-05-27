import os
import requests
import urllib.parse
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

def get_llm():
    """
    文本引擎：调用 DeepSeek 官方 API
    """
    api_key = os.getenv("DEEPSEEK_API_KEY", "sk-d6f9017bee204c49a6fb03dee9dc6a0c") 
    base_url = "https://api.deepseek.com/v1"
    model_name = "deepseek-chat"
    
    llm = ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model_name,
        temperature=0.2, 
    )
    return llm

def generate_image(prompt: str, output_path: str):
    """
    绘图引擎：备用免注册直连方案 (Pollinations API)
    底层基于强大的 FLUX 大模型，完全免费且无需 API Key。
    """
    # 融入专业工业设计风格的英文 Prompt Wrapper
    full_prompt = f"Professional industrial design product photography, sleek futuristic design, hyper-detailed, clean studio background, high-end commercial asset, {prompt}"
    
    # 对 Prompt 进行 URL 编码 (解决特殊字符导致的网络请求失败)
    encoded_prompt = urllib.parse.quote(full_prompt)
    
    # 构建 GET 请求 URL
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=768&nologo=true"
    
    try:
        print("[API INFO] 正在调用免注册视觉引擎生成概念图，请稍候...")
        response = requests.get(url, timeout=45)
        
        if response.status_code == 200:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(response.content)
            print(f"[API OK] 概念图生成成功并已保存至: {output_path}")
            return True
        else:
            print(f"[API ERROR] 绘图接口调用失败，状态码: {response.status_code}")
            return False
    except Exception as e:
        print(f"[API EXCEPTION] 绘图过程中发生网络异常: {e}")
        return False