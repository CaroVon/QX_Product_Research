"""W7 session 分离：qx_assets / studio_products 增加 thread_id 关联

历史数据 thread_id 为 NULL（面板归入「历史」分组）；新数据严格按 session 分离。

Revision ID: 0014
Revises: 0013
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("qx_assets", sa.Column("thread_id", sa.String(64), nullable=True))
    op.create_index("ix_qx_assets_thread_id", "qx_assets", ["thread_id"])
    op.add_column("studio_products", sa.Column("thread_id", sa.String(64), nullable=True))
    op.create_index("ix_studio_products_thread_id", "studio_products", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_studio_products_thread_id", table_name="studio_products")
    op.drop_column("studio_products", "thread_id")
    op.drop_index("ix_qx_assets_thread_id", table_name="qx_assets")
    op.drop_column("qx_assets", "thread_id")
