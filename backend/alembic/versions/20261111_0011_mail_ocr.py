"""OCR-Status an Belegen und Protokoll für den Postfach-Import."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_mail_ocr"
down_revision: Union[str, None] = "0010_sicherheit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("belege", sa.Column("ocr_status", sa.String(length=20), nullable=False, server_default=""))
    op.create_table(
        "mail_importe",
        sa.Column("import_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("message_id", sa.Text(), nullable=False, server_default="", index=True),
        sa.Column("betreff", sa.Text(), nullable=False, server_default=""),
        sa.Column("absender", sa.Text(), nullable=False, server_default=""),
        sa.Column("dateien", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("beleg_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("zeitpunkt", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mail_importe")
    op.drop_column("belege", "ocr_status")
