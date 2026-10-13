"""Add an index for recent-note lookups."""

from typing import Sequence, Union

from alembic import op


revision: str = "0002_add_updated_at_index"
down_revision: Union[str, None] = "0001_create_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_notes_updated_at", "notes", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_notes_updated_at", table_name="notes")
