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
# 新状态机使用 prepare_sources_workflow 作为入口
mock_celery_patch = patch(
    "app.api.v1.endpoints.projects.prepare_sources_workflow",
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
            name="Admin User",
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
        assert data["app"] == "Product Analysis Agent API"


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
        assert data["project"]["status"] == "preparing_data"
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


@pytest.mark.asyncio
async def test_source_review_flow():
    """🎯 测试交互节点1：资料审核流程（状态机约束）"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with mock_celery_patch:
            create_resp = await client.post(
                "/api/v1/projects",
                json={"topic": "AI眼镜行业"},
            )
        project_id = create_resp.json()["project"]["id"]

        # 此时状态应为 preparing_data，资料审核应返回 409
        resp = await client.get(f"/api/v1/projects/{project_id}/sources")
        assert resp.status_code == 409, f"preparing_data 状态下获取资料应返回409: {resp.text}"
        print(f"\n  [OK] preparing_data 状态下 GET /sources → 409 (正确阻断)")

        # 审核资料也应在非 waiting_for_sources 状态被阻断
        resp = await client.post(
            f"/api/v1/projects/{project_id}/review-sources",
            json={"selected_urls": ["https://example.com"]},
        )
        assert resp.status_code == 409, f"非 waiting_for_sources 下审核应返回409: {resp.text}"
        print(f"  [OK] 非 waiting_for_sources 状态下 POST /review-sources → 409 (正确阻断)")


@pytest.mark.asyncio
async def test_outline_approval_flow():
    """🎯 测试交互节点2：大纲审批流程（状态机约束）"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with mock_celery_patch:
            create_resp = await client.post(
                "/api/v1/projects",
                json={"topic": "AI眼镜行业"},
            )
        project_id = create_resp.json()["project"]["id"]

        # 手动将项目状态推进到 waiting_for_outline，测试审批流程
        async with TestSessionLocal() as session:
            result = await session.execute(
                select(Project).where(Project.id == uuid.UUID(project_id))
            )
            project = result.scalar_one()
            project.status = ProjectStatus.WAITING_FOR_OUTLINE
            project.outline_content = "# AI眼镜\n## 1. 行业概述\n## 2. 市场分析\n## 3. 竞品研究"
            await session.commit()

        # 此时应能成功审批大纲
        mock_draft = MockCeleryTask()
        with patch("app.api.v1.endpoints.projects.run_draft_sections_workflow", mock_draft):
            resp = await client.post(
                f"/api/v1/projects/{project_id}/approve-outline",
                json={
                    "outline": "# AI眼镜行业深度分析\n## 1. 行业概述与趋势\n## 2. 市场规模分析\n## 3. 竞品格局"
                },
            )
        assert resp.status_code == 200, f"审批大纲失败: {resp.text}"
        data = resp.json()
        assert data["new_status"] == "drafting", f"状态应为 drafting，实际: {data['new_status']}"
        assert data["sections_count"] == 3, f"应解析出 3 个章节，实际: {data['sections_count']}"
        print(f"\n  [OK] 大纲审批成功: {data['sections_count']} 个章节 → 状态变为 drafting")

        # 验证 DocumentBlock 占位已创建
        resp = await client.get(f"/api/v1/projects/{project_id}/blocks")
        assert resp.status_code == 200
        blocks = resp.json()["blocks"]
        assert len(blocks) == 3, f"应有 3 个占位块，实际: {len(blocks)}"
        print(f"  [OK] 已创建 {len(blocks)} 个 DocumentBlock 占位")

        # 再次审批应返回 409（不在 waiting 状态）
        resp = await client.post(
            f"/api/v1/projects/{project_id}/approve-outline",
            json={"outline": "# Test\n## 1. S1"},
        )
        assert resp.status_code == 409
        print(f"  [OK] 重复审批大纲 → 409 (正确阻断)")


@pytest.mark.asyncio
async def test_editor_revise_endpoint():
    """🎯 测试 Inline AI 编辑器改写功能"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 测试快速指令：润色
        resp = await client.post(
            "/api/v1/editor/revise",
            json={
                "selected_text": "AI眼镜市场在2025年达到1000亿规模，增长迅速。",
                "instruction": "润色",
            },
        )
        assert resp.status_code == 200, f"编辑改写失败: {resp.text}"
        data = resp.json()
        assert "revised_text" in data
        assert len(data["revised_text"]) > 0
        print(f"\n  [OK] 编辑器改写成功: len={len(data['revised_text'])}")

        # 测试自定义指令
        resp = await client.post(
            "/api/v1/editor/revise",
            json={
                "selected_text": "The product has good features.",
                "instruction": "使表达更正式",
            },
        )
        assert resp.status_code == 200
        print(f"  [OK] 自定义指令改写成功")

        # 测试输入校验（空文本）
        resp = await client.post(
            "/api/v1/editor/revise",
            json={
                "selected_text": "",
                "instruction": "润色",
            },
        )
        assert resp.status_code == 422, f"空文本应返回 422: {resp.text}"
        print(f"  [OK] 空文本校验 → 422")


@pytest.mark.asyncio
async def test_full_state_machine_flow():
    """🎯 测试完整状态机流转：PREPARING_DATA → WAITING_FOR_SOURCES → WAITING_FOR_OUTLINE → DRAFTING → COMPLETED"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 创建项目 (PREPARING_DATA)
        with mock_celery_patch:
            create_resp = await client.post(
                "/api/v1/projects",
                json={"topic": "状态机端到端测试"},
            )
        assert create_resp.status_code == 201
        project_id = create_resp.json()["project"]["id"]
        print(f"\n  [STEP 1] 项目创建: {project_id} → preparing_data")

        # 2. 模拟资料准备完成 → WAITING_FOR_SOURCES
        async with TestSessionLocal() as session:
            result = await session.execute(
                select(Project).where(Project.id == uuid.UUID(project_id))
            )
            project = result.scalar_one()
            project.status = ProjectStatus.WAITING_FOR_SOURCES
            await session.commit()
        print(f"  [STEP 2] 状态推进: preparing_data → waiting_for_sources")

        # 3. 用户审核资料 → 触发大纲生成
        resp = await client.post(
            f"/api/v1/projects/{project_id}/review-sources",
            json={"selected_urls": ["https://example.com/source1"]},
        )
        assert resp.status_code == 200, f"资料审核失败: {resp.text}"
        assert resp.json()["new_status"] == "preparing_outline"
        print(f"  [STEP 3] 资料审核确认 → preparing_outline")

        # 4. 模拟大纲生成完成 → WAITING_FOR_OUTLINE
        async with TestSessionLocal() as session:
            result = await session.execute(
                select(Project).where(Project.id == uuid.UUID(project_id))
            )
            project = result.scalar_one()
            project.status = ProjectStatus.WAITING_FOR_OUTLINE
            project.outline_content = "# 测试报告\n## 1. 概述\n## 2. 分析\n## 3. 结论"
            await session.commit()
        print(f"  [STEP 4] 状态推进: preparing_outline → waiting_for_outline")

        # 5. 用户审批大纲 → DRAFTING
        mock_draft = MockCeleryTask()
        with patch("app.api.v1.endpoints.projects.run_draft_sections_workflow", mock_draft):
            resp = await client.post(
                f"/api/v1/projects/{project_id}/approve-outline",
                json={
                    "outline": "# 测试报告\n## 1. 概述\n## 2. 分析\n## 3. 结论"
                },
            )
        assert resp.status_code == 200
        assert resp.json()["new_status"] == "drafting"
        assert resp.json()["sections_count"] == 3
        print(f"  [STEP 5] 大纲确认 → drafting ({resp.json()['sections_count']} 章节)")

        # 6. 验证 DocumentBlock 和 Task 已创建
        resp = await client.get(f"/api/v1/projects/{project_id}/blocks")
        assert resp.status_code == 200
        blocks = resp.json()["blocks"]
        assert len(blocks) == 3

        resp = await client.get(f"/api/v1/projects/{project_id}/status")
        write_tasks = [t for t in resp.json()["tasks"] if t["task_type"] == "write_section"]
        assert len(write_tasks) == 3
        print(f"  [STEP 6] 验证: {len(blocks)} blocks + {len(write_tasks)} write tasks")

        # 7. 模拟全部撰写完成 → COMPLETED
        async with TestSessionLocal() as session:
            result = await session.execute(
                select(Project).where(Project.id == uuid.UUID(project_id))
            )
            project = result.scalar_one()
            project.status = ProjectStatus.COMPLETED
            await session.commit()
        print(f"  [STEP 7] 状态推进: drafting → completed")

        # 8. 验证最终状态
        resp = await client.get(f"/api/v1/projects/{project_id}/status")
        assert resp.json()["project_status"] == "completed"
        print(f"  [STEP 8] 最终状态验证: ✅ COMPLETED")


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
                name="Admin User",
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
