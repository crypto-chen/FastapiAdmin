"""指标定义增加指标分类

Revision ID: b7c1d9e4f2a0
Revises: 15a8c5a1f93a
Create Date: 2026-10-09 10:30:00.000000

新增字段 ``metric_def.category``（指标分类），历史指标统一归入「营销中心-主表」。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7c1d9e4f2a0'
down_revision: str | None = '15a8c5a1f93a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_CATEGORY = "营销中心-主表"


def upgrade() -> None:
    op.add_column(
        'metric_def',
        sa.Column(
            'category',
            sa.String(length=64),
            nullable=False,
            server_default=DEFAULT_CATEGORY,
            comment='指标分类',
        ),
    )
    op.create_index(op.f('ix_metric_def_category'), 'metric_def', ['category'], unique=False)
    # 兜底：把 NULL 或空串的历史数据刷成默认分类（MySQL 加非空列时已按默认值回填）
    op.execute(
        sa.text("UPDATE metric_def SET category = :cat WHERE category IS NULL OR category = ''").bindparams(
            cat=DEFAULT_CATEGORY
        )
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_metric_def_category'), table_name='metric_def')
    op.drop_column('metric_def', 'category')
