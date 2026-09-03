"""qx_assets 独立资产库表（独立生图/关键词/上传，可挂项目）

Revision ID: 0012
Revises: 0011
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "qx_assets",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False, server_default="image"),
        sa.Column("origin", sa.String(16), nullable=False, server_default="agent"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("file_rel", sa.String(500), nullable=True),
        sa.Column("meta", sa.Text(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_qx_assets_kind", "qx_assets", ["kind"])
    op.create_index("ix_qx_assets_status", "qx_assets", ["status"])
    op.create_index("ix_qx_assets_project_id", "qx_assets", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_qx_assets_project_id", table_name="qx_assets")
    op.drop_index("ix_qx_assets_status", table_name="qx_assets")
    op.drop_index("ix_qx_assets_kind", table_name="qx_assets")
    op.drop_table("qx_assets")
