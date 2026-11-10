"""Lieferstatus (datev_geliefert) an Bewegungen."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_lieferung"
down_revision: Union[str, None] = "0005_erkennung"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bewegungen", sa.Column("datev_geliefert", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("bewegungen", "datev_geliefert")
