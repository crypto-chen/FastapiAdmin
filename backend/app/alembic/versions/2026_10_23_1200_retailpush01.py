"""零售数据推送接口：推送批次、订单头、订单明细与开放应用授权字段。

Revision ID: retailpush01
Revises: 0e74123caf97
Create Date: 2026-10-23 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "retailpush01"
down_revision: str | None = "0e74123caf97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- 开放应用：零售推送授权 + 回放任务 ----
    with op.batch_alter_table("open_client", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "allow_retail_sync",
                sa.Boolean(),
                nullable=True,
                comment="是否允许推送零售数据(默认不开放)",
            )
        )
        batch_op.add_column(
            sa.Column(
                "retail_sync_job_id",
                sa.Integer(),
                nullable=True,
                comment="零售推送回放的同步任务ID（空=只落零售表，不回放指标批次）",
            )
        )
    # 先按可空新增并回填，再收紧为 NOT NULL：不保留 server_default，避免与模型漂移
    op.execute("UPDATE open_client SET allow_retail_sync = 0 WHERE allow_retail_sync IS NULL")
    with op.batch_alter_table("open_client", schema=None) as batch_op:
        batch_op.alter_column(
            "allow_retail_sync",
            existing_type=sa.Boolean(),
            nullable=False,
            existing_comment="是否允许推送零售数据(默认不开放)",
        )

    # ---- 推送批次 ----
    op.create_table(
        "retail_sync_batch",
        sa.Column("app_id", sa.String(length=64), nullable=False, comment="调用方应用标识"),
        sa.Column("client_id", sa.Integer(), nullable=True, comment="开放应用ID"),
        sa.Column("request_key", sa.String(length=128), nullable=False, comment="幂等键(请求ID或请求体哈希)"),
        sa.Column("request_id", sa.String(length=128), nullable=True, comment="调用方请求ID"),
        sa.Column("source", sa.String(length=32), nullable=False, comment="数据来源(默认 qimen)"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="状态(success/partial/failed)"),
        sa.Column("payload_hash", sa.String(length=64), nullable=False, comment="原始请求体 SHA256"),
        sa.Column("received_count", sa.Integer(), nullable=False, comment="收到的订单数"),
        sa.Column("created_count", sa.Integer(), nullable=False, comment="新增订单数"),
        sa.Column("updated_count", sa.Integer(), nullable=False, comment="更新订单数"),
        sa.Column("unchanged_count", sa.Integer(), nullable=False, comment="内容未变化的订单数"),
        sa.Column("stale_count", sa.Integer(), nullable=False, comment="旧版本被跳过的订单数"),
        sa.Column("failed_count", sa.Integer(), nullable=False, comment="处理失败的订单数"),
        sa.Column("item_count", sa.Integer(), nullable=False, comment="落库明细行数"),
        sa.Column("periods", sa.JSON(), nullable=True, comment="涉及期间"),
        sa.Column("page_index", sa.Integer(), nullable=True, comment="推送页码"),
        sa.Column("page_size", sa.Integer(), nullable=True, comment="推送页大小"),
        sa.Column("has_next", sa.Boolean(), nullable=False, comment="上游是否还有下一页"),
        sa.Column("params", sa.JSON(), nullable=True, comment="上游查询参数"),
        sa.Column("errors", sa.JSON(), nullable=True, comment="逐单错误"),
        sa.Column("result", sa.JSON(), nullable=True, comment="首次处理结果(幂等重放)"),
        sa.Column("raw_payload", sa.JSON(), nullable=True, comment="原始请求体(超限时省略)"),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retail_sync_batch")),
        sa.UniqueConstraint("app_id", "request_key", name="uq_retail_sync_batch_app_request"),
        comment="零售数据推送批次",
    )
    with op.batch_alter_table("retail_sync_batch", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_retail_sync_batch_app_id"), ["app_id"], unique=False)
        batch_op.create_index(
            "ix_retail_sync_batch_app_created", ["app_id", "created_time"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_retail_sync_batch_created_time"), ["created_time"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_sync_batch_id"), ["id"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_sync_batch_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_sync_batch_uuid"), ["uuid"], unique=True)

    # ---- 订单头 ----
    op.create_table(
        "retail_order",
        sa.Column("order_key", sa.String(length=160), nullable=False, comment="业务唯一键(source:shop_id:so_id/o_id)"),
        sa.Column("source", sa.String(length=32), nullable=False, comment="来源"),
        sa.Column("shop_id", sa.Integer(), nullable=False, comment="店铺编码"),
        sa.Column("so_id", sa.String(length=64), nullable=True, comment="线上单号"),
        sa.Column("o_id", sa.String(length=64), nullable=True, comment="内部单号"),
        sa.Column("co_id", sa.String(length=64), nullable=True, comment="公司编码"),
        sa.Column("status", sa.String(length=32), nullable=True, comment="订单状态"),
        sa.Column("order_from", sa.String(length=32), nullable=True, comment="订单来源"),
        sa.Column("shop_name", sa.String(length=128), nullable=True, comment="店铺名称"),
        sa.Column("shop_site", sa.String(length=64), nullable=True, comment="店铺平台"),
        sa.Column("buyer_id", sa.String(length=64), nullable=True, comment="买家ID"),
        sa.Column("buyer_nick", sa.String(length=128), nullable=True, comment="买家昵称"),
        sa.Column("order_date", sa.DateTime(), nullable=True, comment="下单时间"),
        sa.Column("pay_date", sa.DateTime(), nullable=True, comment="支付时间"),
        sa.Column("modified_time", sa.DateTime(), nullable=True, comment="上游修改时间"),
        sa.Column("plan_delivery_date", sa.DateTime(), nullable=True, comment="计划发货时间"),
        sa.Column("period_value", sa.String(length=16), nullable=False, comment="归属期间(YYYY-MM)"),
        sa.Column("paid_amount", sa.Numeric(precision=18, scale=4), nullable=True, comment="支付金额"),
        sa.Column("pay_amount", sa.Numeric(precision=18, scale=4), nullable=True, comment="应付金额"),
        sa.Column("buyer_paid_amount", sa.Numeric(precision=18, scale=4), nullable=True, comment="买家实付金额"),
        sa.Column("seller_income_amount", sa.Numeric(precision=18, scale=4), nullable=True, comment="卖家实收金额"),
        sa.Column("freight", sa.Numeric(precision=18, scale=4), nullable=True, comment="运费"),
        sa.Column("free_amount", sa.Numeric(precision=18, scale=4), nullable=True, comment="优惠金额"),
        sa.Column("receiver_state", sa.String(length=64), nullable=True, comment="收货省"),
        sa.Column("receiver_city", sa.String(length=64), nullable=True, comment="收货市"),
        sa.Column("receiver_district", sa.String(length=64), nullable=True, comment="收货区"),
        sa.Column("receiver_town", sa.String(length=64), nullable=True, comment="收货街道"),
        sa.Column("remark", sa.Text(), nullable=True, comment="订单备注"),
        sa.Column("seller_flag", sa.String(length=32), nullable=True, comment="卖家标记"),
        sa.Column("item_count", sa.Integer(), nullable=False, comment="明细行数"),
        sa.Column("content_hash", sa.String(length=64), nullable=False, comment="订单内容 SHA256"),
        sa.Column("first_batch_id", sa.String(length=64), nullable=False, comment="首次入库批次"),
        sa.Column("last_batch_id", sa.String(length=64), nullable=False, comment="最近入库批次"),
        sa.Column("raw", sa.JSON(), nullable=True, comment="原始订单 JSON"),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retail_order")),
        sa.UniqueConstraint("order_key", name="uq_retail_order_key"),
        comment="零售订单头（外部推送）",
    )
    with op.batch_alter_table("retail_order", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_retail_order_created_time"), ["created_time"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_order_id"), ["id"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_order_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index("ix_retail_order_modified", ["modified_time"], unique=False)
        batch_op.create_index("ix_retail_order_period_shop", ["period_value", "shop_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_order_period_value"), ["period_value"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_order_shop_id"), ["shop_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_order_so_id"), ["so_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_order_source"), ["source"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_order_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_order_uuid"), ["uuid"], unique=True)
        batch_op.create_index(batch_op.f("ix_retail_order_o_id"), ["o_id"], unique=False)

    # ---- 订单明细 ----
    op.create_table(
        "retail_order_item",
        sa.Column("order_id", sa.Integer(), nullable=False, comment="订单ID"),
        sa.Column("line_key", sa.String(length=128), nullable=False, comment="行唯一键(oi_id 或行哈希)"),
        sa.Column("oi_id", sa.String(length=64), nullable=True, comment="明细行号"),
        sa.Column("sku_id", sa.String(length=64), nullable=True, comment="SKU编码"),
        sa.Column("i_id", sa.String(length=64), nullable=True, comment="商品编码"),
        sa.Column("name", sa.String(length=512), nullable=True, comment="商品名称"),
        sa.Column("properties_value", sa.String(length=512), nullable=True, comment="规格属性"),
        sa.Column("qty", sa.Numeric(precision=18, scale=4), nullable=True, comment="数量"),
        sa.Column("price", sa.Numeric(precision=18, scale=4), nullable=True, comment="单价"),
        sa.Column("base_price", sa.Numeric(precision=18, scale=4), nullable=True, comment="基础单价"),
        sa.Column("amount", sa.Numeric(precision=18, scale=4), nullable=True, comment="明细金额"),
        sa.Column("buyer_paid_amount", sa.Numeric(precision=18, scale=4), nullable=True, comment="买家实付"),
        sa.Column("seller_income_amount", sa.Numeric(precision=18, scale=4), nullable=True, comment="卖家实收"),
        sa.Column("item_pay_amount", sa.Numeric(precision=18, scale=4), nullable=True, comment="明细支付金额"),
        sa.Column("item_status", sa.String(length=32), nullable=True, comment="明细状态"),
        sa.Column("refund_status", sa.String(length=32), nullable=True, comment="退款状态"),
        sa.Column("is_gift", sa.Boolean(), nullable=False, comment="是否赠品"),
        sa.Column("src_combine_sku_id", sa.String(length=64), nullable=True, comment="来源组合装SKU"),
        sa.Column("raw", sa.JSON(), nullable=True, comment="原始明细 JSON"),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["retail_order.id"],
            name=op.f("fk_retail_order_item_order_id_retail_order"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retail_order_item")),
        sa.UniqueConstraint("order_id", "line_key", name="uq_retail_order_item_line"),
        comment="零售订单明细（外部推送）",
    )
    with op.batch_alter_table("retail_order_item", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_retail_order_item_created_time"), ["created_time"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_order_item_id"), ["id"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_order_item_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_order_item_order_id"), ["order_id"], unique=False)
        batch_op.create_index("ix_retail_order_item_sku", ["sku_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_retail_order_item_uuid"), ["uuid"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("retail_order_item", schema=None) as batch_op:
        for name in (
            "ix_retail_order_item_uuid",
            "ix_retail_order_item_sku",
            "ix_retail_order_item_order_id",
            "ix_retail_order_item_is_deleted",
            "ix_retail_order_item_id",
            "ix_retail_order_item_created_time",
        ):
            batch_op.drop_index(name)
    op.drop_table("retail_order_item")

    with op.batch_alter_table("retail_order", schema=None) as batch_op:
        for name in (
            "ix_retail_order_uuid",
            "ix_retail_order_status",
            "ix_retail_order_source",
            "ix_retail_order_so_id",
            "ix_retail_order_shop_id",
            "ix_retail_order_period_value",
            "ix_retail_order_period_shop",
            "ix_retail_order_modified",
            "ix_retail_order_is_deleted",
            "ix_retail_order_id",
            "ix_retail_order_created_time",
            "ix_retail_order_o_id",
        ):
            batch_op.drop_index(name)
    op.drop_table("retail_order")

    with op.batch_alter_table("retail_sync_batch", schema=None) as batch_op:
        for name in (
            "ix_retail_sync_batch_uuid",
            "ix_retail_sync_batch_is_deleted",
            "ix_retail_sync_batch_id",
            "ix_retail_sync_batch_created_time",
            "ix_retail_sync_batch_app_created",
            "ix_retail_sync_batch_app_id",
        ):
            batch_op.drop_index(name)
    op.drop_table("retail_sync_batch")

    with op.batch_alter_table("open_client", schema=None) as batch_op:
        batch_op.drop_column("retail_sync_job_id")
        batch_op.drop_column("allow_retail_sync")
