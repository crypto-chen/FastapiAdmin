"""成本计算单-工单级成本拆分表

Revision ID: c057b1112026
Revises: 27578c7b66b6
Create Date: 2026-10-17 17:00:00.000000

金蝶成本计算单整月直查会被 ERP 中止（约 10 分钟「正在中止线程」），
按工单（``FSTARTPROORDERID``）单查 1~3 秒，故按工单分批抓取后落本表，
供产品线 PRD-07 实际材料成本（及后续人工/制造费用拆分）聚合。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c057b1112026'
down_revision: Union[str, None] = '27578c7b66b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 表可能已由哨兵迁移或脚本的建表兜底建好（服务器真实出现过 1050 already exists）：
    # 已存在就跳过建表，缺失的外键/索引交给 6233ad1c74ba 补
    if sa.inspect(op.get_bind()).has_table('dwd_cost_bill_workorder'):
        return
    op.create_table(
        'dwd_cost_bill_workorder',
        sa.Column('period_value', sa.String(length=16), nullable=False, comment='期间(YYYY-MM)'),
        sa.Column('work_order', sa.String(length=64), nullable=False, comment='工单号(FPRODUCTNO)'),
        sa.Column('product_code', sa.String(length=64), nullable=True, comment='产品编码'),
        sa.Column('complete_qty', sa.Numeric(precision=20, scale=4), nullable=True, comment='本期完工数量(FCompleteQty)'),
        sa.Column('material_cost', sa.Numeric(precision=20, scale=4), nullable=True, comment='材料成本(成本项目=直接材料)'),
        sa.Column('labor_cost', sa.Numeric(precision=20, scale=4), nullable=True, comment='人工成本(费用项目=直接人工-* 等)'),
        sa.Column('other_cost', sa.Numeric(precision=20, scale=4), nullable=True, comment='其余费用项目(制造费用等)'),
        sa.Column('total_cost', sa.Numeric(precision=20, scale=4), nullable=True, comment='材料+人工+其余'),
        sa.Column('extra', sa.JSON(), nullable=True, comment='明细摘要(JSON)'),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('uuid', sa.String(length=64), nullable=False, comment='UUID全局唯一标识'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, comment='是否已删除(0:未删除 1:已删除)'),
        sa.Column('created_time', sa.DateTime(timezone=True), nullable=False, comment='创建时间'),
        sa.Column('updated_time', sa.DateTime(timezone=True), nullable=False, comment='更新时间'),
        sa.Column('deleted_time', sa.DateTime(timezone=True), nullable=True, comment='删除时间'),
        sa.Column('created_id', sa.Integer(), nullable=True, comment='创建人ID'),
        sa.Column('updated_id', sa.Integer(), nullable=True, comment='更新人ID'),
        sa.Column('deleted_id', sa.Integer(), nullable=True, comment='删除人ID'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_dwd_cost_bill_workorder')),
        sa.UniqueConstraint('period_value', 'work_order', name='uq_dwd_cost_bill_workorder'),
        comment='成本计算单-工单级成本拆分',
    )
    with op.batch_alter_table('dwd_cost_bill_workorder', schema=None) as batch_op:
        batch_op.create_index('ix_dwd_cost_bill_workorder_period', ['period_value'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_cost_bill_workorder_work_order'), ['work_order'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_cost_bill_workorder_uuid'), ['uuid'], unique=True)
        batch_op.create_index(batch_op.f('ix_dwd_cost_bill_workorder_is_deleted'), ['is_deleted'], unique=False)
        batch_op.create_index(batch_op.f('ix_dwd_cost_bill_workorder_created_time'), ['created_time'], unique=False)


def downgrade() -> None:
    op.drop_table('dwd_cost_bill_workorder')
