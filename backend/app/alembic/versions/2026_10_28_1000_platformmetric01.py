"""平台分析指标定义表（指标配置化，新增指标不再改代码）。

Revision ID: platformmetric01
Revises: retailplatform01
Create Date: 2026-10-28 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "platformmetric01"
down_revision: str | None = "retailplatform01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_metric_def",
        sa.Column("code", sa.String(length=32), nullable=False, comment="指标编码(如 PLT-08)"),
        sa.Column("name", sa.String(length=128), nullable=False, comment="指标名称"),
        sa.Column("group", sa.String(length=32), nullable=False, comment="分组：维度/数量/金额/比率"),
        sa.Column("data_type", sa.String(length=16), nullable=False, comment="数据类型：number/percent/string"),
        sa.Column("unit", sa.String(length=16), nullable=True, comment="单位"),
        sa.Column("sensitive", sa.Boolean(), nullable=False, comment="是否敏感字段（页面标红）"),
        sa.Column(
            "expression",
            sa.Text(),
            nullable=False,
            comment="取值表达式：可用 base 变量（orders/intake/shipment/...）与其他指标编码",
        ),
        sa.Column("note", sa.Text(), nullable=True, comment="口径说明"),
        sa.Column("sort", sa.Integer(), nullable=False, comment="列顺序"),
        sa.Column("status", sa.Integer(), nullable=False, comment="状态(0:启用 1:停用)"),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_metric_def")),
        sa.UniqueConstraint("code", name="uq_platform_metric_def_code"),
        comment="平台分析指标定义表",
    )
    with op.batch_alter_table("platform_metric_def", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_platform_metric_def_code"), ["code"], unique=False)
        batch_op.create_index(batch_op.f("ix_platform_metric_def_created_time"), ["created_time"], unique=False)
        batch_op.create_index(batch_op.f("ix_platform_metric_def_id"), ["id"], unique=False)
        batch_op.create_index(batch_op.f("ix_platform_metric_def_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index(batch_op.f("ix_platform_metric_def_uuid"), ["uuid"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("platform_metric_def", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_platform_metric_def_uuid"))
        batch_op.drop_index(batch_op.f("ix_platform_metric_def_is_deleted"))
        batch_op.drop_index(batch_op.f("ix_platform_metric_def_id"))
        batch_op.drop_index(batch_op.f("ix_platform_metric_def_created_time"))
        batch_op.drop_index(batch_op.f("ix_platform_metric_def_code"))
    op.drop_table("platform_metric_def")
