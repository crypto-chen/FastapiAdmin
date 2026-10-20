"""成本计算单工单表：补齐 UserMixin 外键与索引（消除模型与库的结构差异）

``c057b1112026`` 建表时只声明了业务列与唯一键，模型（``UserMixin``）另带
``created_id/updated_id/deleted_id`` 的 ``sys_user`` 外键和单列索引；
不补齐的话 dev 每次启动 autogenerate 都会认为「模型有变更」→ 生成重复迁移 → 多头。

Revision ID: 6233ad1c74ba
Revises: c057b1112026
Create Date: 2026-10-20 10:09:36.299473

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6233ad1c74ba'
down_revision: Union[str, None] = 'c057b1112026'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 幂等：服务器上的表由哨兵迁移建好且可能已带外键/索引，逐项判断再补，
    # 重复执行不会 1061 duplicate key / 1826 duplicate foreign key
    inspector = sa.inspect(op.get_bind())
    indexes = {idx["name"] for idx in inspector.get_indexes('dwd_cost_bill_workorder')}
    fks = {fk["name"] for fk in inspector.get_foreign_keys('dwd_cost_bill_workorder')}
    wanted_indexes = (
        ('ix_dwd_cost_bill_workorder_created_id', 'created_id'),
        ('ix_dwd_cost_bill_workorder_deleted_id', 'deleted_id'),
        ('ix_dwd_cost_bill_workorder_id', 'id'),
        ('ix_dwd_cost_bill_workorder_updated_id', 'updated_id'),
    )
    wanted_fks = (
        ('fk_dwd_cost_bill_workorder_updated_id_sys_user', 'updated_id'),
        ('fk_dwd_cost_bill_workorder_created_id_sys_user', 'created_id'),
        ('fk_dwd_cost_bill_workorder_deleted_id_sys_user', 'deleted_id'),
    )
    missing_indexes = [(name, column) for name, column in wanted_indexes if name not in indexes]
    missing_fks = [(name, column) for name, column in wanted_fks if name not in fks]
    if not (missing_indexes or missing_fks):
        return
    with op.batch_alter_table('dwd_cost_bill_workorder', schema=None) as batch_op:
        for name, column in missing_indexes:
            batch_op.create_index(batch_op.f(name), [column], unique=False)
        for name, column in missing_fks:
            batch_op.create_foreign_key(
                batch_op.f(name), 'sys_user', [column], ['id'], onupdate='CASCADE', ondelete='SET NULL'
            )


def downgrade() -> None:
    # 只回滚本迁移确实存在的对象
    inspector = sa.inspect(op.get_bind())
    indexes = {idx["name"] for idx in inspector.get_indexes('dwd_cost_bill_workorder')}
    fks = {fk["name"] for fk in inspector.get_foreign_keys('dwd_cost_bill_workorder')}
    with op.batch_alter_table('dwd_cost_bill_workorder', schema=None) as batch_op:
        for name in (
            'fk_dwd_cost_bill_workorder_deleted_id_sys_user',
            'fk_dwd_cost_bill_workorder_created_id_sys_user',
            'fk_dwd_cost_bill_workorder_updated_id_sys_user',
        ):
            if name in fks:
                batch_op.drop_constraint(batch_op.f(name), type_='foreignkey')
        for name in (
            'ix_dwd_cost_bill_workorder_updated_id',
            'ix_dwd_cost_bill_workorder_id',
            'ix_dwd_cost_bill_workorder_deleted_id',
            'ix_dwd_cost_bill_workorder_created_id',
        ):
            if name in indexes:
                batch_op.drop_index(batch_op.f(name))
