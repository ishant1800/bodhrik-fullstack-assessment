"""add password_hash column to users table

Revision ID: 0002_add_user_password_hash
Revises: 0001_initial_schema
Create Date: 2026-09-10 19:30:00.000000

"""

import secrets
from collections.abc import Sequence

import bcrypt
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_add_user_password_hash"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add column as nullable first to safely accommodate existing records
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=255), nullable=True),
    )

    # 2. Backfill existing records with a structurally valid, unusable bcrypt hash
    # generated from a random 256-bit secret so that existing rows satisfy NOT NULL
    # without exposing any plaintext password or allowing unauthorized logins.
    random_secret = secrets.token_hex(32)
    unusable_hash = bcrypt.hashpw(
        random_secret.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    users_table = sa.table(
        "users",
        sa.column("password_hash", sa.String),
    )
    op.execute(
        users_table.update()
        .where(users_table.c.password_hash.is_(None))
        .values(password_hash=unusable_hash)
    )

    # 3. Alter column to enforce NOT NULL constraint
    op.alter_column(
        "users",
        "password_hash",
        existing_type=sa.String(length=255),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("users", "password_hash")
