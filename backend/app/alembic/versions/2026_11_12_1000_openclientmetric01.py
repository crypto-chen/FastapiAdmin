"""open_client 增加 metric_scope（按指标的授权范围）

Revision ID: openclientmetric01
Revises: platformmetric03
Create Date: 2026-11-12 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "openclientmetric01"
down_revision: str | None = "platformmetric03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 服务器可能已被启动时的自动迁移/哨兵加过该列：存在则跳过，避免 1060 重复列
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("open_client")}
    if "metric_scope" in columns:
        return
    with op.batch_alter_table("open_client", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "metric_scope",
                sa.JSON(),
                nullable=True,
                comment="允许读取的指标编码列表，空=全部启用指标（兼容旧应用）",
            )
        )


def downgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("open_client")}
    if "metric_scope" not in columns:
        return
    with op.batch_alter_table("open_client", schema=None) as batch_op:
        batch_op.drop_column("metric_scope")
