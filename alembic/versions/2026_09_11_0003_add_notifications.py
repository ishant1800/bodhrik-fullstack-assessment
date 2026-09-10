"""create notifications table and notification_type enum

Revision ID: 0003_add_notifications
Revises: 0002_add_user_password_hash
Create Date: 2026-09-11 02:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_add_notifications"
down_revision: str | None = "0002_add_user_password_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create notifications table
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("booking_id", sa.Uuid(), nullable=True),
        sa.Column(
            "type",
            sa.Enum(
                "booking_created",
                "booking_confirmed",
                "booking_cancelled",
                "booking_reminder",
                "booking_completed",
                "booking_overdue",
                name="notification_type",
                native_enum=True,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "is_read", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "booking_id", "type", name="uq_notifications_user_booking_type"
        ),
    )

    # 3. Create indexes
    op.create_index(
        op.f("ix_notifications_user_id"),
        "notifications",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_booking_id"),
        "notifications",
        ["booking_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_type"),
        "notifications",
        ["type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_is_read"),
        "notifications",
        ["is_read"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_user_is_read",
        "notifications",
        ["user_id", "is_read"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_user_created_at",
        "notifications",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    # Drop indexes and table in reverse order
    op.drop_index("ix_notifications_user_created_at", table_name="notifications")
    op.drop_index("ix_notifications_user_is_read", table_name="notifications")
    op.drop_index(op.f("ix_notifications_is_read"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_type"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_booking_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_table("notifications")

    # Drop enum
    op.execute("DROP TYPE IF EXISTS notification_type")
