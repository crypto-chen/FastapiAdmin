"""订单全链路宽表与构建批次表

Revision ID: 5c1f7a2b9d31
Revises: cd6a5655eba2
Create Date: 2026-10-13 10:30:00.000000

订单全链路（订单明细宽表）:

- ``dwd_order_full_chain``：一行一单，``order_number + calc_version`` 唯一；
  核心字段用物理列，可变字段放 ``extra`` JSON，加减字段零 DDL。
- ``dwd_order_build_run``：每个期间每次构建的批次记录（版本、订单数、质量指标）。

方案见 ``docs/订单全链路数据方案.md``。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5c1f7a2b9d31'
down_revision: str | None = 'cd6a5655eba2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'dwd_order_full_chain',
        sa.Column('order_number', sa.String(length=64), nullable=False, comment='CRM 订单号'),
        sa.Column('period_value', sa.String(length=16), nullable=False, comment='期间(接单月 YYYY-MM)'),
        sa.Column('calc_version', sa.Integer(), nullable=False, comment='计算版本(重算递增)'),
        sa.Column('trade_type', sa.String(length=16), nullable=True, comment='贸易类型(domestic/export)'),
        sa.Column('order_type', sa.String(length=16), nullable=True, comment='订单类型(1批量 2打样 3零售)'),
        sa.Column('customer_id', sa.Integer(), nullable=True, comment='CRM 客户ID'),
        sa.Column('salesman_code', sa.String(length=64), nullable=True, comment='业务员编码(CRM create_id)'),
        sa.Column('order_date', sa.Date(), nullable=True, comment='接单日期'),
        sa.Column('push_date', sa.DateTime(), nullable=True, comment='下推日期'),
        sa.Column('finish_date', sa.DateTime(), nullable=True, comment='齐套入库日期'),
        sa.Column('ship_date', sa.DateTime(), nullable=True, comment='销售出库日期'),
        sa.Column('qty', sa.Numeric(precision=18, scale=4), nullable=True, comment='数量'),
        sa.Column('intake_untaxed', sa.Numeric(precision=18, scale=4), nullable=True, comment='接单未税'),
        sa.Column('ship_untaxed', sa.Numeric(precision=18, scale=4), nullable=True, comment='出货未税'),
        sa.Column('net_shipment', sa.Numeric(precision=18, scale=4), nullable=True, comment='净出货'),
        sa.Column('extra', sa.JSON(), nullable=True, comment='可变字段区(JSON)'),
        sa.Column('source_batch_id', sa.String(length=64), nullable=True, comment='来源批次ID'),
        sa.Column(
            'data_quality_flag',
            sa.String(length=32),
            nullable=True,
            comment='数据质量标记(ok/cost_missing/mo_unlinked/ar_customer_level)',
        ),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('uuid', sa.String(length=64), nullable=False, comment='UUID全局唯一标识'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, comment='是否已删除(0:未删除 1:已删除)'),
        sa.Column('created_time', sa.DateTime(timezone=True), nullable=False, comment='创建时间'),
        sa.Column('updated_time', sa.DateTime(timezone=True), nullable=False, comment='更新时间'),
        sa.Column('deleted_time', sa.DateTime(timezone=True), nullable=True, comment='删除时间'),
        sa.Column('created_id', sa.Integer(), nullable=True, comment='创建人ID'),
        sa.Column('updated_id', sa.Integer(), nullable=True, comment='更新人ID'),
        sa.Column('deleted_id', sa.Integer(), nullable=True, comment='删除人ID'),
        sa.ForeignKeyConstraint(
            ['created_id'], ['sys_user.id'],
            name=op.f('fk_dwd_order_full_chain_created_id_sys_user'), onupdate='CASCADE', ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['deleted_id'], ['sys_user.id'],
            name=op.f('fk_dwd_order_full_chain_deleted_id_sys_user'), onupdate='CASCADE', ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['updated_id'], ['sys_user.id'],
            name=op.f('fk_dwd_order_full_chain_updated_id_sys_user'), onupdate='CASCADE', ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_dwd_order_full_chain')),
        sa.UniqueConstraint('order_number', 'calc_version', name='uq_dwd_order_full_chain_order_version'),
        comment='订单全链路宽表',
    )
    with op.batch_alter_table('dwd_order_full_chain', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dwd_order_full_chain_created_id'), ['created_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_full_chain_created_time'), ['created_time'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_full_chain_customer_id'), ['customer_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_full_chain_deleted_id'), ['deleted_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_full_chain_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_full_chain_is_deleted'), ['is_deleted'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_full_chain_order_number'), ['order_number'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_full_chain_period_value'), ['period_value'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_full_chain_salesman_code'), ['salesman_code'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_full_chain_ship_date'), ['ship_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_full_chain_trade_type'), ['trade_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_full_chain_updated_id'), ['updated_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_full_chain_updated_time'), ['updated_time'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_full_chain_uuid'), ['uuid'], unique=True)

    op.create_table(
        'dwd_order_build_run',
        sa.Column('period_value', sa.String(length=16), nullable=False, comment='期间'),
        sa.Column('calc_version', sa.Integer(), nullable=False, comment='计算版本'),
        sa.Column('status', sa.String(length=16), nullable=False, comment='状态(pending/running/success/failed)'),
        sa.Column('order_count', sa.Integer(), nullable=False, comment='订单数'),
        sa.Column('mo_linked_count', sa.Integer(), nullable=False, comment='关联到生产订单的订单数'),
        sa.Column('cost_missing_count', sa.Integer(), nullable=False, comment='成本缺失订单数'),
        sa.Column('source_batches', sa.JSON(), nullable=True, comment='来源批次清单'),
        sa.Column('error', sa.Text(), nullable=True, comment='错误信息'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True, comment='开始时间'),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True, comment='结束时间'),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('uuid', sa.String(length=64), nullable=False, comment='UUID全局唯一标识'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, comment='是否已删除(0:未删除 1:已删除)'),
        sa.Column('created_time', sa.DateTime(timezone=True), nullable=False, comment='创建时间'),
        sa.Column('updated_time', sa.DateTime(timezone=True), nullable=False, comment='更新时间'),
        sa.Column('deleted_time', sa.DateTime(timezone=True), nullable=True, comment='删除时间'),
        sa.Column('created_id', sa.Integer(), nullable=True, comment='创建人ID'),
        sa.Column('updated_id', sa.Integer(), nullable=True, comment='更新人ID'),
        sa.Column('deleted_id', sa.Integer(), nullable=True, comment='删除人ID'),
        sa.ForeignKeyConstraint(
            ['created_id'], ['sys_user.id'],
            name=op.f('fk_dwd_order_build_run_created_id_sys_user'), onupdate='CASCADE', ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['deleted_id'], ['sys_user.id'],
            name=op.f('fk_dwd_order_build_run_deleted_id_sys_user'), onupdate='CASCADE', ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['updated_id'], ['sys_user.id'],
            name=op.f('fk_dwd_order_build_run_updated_id_sys_user'), onupdate='CASCADE', ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_dwd_order_build_run')),
        comment='订单全链路构建批次',
    )
    with op.batch_alter_table('dwd_order_build_run', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dwd_order_build_run_created_id'), ['created_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_build_run_created_time'), ['created_time'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_build_run_deleted_id'), ['deleted_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_build_run_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_build_run_is_deleted'), ['is_deleted'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_build_run_period_value'), ['period_value'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_build_run_updated_id'), ['updated_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_order_build_run_uuid'), ['uuid'], unique=True)

    # 开放接口应用新增订单全链路权限
    op.add_column(
        'open_client',
        sa.Column(
            'allow_order_detail',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment='是否允许查询订单全链路明细(默认不开放)',
        ),
    )
    op.add_column(
        'open_client',
        sa.Column(
            'allow_cost_fields',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment='是否允许读取成本/毛利/边际贡献类字段(默认不开放)',
        ),
    )
    op.add_column(
        'open_client',
        sa.Column('order_scope', sa.JSON(), nullable=True, comment='允许的订单范围(客户/业务员/贸易类型)，空=不限'),
    )


def downgrade() -> None:
    op.drop_column('open_client', 'order_scope')
    op.drop_column('open_client', 'allow_cost_fields')
    op.drop_column('open_client', 'allow_order_detail')
    op.drop_table('dwd_order_build_run')
    op.drop_table('dwd_order_full_chain')
