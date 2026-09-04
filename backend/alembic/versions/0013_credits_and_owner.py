"""W3-4 多用户计费底座：qx_assets 归属列 + credit_ledger 账本 + 旧数据归属合并

Revision ID: 0013
Revises: 0012
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. qx_assets 增加 owner（与 studio_products 同语义：NULL=旧数据/全可见）
    op.add_column("qx_assets", sa.Column("owner_id", sa.UUID(), nullable=True))
    op.create_index("ix_qx_assets_owner_id", "qx_assets", ["owner_id"])

    # 2. credits 账本（三类：llm_tokens/image/rainforest；正数=发放，负数=消耗）
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False, index=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("delta", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False, server_default=""),
        sa.Column("meta", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_credit_ledger_user_kind", "credit_ledger", ["user_id", "kind"])

    # 3. 旧数据归属合并：legacy 'admin' 用户的产品/资产归并到 deer-flow 管理员映射用户
    #    （UPDATE ... FROM 空集时 no-op，目标用户不存在则保持原状）
    op.execute("""
        UPDATE studio_products sp SET owner_id = t.new_id
        FROM (SELECT u2.id AS new_id FROM users u2 WHERE u2.username = 'admin@deerflow.qxdev.com') t
        WHERE sp.owner_id = (SELECT u.id FROM users u WHERE u.username = 'admin')
    """)
    op.execute("""
        UPDATE qx_assets a SET owner_id = COALESCE(a.owner_id, t.new_id)
        FROM (SELECT u2.id AS new_id FROM users u2 WHERE u2.username = 'admin@deerflow.qxdev.com') t
    """)


def downgrade() -> None:
    op.drop_index("ix_credit_ledger_user_kind", table_name="credit_ledger")
    op.drop_table("credit_ledger")
    op.drop_index("ix_qx_assets_owner_id", table_name="qx_assets")
    op.drop_column("qx_assets", "owner_id")
