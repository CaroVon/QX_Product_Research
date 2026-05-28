"""
============================================================
backend/app 包初始化
—— 通过扩展 __path__ 将 research_agent/app/ 的子模块合并进来
============================================================

问题背景：
  backend/app/ 和 research_agent/app/ 都是 "app" 包。
  Python 在同一命名空间下默认只能使用一个包路径，
  导致 research_agent/app/ 下的子模块（search, crawler, rag 等）
  无法被 Celery Worker 导入。

解决方案：
  在 __path__ 中追加 research_agent/app/ 目录，
  使得 app.search / app.crawler / app.planner / app.report / app.rag
  等子模块可以被正确解析。
"""

import os
import sys

# ─── 计算 research_agent 根目录 ────────────────────────────
# __file__: /root/autodl-tmp/research_agent/backend/app/__init__.py
_current_dir = os.path.dirname(os.path.abspath(__file__))        # backend/app/
_backend_dir = os.path.dirname(_current_dir)                      # backend/
_research_agent_dir = os.path.dirname(_backend_dir)               # research_agent/

# ─── 将 research_agent 加入 sys.path（确保 import app 时能找到） ─
if _research_agent_dir not in sys.path:
    sys.path.insert(0, _research_agent_dir)

# ─── 将 research_agent/app/ 追加到 app 包的 __path__ ──────────
_research_agent_app = os.path.join(_research_agent_dir, "app")
if os.path.isdir(_research_agent_app) and _research_agent_app not in __path__:
    __path__.append(_research_agent_app)
