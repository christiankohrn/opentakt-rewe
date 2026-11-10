"""Kategorien (weiterverarbeitung, iban, bic) und Export-Vorgänge."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_export_und_konten"
down_revision: Union[str, None] = "0007_ausgang_stb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("kategorien", sa.Column("weiterverarbeitung", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("kategorien", sa.Column("iban", sa.Text(), nullable=False, server_default=""))
    op.add_column("kategorien", sa.Column("bic", sa.Text(), nullable=False, server_default=""))
    op.create_table(
        "export_vorgaenge",
        sa.Column("export_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("zeitpunkt", sa.DateTime(), nullable=False),
        sa.Column("art", sa.String(length=20), nullable=False, server_default="email"),
        sa.Column("konto", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("zusammenfassung", sa.Text(), nullable=False, server_default=""),
        sa.Column("daten_json", sa.Text(), nullable=False, server_default="{}"),
    )
    # Girokonten bekommen die Weiterverarbeitung an den Steuerberater als
    # Startwert. IBAN und BIC trägt jede Installation selbst ein.
    op.execute(sa.text("UPDATE kategorien SET weiterverarbeitung = TRUE WHERE schluessel IN ('n26', 'volksbank')"))


def downgrade() -> None:
    op.drop_table("export_vorgaenge")
    op.drop_column("kategorien", "bic")
    op.drop_column("kategorien", "iban")
    op.drop_column("kategorien", "weiterverarbeitung")
