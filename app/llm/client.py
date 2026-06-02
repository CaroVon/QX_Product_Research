"""
============================================================
LLM 客户端 —— 文本引擎 (DeepSeek) + 图像引擎 (硅基流动 FLUX.1)
============================================================
"""
import os
import time
import base64
import requests
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

# ══════════════════════════════════════════════════════════
# 文本引擎：DeepSeek Chat
# ══════════════════════════════════════════════════════════
def get_llm():
    """
    文本引擎：调用 DeepSeek 官方 API，用于分析报告大纲规划 + 章节撰写。
    """
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    llm = ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model_name,
        temperature=0.2,
    )
    return llm


# ══════════════════════════════════════════════════════════
# 图像引擎：硅基流动 (SiliconFlow) FLUX.1-schnell
# 国内高性价比，出图快，原生支持 16:9 横版
# ══════════════════════════════════════════════════════════
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
# 推荐模型: black-forest-labs/FLUX.1-schnell (速度优先, 性价比极高)
# 备选: black-forest-labs/FLUX.1-pro (品质优先)
SILICONFLOW_IMAGE_MODEL = os.getenv(
    "SILICONFLOW_IMAGE_MODEL",
    "black-forest-labs/FLUX.1-schnell"
)

# 横版 16:9 尺寸 (1024x576)
IMAGE_WIDTH = int(os.getenv("CONCEPT_IMAGE_WIDTH", "1024"))
IMAGE_HEIGHT = int(os.getenv("CONCEPT_IMAGE_HEIGHT", "576"))


def _wrap_prompt(raw_prompt: str) -> str:
    """
    对原始图片描述 Prompt 进行高规格商业 PPT 封面的风格强化。
    目标：生成极具视觉冲击力的横版路演封面配图。
    """
    return (
        f"Premium business presentation cover slide, cinematic 16:9 widescreen composition, "
        f"minimalist corporate aesthetic, futuristic technology atmosphere with elegant negative space, "
        f"dark sophisticated background with subtle gradient, high-end commercial keynote visual, "
        f"photorealistic hyper-detailed 8K render. Subject: {raw_prompt}"
    )


def generate_image(
    prompt: str,
    output_path: str,
    retries: int = 2,
    timeout: int = 120,
) -> bool:
    """
    调用硅基流动 FLUX.1 模型生成 16:9 横版概念图。

    🆕 增强韧性：
    - 严密的 try-except 异常捕获，覆盖网络超时、JSON 解析失败、
      图片下载中断、磁盘写入失败等所有已知故障模式
    - 指数退避重试（2ⁿ 秒间隔）
    - 超时保护（连接超时 + 读取超时双保险）
    - 参数约束：强制 16:9 横版比例 (1024×576)

    Args:
        prompt:      图片主题描述（中文/英文均可，内部会包一层风格 Prompt）
        output_path: 图片保存路径 (e.g. outputs/images/xxx_concept.png)
        retries:     失败重试次数 (default 2, total attempts = 3)
        timeout:     单次请求超时秒数 (default 120)

    Returns:
        bool: 生成成功返回 True，否则 False（调用方应使用 CSS 渐变兜底）
    """
    if not SILICONFLOW_API_KEY:
        print("[IMAGE WARN] 未设置 SILICONFLOW_API_KEY，跳过封面图生成 (报告将使用 CSS 渐变封面)")
        return False

    full_prompt = _wrap_prompt(prompt)

    # 🆕 强制约束 16:9 横版尺寸
    payload = {
        "model": SILICONFLOW_IMAGE_MODEL,
        "prompt": full_prompt,
        "n": 1,
        "size": f"{IMAGE_WIDTH}x{IMAGE_HEIGHT}",         # 1024×576 (16:9)
    }

    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(1, retries + 1 + 1):  # total = retries + 1 (initial)
        try:
            print(f"[IMAGE API] 调用硅基流动 {SILICONFLOW_IMAGE_MODEL} "
                  f"({IMAGE_WIDTH}×{IMAGE_HEIGHT}, 16:9 横版) "
                  f"第 {attempt}/{retries + 1} 次...")

            # 🆕 双超时保护：连接超时 15s + 读取超时 = timeout
            resp = requests.post(
                f"{SILICONFLOW_BASE_URL}/images/generations",
                json=payload,
                headers=headers,
                timeout=(15, timeout),  # (connect_timeout, read_timeout)
            )

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError as e:
                    print(f"[IMAGE ERR] JSON 解析响应失败: {e}")
                    if attempt <= retries:
                        time.sleep(3 * attempt)
                        continue
                    return False

                # OpenAI 兼容格式: data[0].url 或 data[0].b64_json
                image_url = None
                if "data" in data and len(data["data"]) > 0:
                    item = data["data"][0]
                    image_url = item.get("url")
                    b64_data = item.get("b64_json")

                    if image_url:
                        try:
                            # 🆕 下载图片二进制（带超时保护）
                            img_resp = requests.get(image_url, timeout=(10, 60))
                            img_resp.raise_for_status()
                            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                            with open(output_path, "wb") as f:
                                f.write(img_resp.content)
                            file_size_kb = os.path.getsize(output_path) / 1024
                            print(f"[IMAGE OK] 封面概念图已保存: {output_path} ({file_size_kb:.1f} KB)")
                            return True
                        except requests.exceptions.Timeout:
                            print(f"[IMAGE ERR] 图片下载超时")
                        except requests.exceptions.HTTPError as e:
                            print(f"[IMAGE ERR] 图片下载 HTTP 错误: {e}")
                        except OSError as e:
                            print(f"[IMAGE ERR] 写入图片文件失败: {e}")
                        # 下载失败继续尝试重试
                        if attempt <= retries:
                            time.sleep(3 * attempt)
                            continue
                        return False

                    elif b64_data:
                        try:
                            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                            with open(output_path, "wb") as f:
                                f.write(base64.b64decode(b64_data))
                            file_size_kb = os.path.getsize(output_path) / 1024
                            print(f"[IMAGE OK] 封面概念图已保存 (b64): {output_path} ({file_size_kb:.1f} KB)")
                            return True
                        except (base64.binascii.Error, OSError) as e:
                            print(f"[IMAGE ERR] Base64 解码 / 写文件失败: {e}")
                            if attempt <= retries:
                                time.sleep(3 * attempt)
                                continue
                            return False

                print(f"[IMAGE WARN] 响应中未找到图片数据: {str(data)[:200]}")
                if attempt <= retries:
                    time.sleep(3)
                    continue
                return False

            elif resp.status_code == 429:
                # 🆕 指数退避：2s, 4s, 8s...
                wait = 2 ** attempt
                print(f"[IMAGE WARN] 速率限制 (429)，{wait}s 后重试...")
                time.sleep(wait)
                continue
            elif resp.status_code >= 500:
                # 服务器错误，指数退避重试
                wait = 3 * attempt
                print(f"[IMAGE ERR] 服务器错误 {resp.status_code}: {resp.text[:200]}, {wait}s 后重试")
                time.sleep(wait)
                continue
            else:
                print(f"[IMAGE ERR] API 返回 {resp.status_code}: {resp.text[:300]}")
                if attempt <= retries:
                    time.sleep(3)
                continue

        except requests.exceptions.Timeout:
            print(f"[IMAGE ERR] 请求超时 (连接 15s + 读取 {timeout}s)")
            if attempt <= retries:
                wait = 3 * attempt
                print(f"[IMAGE RETRY] {wait}s 后重试...")
                time.sleep(wait)
        except requests.exceptions.ConnectionError as e:
            print(f"[IMAGE ERR] 连接错误: {e}")
            if attempt <= retries:
                wait = 5 * attempt
                print(f"[IMAGE RETRY] {wait}s 后重试...")
                time.sleep(wait)
        except Exception as e:
            print(f"[IMAGE ERR] 未预期异常: {type(e).__name__}: {e}")
            if attempt <= retries:
                time.sleep(3 * attempt)

    print(f"[IMAGE FAIL] 所有 {retries + 1} 次尝试均失败，将使用 CSS 渐变兜底封面")
    return False
