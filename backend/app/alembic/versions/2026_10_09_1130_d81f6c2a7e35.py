"""开放接口应用增加业务员明细权限

Revision ID: d81f6c2a7e35
Revises: 203324073db9
Create Date: 2026-10-09 11:30:00.000000

业务员维度指标对外提供后，开放接口新增 ``level=person``：
``open_client.allow_person_detail`` 控制某个接入应用能否查询业务员明细（默认关闭）。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd81f6c2a7e35'
down_revision: str | None = '203324073db9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'open_client',
        sa.Column(
            'allow_person_detail',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment='是否允许查询业务员明细(默认不开放)',
        ),
    )


def downgrade() -> None:
    op.drop_column('open_client', 'allow_person_detail')
