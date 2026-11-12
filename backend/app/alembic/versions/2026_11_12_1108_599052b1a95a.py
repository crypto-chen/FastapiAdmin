"""自动合并多头

Revision ID: 599052b1a95a
Revises: d396f510a777, openclientmetric01
Create Date: 2026-11-12 11:08:05.901929

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '599052b1a95a'
down_revision: Union[str, None] = ('d396f510a777', 'openclientmetric01')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
