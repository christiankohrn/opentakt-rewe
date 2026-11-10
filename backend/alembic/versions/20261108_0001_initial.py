"""Kunden, Rechnungen, Positionen, Serienpositionen, Optionen."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kunden",
        sa.Column("kunden_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name1", sa.Text(), nullable=False, server_default=""),
        sa.Column("name2", sa.Text(), nullable=False, server_default=""),
        sa.Column("name3", sa.Text(), nullable=False, server_default=""),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("tel1", sa.Text(), nullable=True),
        sa.Column("tel2", sa.Text(), nullable=True),
        sa.Column("tel3", sa.Text(), nullable=True),
        sa.Column("fax", sa.Text(), nullable=True),
        sa.Column("strasse", sa.Text(), nullable=False, server_default=""),
        sa.Column("plz", sa.Text(), nullable=False, server_default=""),
        sa.Column("ort", sa.Text(), nullable=False, server_default=""),
        sa.Column("stundensatz", sa.Numeric(18, 6), nullable=False, server_default="85"),
        sa.Column("umsatzsteuer_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("keine_mehrwertsteuer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("factoring", sa.Integer(), nullable=False, server_default="2"),
    )
    op.create_table(
        "optionen",
        sa.Column("optionen_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("einstellung", sa.Text(), nullable=False, server_default=""),
        sa.Column("e_int", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("e_decimal", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("e_string", sa.Text(), nullable=False, server_default=""),
        sa.Column("e_bool", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "rechnungen",
        sa.Column("rechnungs_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("datum", sa.Date(), nullable=False),
        sa.Column("kunde_id", sa.Integer(), sa.ForeignKey("kunden.kunden_id"), nullable=True),
        sa.Column("name1", sa.Text(), nullable=False, server_default=""),
        sa.Column("name2", sa.Text(), nullable=False, server_default=""),
        sa.Column("name3", sa.Text(), nullable=False, server_default=""),
        sa.Column("strasse", sa.Text(), nullable=False, server_default=""),
        sa.Column("plz", sa.Text(), nullable=False, server_default=""),
        sa.Column("ort", sa.Text(), nullable=False, server_default=""),
        sa.Column("rechnungs_nr", sa.Text(), nullable=True),
        sa.Column("leistungszeitraum", sa.Text(), nullable=False, server_default=""),
        sa.Column("umsatzsteuer_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("keine_mehrwertsteuer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storno_zu_rechnung_id", sa.Integer(), sa.ForeignKey("rechnungen.rechnungs_id"), nullable=True),
        sa.Column("archiv", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("stornierte_rechnung_id", sa.Integer(), nullable=True),
        sa.Column("wiedervorlage_termin", sa.Date(), nullable=True),
        sa.Column("wiederholung_monate", sa.Integer(), nullable=True),
        sa.Column("notizen_intern", sa.Text(), nullable=True),
        sa.Column("brutto", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("netto", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("bezahlt", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("bezahlt_am", sa.Date(), nullable=True),
        sa.Column("factoring", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gedruckt_buchhaltung", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_rechnungen_kunde_id", "rechnungen", ["kunde_id"])
    op.create_index("ix_rechnungen_storno", "rechnungen", ["storno_zu_rechnung_id"])
    op.create_index("ix_rechnungen_wiedervorlage", "rechnungen", ["wiedervorlage_termin"])
    op.create_table(
        "positionen",
        sa.Column("positionen_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rechnung_id", sa.Integer(), sa.ForeignKey("rechnungen.rechnungs_id", ondelete="CASCADE"), nullable=False),
        sa.Column("menge", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("preis", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("naechster_preis", sa.Numeric(18, 6), nullable=True),
        sa.Column("naechste_menge", sa.Numeric(18, 6), nullable=True),
        sa.Column("einmalig", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("bezeichnung", sa.Text(), nullable=False, server_default=""),
        sa.Column("freitext", sa.Text(), nullable=False, server_default=""),
        sa.Column("mengeneinheit", sa.Text(), nullable=False, server_default=""),
        sa.Column("pos_nr", sa.Integer(), nullable=True),
    )
    op.create_index("ix_positionen_rechnung_id", "positionen", ["rechnung_id"])
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


def downgrade() -> None:
    op.drop_table("serienpositionen")
    op.drop_table("positionen")
    op.drop_table("rechnungen")
    op.drop_table("optionen")
    op.drop_table("kunden")
