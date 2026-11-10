"""Ausgangsrechnungen: Zeitpunkt der StB-Lieferung."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_ausgang_stb"
down_revision: Union[str, None] = "0006_lieferung"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rechnungen", sa.Column("datev_gesendet", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("rechnungen", "datev_gesendet")
