"""Kategorien und Rechnungsnummer am Beleg."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_kategorien"
down_revision: Union[str, None] = "0003_aufraeumen"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Startwerte für frische Installationen. DATEV-Adressen trägt jede
# Installation in den Einstellungen selbst ein.
_SEED = [
    {"schluessel": "amex", "name": "Amex", "datev_email": "", "reihenfolge": 1},
    {"schluessel": "miles", "name": "Lufthansa", "datev_email": "", "reihenfolge": 2},
    {"schluessel": "volksbank", "name": "Volksbank", "datev_email": "", "reihenfolge": 3},
    {"schluessel": "n26", "name": "N26", "datev_email": "", "reihenfolge": 4},
]


def upgrade() -> None:
    op.add_column("belege", sa.Column("rechnungsnummer", sa.Text(), nullable=False, server_default=""))
    op.create_table(
        "kategorien",
        sa.Column("kategorie_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("schluessel", sa.String(length=20), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("datev_email", sa.Text(), nullable=False, server_default=""),
        sa.Column("reihenfolge", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("schluessel"),
    )
    op.bulk_insert(sa.table(
        "kategorien",
        sa.column("schluessel", sa.String),
        sa.column("name", sa.Text),
        sa.column("datev_email", sa.Text),
        sa.column("reihenfolge", sa.Integer),
    ), _SEED)


def downgrade() -> None:
    op.drop_table("kategorien")
    op.drop_column("belege", "rechnungsnummer")
