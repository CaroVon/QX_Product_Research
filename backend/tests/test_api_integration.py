"""
============================================================
API 集成测试 —— 使用 SQLite 替代 PostgreSQL
验证所有核心路由能正常响应
============================================================
"""

import sys
import os
import json
import asyncio
import uuid
from datetime import datetime
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ─── 覆写数据库为 SQLite（测试隔离） ─────────────────────────
os.environ["POSTGRES_HOST"] = "localhost"

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import select

from app.main import create_app
from app.core.database import get_db, Base
from app.models import User, Project, ProjectStatus, Task, TaskType, TaskStatus


# ─── 使用 SQLite 内存数据库 ──────────────────────────────────
TEST_DB_URL = "sqlite+aiosqlite:///./test_research.db"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def override_get_db():
    """覆写 FastAPI 的数据库依赖"""
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ─── Mock Celery 任务（避免依赖 Redis） ──────────────────────
class MockCeleryTask:
    """模拟 Celery AsyncResult"""
    _id = "mock-task-id-001"

    @property
    def id(self):
        return self._id

    def delay(self, *args, **kwargs):
        return self

    def get(self, timeout=None):
        return {"status": "completed"}


# Patch 在 projects 模块中已导入的引用（而非原始定义）
mock_celery_patch = patch(
    "app.api.v1.endpoints.projects.run_full_report_workflow",
    MockCeleryTask(),
)

# ─── 测试夹具 ────────────────────────────────────────────────
app = create_app()
app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="module")
def event_loop():
    """为整个模块创建一个事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def setup_db():
    """每个测试前重建表"""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 插入默认演示用户
    async with TestSessionLocal() as session:
        user = User(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            email="admin@test.com",
            username="admin",
            hashed_password="fakehash",
            is_active=True,
            is_superuser=True,
        )
        session.add(user)
        await session.commit()

    yield

    # 清理
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_health_check():
    """测试健康检查接口"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["app"] == "Research Agent API"


@pytest.mark.asyncio
async def test_create_project():
    """测试创建项目"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with mock_celery_patch:
            resp = await client.post(
                "/api/v1/projects",
                json={"topic": "AI眼镜行业"},
            )
        assert resp.status_code == 201, f"创建失败: {resp.text}"
        data = resp.json()
        assert "project" in data
        assert data["project"]["topic"] == "AI眼镜行业"
        assert data["project"]["status"] == "processing"
        assert "celery_task_id" in data
        print(f"\n  [OK] 创建项目成功: id={data['project']['id']}")


@pytest.mark.asyncio
async def test_get_project_status():
    """测试查询项目状态"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 先创建项目
        with mock_celery_patch:
            create_resp = await client.post(
                "/api/v1/projects",
                json={"topic": "AI眼镜行业"},
            )
        project_id = create_resp.json()["project"]["id"]

        # 查询状态
        resp = await client.get(f"/api/v1/projects/{project_id}/status")
        assert resp.status_code == 200, f"查询失败: {resp.text}"
        data = resp.json()
        assert data["project_id"] == project_id
        assert "progress" in data
        assert "tasks" in data
        assert data["progress"]["total_tasks"] > 0
        print(f"\n  [OK] 查询状态成功: 共 {data['progress']['total_tasks']} 个任务")


@pytest.mark.asyncio
async def test_get_project_download_before_complete():
    """测试未完成时下载应返回 409"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with mock_celery_patch:
            create_resp = await client.post(
                "/api/v1/projects",
                json={"topic": "测试项目"},
            )
        project_id = create_resp.json()["project"]["id"]

        resp = await client.get(f"/api/v1/projects/{project_id}/download")
        assert resp.status_code == 409, f"应返回 409: {resp.text}"
        data = resp.json()
        assert "生成中" in data["detail"]
        print(f"\n  [OK] 未完成时返回 409: {data['detail']}")


@pytest.mark.asyncio
async def test_list_projects():
    """测试项目列表"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 创建 3 个项目
        with mock_celery_patch:
            for topic in ["AI眼镜行业", "新国潮软床", "3维交互编辑器"]:
                await client.post("/api/v1/projects", json={"topic": topic})

        resp = await client.get("/api/v1/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 3
        topics = [p["topic"] for p in data]
        assert "AI眼镜行业" in topics
        print(f"\n  [OK] 项目列表返回 {len(data)} 个项目")


@pytest.mark.asyncio
async def test_project_not_found():
    """测试项目不存在"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        fake_id = "00000000-0000-0000-0000-000000009999"
        resp = await client.get(f"/api/v1/projects/{fake_id}/status")
        assert resp.status_code == 404
        print(f"\n  [OK] 不存在的项目返回 404")


@pytest.mark.asyncio
async def test_schema_validation():
    """测试 Schema 校验"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 空 topic 应校验失败
        resp = await client.post("/api/v1/projects", json={"topic": ""})
        assert resp.status_code == 422
        print(f"\n  [OK] 空 topic 校验返回 422")

        # 缺少 topic 字段
        resp = await client.post("/api/v1/projects", json={})
        assert resp.status_code == 422
        print(f"  [OK] 缺少字段校验返回 422")


if __name__ == "__main__":
    print("=" * 60)
    print("Research Agent API 集成测试")
    print("=" * 60)

    async def run_tests():
        # 初始化数据库
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with TestSessionLocal() as session:
            user = User(
                id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                email="admin@test.com",
                username="admin",
                hashed_password="fakehash",
                is_active=True,
                is_superuser=True,
            )
            session.add(user)
            await session.commit()

        tests = [
            ("健康检查", test_health_check),
            ("创建项目", test_create_project),
            ("查询项目状态", test_get_project_status),
            ("未完成时下载返回409", test_get_project_download_before_complete),
            ("项目列表", test_list_projects),
            ("项目不存在404", test_project_not_found),
            ("Schema校验422", test_schema_validation),
        ]

        passed = 0
        for name, test_fn in tests:
            try:
                await test_fn()
                print(f"  ✅ {name}")
                passed += 1
            except Exception as e:
                print(f"  ❌ {name}: {e}")

        # 清理
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await test_engine.dispose()
        if os.path.exists("./test_research.db"):
            os.remove("./test_research.db")

        print(f"\n{'=' * 50}")
        print(f"结果: {passed}/{len(tests)} 通过")
        print(f"{'=' * 50}")

    asyncio.run(run_tests())
