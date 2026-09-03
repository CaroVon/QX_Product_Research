"""studio_products.status 新增 cancelled 终态（用户主动终止）

与 failed 严格区分：claim 幂等守卫、Celery 重试、看门狗均不复活 cancelled，
前端徽章显示灰色「已取消」而非红色失败。

Revision ID: 0011
Revises: 0010
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS 幂等：与 0006 新增 paused 同模式。
    # PG>=12 支持事务内 ADD VALUE（新值不在同事务内使用即可）。
    op.execute("ALTER TYPE studioproductstatus ADD VALUE IF NOT EXISTS 'cancelled'")


def downgrade() -> None:
    # PG 无法直接删除枚举值；保持幂等即可（删除需重建类型，风险大于收益）。
    pass
