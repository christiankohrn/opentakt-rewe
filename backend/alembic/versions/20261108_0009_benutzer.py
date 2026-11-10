"""Benutzerkonten mit Rollen."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_benutzer"
down_revision: Union[str, None] = "0008_export_und_konten"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "benutzer",
        sa.Column("benutzer_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("benutzername", sa.String(length=80), nullable=False),
        sa.Column("name", sa.Text(), nullable=False, server_default=""),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("passwort_hash", sa.Text(), nullable=False),
        sa.Column("rolle", sa.String(length=20), nullable=False, server_default="benutzer"),
        sa.Column("aktiv", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("session_rev", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passwort_aendern", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("benutzername"),
    )


def downgrade() -> None:
    op.drop_table("benutzer")
