"""Geschäftspartner, Abrechnungskriterien und mehrere Belege je Bewegung."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_erkennung"
down_revision: Union[str, None] = "0004_kategorien"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geschaeftspartner",
        sa.Column("partner_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("ust_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("steuernummer", sa.Text(), nullable=False, server_default=""),
        sa.Column("iban", sa.Text(), nullable=False, server_default=""),
        sa.Column("datum_muster", sa.Text(), nullable=False, server_default=""),
        sa.Column("nummer_muster", sa.Text(), nullable=False, server_default=""),
        sa.Column("betrag_muster", sa.Text(), nullable=False, server_default=""),
    )
    op.create_table(
        "abrechnungskriterien",
        sa.Column("kriterium_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("schluessel", sa.String(length=20), nullable=False),
        sa.Column("art", sa.String(length=20), nullable=False),
        sa.Column("muster", sa.Text(), nullable=False),
    )
    op.create_table(
        "bewegung_belege",
        sa.Column("bewegung_beleg_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("bewegung_id", sa.Integer(), sa.ForeignKey("bewegungen.bewegung_id"), nullable=False),
        sa.Column("beleg_id", sa.Integer(), sa.ForeignKey("belege.beleg_id"), nullable=False),
        sa.Column("zuordnung", sa.String(length=20), nullable=False, server_default=""),
        sa.UniqueConstraint("bewegung_id", "beleg_id"),
        sa.UniqueConstraint("beleg_id"),
    )
    op.add_column("belege", sa.Column("geschaeftspartner_id", sa.Integer(), nullable=True))
    op.create_foreign_key("belege_geschaeftspartner_id_fkey", "belege", "geschaeftspartner", ["geschaeftspartner_id"], ["partner_id"])
    op.execute(
        sa.text(
            "INSERT INTO bewegung_belege (bewegung_id, beleg_id, zuordnung) "
            "SELECT bewegung_id, beleg_id, COALESCE(zuordnung, '') FROM bewegungen WHERE beleg_id IS NOT NULL"
        )
    )
    from app.erkennung import ABRECHNUNGEN, PARTNER

    op.bulk_insert(
        sa.table(
            "abrechnungskriterien",
            sa.column("schluessel", sa.String),
            sa.column("art", sa.String),
            sa.column("muster", sa.Text),
        ),
        [{"schluessel": schluessel, "art": art, "muster": muster} for schluessel, art, muster in ABRECHNUNGEN],
    )
    op.bulk_insert(
        sa.table(
            "geschaeftspartner",
            sa.column("name", sa.Text),
            sa.column("ust_id", sa.Text),
            sa.column("steuernummer", sa.Text),
            sa.column("iban", sa.Text),
            sa.column("datum_muster", sa.Text),
            sa.column("nummer_muster", sa.Text),
            sa.column("betrag_muster", sa.Text),
        ),
        [
            {
                "name": name,
                "ust_id": ust,
                "steuernummer": steuer,
                "iban": iban,
                "datum_muster": datum,
                "nummer_muster": nummer,
                "betrag_muster": betrag,
            }
            for name, ust, steuer, iban, datum, nummer, betrag in PARTNER
        ],
    )


def downgrade() -> None:
    op.drop_constraint("belege_geschaeftspartner_id_fkey", "belege", type_="foreignkey")
    op.drop_column("belege", "geschaeftspartner_id")
    op.drop_table("bewegung_belege")
    op.drop_table("abrechnungskriterien")
    op.drop_table("geschaeftspartner")
