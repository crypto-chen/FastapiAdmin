"""零售店铺/平台主数据表。

Revision ID: retailshop01
Revises: f246db8af3ec
Create Date: 2026-10-27 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "retailshop01"
down_revision: str | None = "f246db8af3ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "retail_shop",
        sa.Column("source", sa.String(length=32), nullable=False, comment="来源"),
        sa.Column("shop_id", sa.Integer(), nullable=False, comment="店铺编号"),
        sa.Column("shop_name", sa.String(length=128), nullable=True, comment="聚水潭店铺名称"),
        sa.Column("shop_site", sa.String(length=64), nullable=True, comment="平台/站点"),
        sa.Column("platform_shop_name", sa.String(length=128), nullable=True, comment="平台店铺名称"),
        sa.Column("co_id", sa.String(length=64), nullable=True, comment="公司编号"),
        sa.Column("nick", sa.String(length=128), nullable=True, comment="授权账号"),
        sa.Column(
            "session_status",
            sa.Integer(),
            nullable=True,
            comment="授权状态(0未授权 1已过期 2已授权 3无需授权)",
        ),
        sa.Column("session_expired", sa.String(length=64), nullable=True, comment="授权过期时间"),
        sa.Column("group_id", sa.Integer(), nullable=True, comment="分组ID"),
        sa.Column("group_name", sa.String(length=128), nullable=True, comment="分组名称"),
        sa.Column("shop_url", sa.String(length=255), nullable=True, comment="店铺网址"),
        sa.Column("short_name", sa.String(length=128), nullable=True, comment="店铺简称"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True, comment="最近同步时间"),
        sa.Column("raw", sa.JSON(), nullable=True, comment="原始店铺 JSON"),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retail_shop")),
        sa.UniqueConstraint("source", "shop_id", name="uq_retail_shop_source_shop"),
        comment="零售店铺/平台主数据",
    )
    with op.batch_alter_table("retail_shop", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_retail_shop_created_time"), ["created_time"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_shop_id"), ["id"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_shop_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_shop_shop_id"), ["shop_id"], unique=False)
        batch_op.create_index("ix_retail_shop_site", ["shop_site"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_shop_source"), ["source"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_shop_uuid"), ["uuid"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("retail_shop", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_retail_shop_uuid"))
        batch_op.drop_index(batch_op.f("ix_retail_shop_source"))
        batch_op.drop_index("ix_retail_shop_site")
        batch_op.drop_index(batch_op.f("ix_retail_shop_shop_id"))
        batch_op.drop_index(batch_op.f("ix_retail_shop_is_deleted"))
        batch_op.drop_index(batch_op.f("ix_retail_shop_id"))
        batch_op.drop_index(batch_op.f("ix_retail_shop_created_time"))
    op.drop_table("retail_shop")
