"""create account table

Revision ID: 441e307d4eb3
Revises: 
Create Date: 2024-07-22 12:00:21.860032

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '441e307d4eb3'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        'user_types',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('description', sa.Unicode(200)),
    )



def downgrade():
    op.drop_table('user_types')
