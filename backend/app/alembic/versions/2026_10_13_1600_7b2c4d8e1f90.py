"""标准字段增加指标编码

Revision ID: 7b2c4d8e1f90
Revises: 4b2df2b6888d
Create Date: 2026-10-13 16:00:00.000000

订单全链路字段要与财务底稿的 ORD-xx 编码一一对应，
``meta_standard_field`` 增加 ``excel_code``（与 ``metric_def.excel_code`` 同义）。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7b2c4d8e1f90'
down_revision: str | None = '4b2df2b6888d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'meta_standard_field',
        sa.Column('excel_code', sa.String(length=64), nullable=True, comment='指标编码（财务底稿 ORD-xx 等）'),
    )
    op.create_index(
        op.f('ix_meta_standard_field_excel_code'), 'meta_standard_field', ['excel_code'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_meta_standard_field_excel_code'), table_name='meta_standard_field')
    op.drop_column('meta_standard_field', 'excel_code')
