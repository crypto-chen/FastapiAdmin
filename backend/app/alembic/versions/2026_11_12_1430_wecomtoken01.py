"""企业微信连接增加 Token 服务 URL（PHP 兼容模式）。

Revision ID: wecomtoken01
Revises: wecomsync01
Create Date: 2026-11-12 14:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "wecomtoken01"
down_revision: str | None = "wecomsync01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("erp_wecom_connection")}
    if "token_url" in columns:
        return
    with op.batch_alter_table("erp_wecom_connection", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "token_url",
                sa.Text(),
                nullable=True,
                comment="Token服务URL(PHP兼容模式，免填Secret)",
            )
        )


def downgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("erp_wecom_connection")}
    if "token_url" not in columns:
        return
    with op.batch_alter_table("erp_wecom_connection", schema=None) as batch_op:
        batch_op.drop_column("token_url")

