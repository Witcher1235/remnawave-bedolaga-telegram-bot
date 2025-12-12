from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "e3c1e0b5b4a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tochka_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("payment_id", sa.String(length=128), nullable=False, unique=True),
        sa.Column("amount_kopeks", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="RUB"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column(
            "is_paid",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("checkout_url", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("callback_payload", sa.JSON(), nullable=True),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="SET NULL"),
    )

    op.create_index("ix_tochka_payments_id", "tochka_payments", ["id"])
    op.create_index("ix_tochka_payments_user_id", "tochka_payments", ["user_id"])
    op.create_index("ix_tochka_payments_payment_id", "tochka_payments", ["payment_id"])
    op.create_index("ix_tochka_payments_transaction_id", "tochka_payments", ["transaction_id"])


def downgrade() -> None:
    op.drop_index("ix_tochka_payments_transaction_id", table_name="tochka_payments")
    op.drop_index("ix_tochka_payments_payment_id", table_name="tochka_payments")
    op.drop_index("ix_tochka_payments_user_id", table_name="tochka_payments")
    op.drop_index("ix_tochka_payments_id", table_name="tochka_payments")
    op.drop_table("tochka_payments")
