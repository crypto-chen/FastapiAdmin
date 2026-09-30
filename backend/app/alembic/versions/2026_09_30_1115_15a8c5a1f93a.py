"""指标定义增加 Excel 科目编码

Revision ID: 15a8c5a1f93a
Revises: 6dba8143ca7a
Create Date: 2026-09-30 11:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '15a8c5a1f93a'
down_revision: Union[str, None] = '6dba8143ca7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'metric_def',
        sa.Column('excel_code', sa.String(length=64), nullable=True, comment='Excel 科目编码（财务口径对照编码）'),
    )
    op.create_index(op.f('ix_metric_def_excel_code'), 'metric_def', ['excel_code'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_metric_def_excel_code'), table_name='metric_def')
    op.drop_column('metric_def', 'excel_code')
