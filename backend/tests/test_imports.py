"""
============================================================
导入测试 —— 验证所有模块能否正常导入
============================================================
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 1. 测试核心配置
print("[TEST] 导入 config...")
from app.core.config import get_settings, Settings
s = get_settings()
print(f"  OK: APP_NAME={s.APP_NAME}, DB={s.POSTGRES_HOST}")

# 2. 测试 Pydantic schemas
print("[TEST] 导入 schemas...")
from app.schemas import (
    ProjectCreateRequest,
    ProjectResponse,
    ProjectCreateResponse,
    ProjectStatusResponse,
    TaskResponse,
    DownloadResponse,
)

# 测试 Schema 校验
req = ProjectCreateRequest(topic="AI眼镜行业")
print(f"  OK: ProjectCreateRequest(topic={req.topic})")

resp = ProjectResponse(
    id="00000000-0000-0000-0000-000000000001",
    topic="test",
    status="pending",
    created_at="2024-01-01T00:00:00Z",
)
print(f"  OK: ProjectResponse(id={resp.id})")

# 3. 测试 ORM 模型（纯语法检查）
print("[TEST] 导入 models（语法检查）...")
from app.models import Base, User, Project, Task, Document, ProjectStatus, TaskType, TaskStatus
print(f"  OK: 所有模型导入成功")

# 4. 测试 Celery 应用
print("[TEST] 导入 celery_app...")
from app.core.celery_app import celery_app
print(f"  OK: Celery app name={celery_app.main}")

# 5. 测试 FastAPI 应用
print("[TEST] 导入 FastAPI app...")
from app.main import create_app
app = create_app()
routes = [r.path for r in app.routes if hasattr(r, 'path')]
print(f"  OK: FastAPI 路由数量={len(routes)}")
print(f"  路由列表: {routes}")

print("\n" + "=" * 50)
print("[PASSED] 所有模块导入测试通过！")
print("=" * 50)
