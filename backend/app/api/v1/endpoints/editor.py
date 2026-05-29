"""
============================================================
编辑器 AI 相关 API 路由
—— InlineAIBubble 的「扩写/精简/润色/自定义指令」后端
============================================================
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.schemas import EditorReviseRequest, EditorReviseResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/editor", tags=["editor"])


# ================================================================
# POST /api/v1/editor/revise —— AI 改写选中文本
# ================================================================

@router.post("/revise", response_model=EditorReviseResponse)
async def revise_text(body: EditorReviseRequest):
    """
    对用户选中的文本执行 AI 改写。

    该端点被前端 InlineAIBubble 组件调用，
    支持「扩写」「精简」「润色」等快速按钮及自定义指令。

    参数:
    - **selected_text**: 用户选中的原文
    - **instruction**: 改写指令（扩写/精简/润色/自定义）
    - **context**: （可选）段落前后文，帮助 LLM 保持语境连贯

    返回:
    - **revised_text**: LLM 改写后的文本
    """
    try:
        settings = get_settings()

        system_prompt = (
            "你是一个专业的中文学术写作助手。请根据用户的指令改写文本。\n"
            "要求：\n"
            "1. 保持原文的核心信息和专业术语不变\n"
            "2. 仅返回改写后的文本，不要添加任何解释、前缀或注释\n"
            "3. 不要使用 Markdown 格式回复，仅返回纯文本\n"
        )

        user_message = (
            f"【改写指令】{body.instruction}\n\n"
            f"【原文】\n{body.selected_text}\n"
        )

        if body.context:
            user_message += f"\n【上下文参考（仅用于理解语境，不要直接引用）】\n{body.context}\n"

        llm = ChatOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            model=settings.DEEPSEEK_MODEL,
            temperature=0.3,
        )

        response = llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ])

        revised_text = response.content.strip()

        if not revised_text:
            raise ValueError("LLM 返回空内容")

        logger.info(
            "editor/revise 成功 | instruction=%s | len(selected)=%d | len(revised)=%d",
            body.instruction, len(body.selected_text), len(revised_text),
        )

        return EditorReviseResponse(revised_text=revised_text)

    except Exception as e:
        logger.error(
            "editor/revise 失败 | instruction=%s | error=%s",
            body.instruction, str(e), exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI 改写失败: {str(e)}",
        )
