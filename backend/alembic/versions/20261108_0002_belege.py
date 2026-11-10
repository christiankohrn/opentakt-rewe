"""Belege und Kontobewegungen, ohne Kontierung."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_belege"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "belege",
        sa.Column("beleg_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("dateiname", sa.Text(), nullable=False),
        sa.Column("art", sa.String(20), nullable=False),
        sa.Column("quelle", sa.String(20), nullable=False),
        sa.Column("betrag", sa.Numeric(18, 2), nullable=True),
        sa.Column("datum", sa.Date(), nullable=True),
        sa.Column("text_auszug", sa.Text(), nullable=False, server_default=""),
        sa.Column("pruefung", sa.Text(), nullable=False, server_default=""),
        sa.Column("datei", sa.Text(), nullable=False),
        sa.Column("erstellt", sa.DateTime(), nullable=False),
        sa.Column("datev_gesendet", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("sha256"),
    )
    op.create_table(
        "bewegungen",
        sa.Column("bewegung_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("quelle", sa.String(20), nullable=False),
        sa.Column("datum", sa.Date(), nullable=False),
        sa.Column("betrag", sa.Numeric(18, 2), nullable=False),
        sa.Column("waehrung", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("gegenpartei", sa.Text(), nullable=False, server_default=""),
        sa.Column("zweck", sa.Text(), nullable=False, server_default=""),
        sa.Column("fingerabdruck", sa.String(64), nullable=False),
        sa.Column("import_beleg_id", sa.Integer(), sa.ForeignKey("belege.beleg_id"), nullable=True),
        sa.Column("beleg_id", sa.Integer(), sa.ForeignKey("belege.beleg_id"), nullable=True),
        sa.Column("zuordnung", sa.String(20), nullable=False, server_default=""),
        sa.UniqueConstraint("fingerabdruck"),
        sa.UniqueConstraint("beleg_id"),
    )


def downgrade() -> None:
    op.drop_table("bewegungen")
    op.drop_table("belege")
