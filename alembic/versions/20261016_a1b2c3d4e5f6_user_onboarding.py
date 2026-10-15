"""user onboarding: preferred genres and the time onboarding was completed

Revision ID: a1b2c3d4e5f6
Revises: 3d09a07238dd
Create Date: 2026-10-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '3d09a07238dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('preferred_genres', postgresql.ARRAY(sa.String(length=40)), server_default='{}', nullable=False))
    op.add_column('users', sa.Column('onboarded_at', sa.DateTime(timezone=True), nullable=True))
    # Everyone who already has an account has been using the app: never show them first-run onboarding.
    op.execute("UPDATE users SET onboarded_at = now()")


def downgrade() -> None:
    op.drop_column('users', 'onboarded_at')
    op.drop_column('users', 'preferred_genres')
