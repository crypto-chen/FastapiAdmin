"""平台指标每日快照表。

Revision ID: platformmetric03
Revises: platformmetric02
Create Date: 2026-10-28 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "platformmetric03"
down_revision: str | None = "platformmetric02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_metric_snapshot",
        sa.Column("period_value", sa.String(length=16), nullable=False, comment="期间 YYYY-MM"),
        sa.Column("level", sa.String(length=16), nullable=False, comment="维度：shop/platform/total"),
        sa.Column("dim_key", sa.String(length=64), nullable=False, comment="维度键：店铺ID/平台/ALL"),
        sa.Column("dim_name", sa.String(length=128), nullable=True, comment="维度名称"),
        sa.Column("platform", sa.String(length=32), nullable=True, comment="平台"),
        sa.Column("shop_id", sa.Integer(), nullable=True, comment="店铺编号"),
        sa.Column("metric_code", sa.String(length=32), nullable=False, comment="指标编码"),
        sa.Column("value", sa.Numeric(precision=20, scale=4), nullable=False, comment="指标值"),
        sa.Column("calc_version", sa.Integer(), nullable=False, comment="计算版本"),
        sa.Column("batch_id", sa.String(length=64), nullable=False, comment="批次ID"),
        sa.Column("calc_time", sa.DateTime(timezone=True), nullable=False, comment="计算时间"),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_metric_snapshot")),
        sa.UniqueConstraint(
            "period_value", "level", "dim_key", "metric_code", "calc_version",
            name="uq_platform_metric_snapshot",
        ),
        comment="平台指标每日快照",
    )
    with op.batch_alter_table("platform_metric_snapshot", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_platform_metric_snapshot_created_time"), ["created_time"], unique=False)
        batch_op.create_index(batch_op.f("ix_platform_metric_snapshot_id"), ["id"], unique=False)
        batch_op.create_index(batch_op.f("ix_platform_metric_snapshot_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index(batch_op.f("ix_platform_metric_snapshot_metric_code"), ["metric_code"], unique=False)
        batch_op.create_index(batch_op.f("ix_platform_metric_snapshot_period_value"), ["period_value"], unique=False)
        batch_op.create_index("ix_platform_metric_snapshot_period_ver", ["period_value", "calc_version"], unique=False)
        batch_op.create_index(batch_op.f("ix_platform_metric_snapshot_uuid"), ["uuid"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("platform_metric_snapshot", schema=None) as batch_op:
        for name in (
            "ix_platform_metric_snapshot_uuid",
            "ix_platform_metric_snapshot_period_ver",
            "ix_platform_metric_snapshot_period_value",
            "ix_platform_metric_snapshot_metric_code",
            "ix_platform_metric_snapshot_is_deleted",
            "ix_platform_metric_snapshot_id",
            "ix_platform_metric_snapshot_created_time",
        ):
            batch_op.drop_index(name)
    op.drop_table("platform_metric_snapshot")
