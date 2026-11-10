"""Serienpositionen und Factoring entfernen. Herkunft an Belegen."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_aufraeumen"
down_revision: Union[str, None] = "0002_belege"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_serienpositionen_kunde_id", table_name="serienpositionen")
    op.drop_table("serienpositionen")
    op.drop_column("kunden", "factoring")
    op.drop_column("rechnungen", "factoring")
    op.add_column("belege", sa.Column("partner", sa.Text(), nullable=False, server_default=""))
    op.add_column("belege", sa.Column("betrag_herkunft", sa.String(length=20), nullable=False, server_default=""))
    op.add_column("belege", sa.Column("datum_herkunft", sa.String(length=20), nullable=False, server_default=""))
    op.add_column("belege", sa.Column("partner_herkunft", sa.String(length=20), nullable=False, server_default=""))
    op.add_column("bewegungen", sa.Column("geprueft", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("bewegungen", "geprueft")
    op.drop_column("belege", "partner_herkunft")
    op.drop_column("belege", "datum_herkunft")
    op.drop_column("belege", "betrag_herkunft")
    op.drop_column("belege", "partner")
    op.add_column("rechnungen", sa.Column("factoring", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("kunden", sa.Column("factoring", sa.Integer(), nullable=False, server_default="2"))
    op.create_table(
        "serienpositionen",
        sa.Column("serienpositions_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("menge", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("preis", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("bezeichnung", sa.Text(), nullable=False, server_default=""),
        sa.Column("freitext", sa.Text(), nullable=False, server_default=""),
        sa.Column("mengeneinheit", sa.Text(), nullable=False, server_default=""),
        sa.Column("kunde_id", sa.Integer(), sa.ForeignKey("kunden.kunden_id", ondelete="CASCADE"), nullable=False),
        sa.Column("termin", sa.Date(), nullable=False),
        sa.Column("wiederholung_monat", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_serienpositionen_kunde_id", "serienpositionen", ["kunde_id"])
