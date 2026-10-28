"""平台指标补「可出性」字段，表达式允许为空（待确认/待做指标先占位）。

Revision ID: platformmetric02
Revises: platformmetric01
Create Date: 2026-10-28 11:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "platformmetric02"
down_revision: str | None = "platformmetric01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "platform_metric_def",
        sa.Column(
            "readiness",
            sa.String(length=16),
            nullable=False,
            server_default="ready",
            comment="可出性：ready 现用可出 / pending 待确认 / todo 待做 / missing 缺数据源",
        ),
    )
    op.alter_column(
        "platform_metric_def",
        "expression",
        existing_type=sa.Text(),
        nullable=True,
        existing_comment="取值表达式：可用 base 变量（orders/intake/shipment/...）与其他指标编码",
    )


def downgrade() -> None:
    op.execute(sa.text("UPDATE platform_metric_def SET expression = '' WHERE expression IS NULL"))
    op.alter_column(
        "platform_metric_def",
        "expression",
        existing_type=sa.Text(),
        nullable=False,
        existing_comment="取值表达式：可用 base 变量（orders/intake/shipment/...）与其他指标编码",
    )
    with op.batch_alter_table("platform_metric_def", schema=None) as batch_op:
        batch_op.drop_column("readiness")
