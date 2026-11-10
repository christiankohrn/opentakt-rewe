"""Zwei-Faktor, Passkeys, Mail-Tokens und Audit-Ereignisse."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_sicherheit"
down_revision: Union[str, None] = "0009_benutzer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("benutzer", sa.Column("auth_quelle", sa.String(length=16), nullable=False, server_default="local"))
    op.add_column("benutzer", sa.Column("totp_secret", sa.String(length=64), nullable=True))
    op.add_column("benutzer", sa.Column("totp_aktiv", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("benutzer", sa.Column("totp_bestaetigt_am", sa.DateTime(), nullable=True))
    op.create_table(
        "mail_tokens",
        sa.Column("token_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("benutzer_id", sa.Integer(), sa.ForeignKey("benutzer.benutzer_id"), nullable=False, index=True),
        sa.Column("zweck", sa.String(length=16), nullable=False, index=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True, index=True),
        sa.Column("laeuft_ab", sa.DateTime(), nullable=False, index=True),
        sa.Column("benutzt_am", sa.DateTime(), nullable=True),
        sa.Column("erstellt", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "backup_codes",
        sa.Column("code_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("benutzer_id", sa.Integer(), sa.ForeignKey("benutzer.benutzer_id"), nullable=False, index=True),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("benutzt_am", sa.DateTime(), nullable=True),
        sa.Column("erstellt", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "passkeys",
        sa.Column("passkey_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("benutzer_id", sa.Integer(), sa.ForeignKey("benutzer.benutzer_id"), nullable=False, index=True),
        sa.Column("credential_id", sa.String(length=255), nullable=False, unique=True, index=True),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transports", sa.String(length=120), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False, server_default="Passkey"),
        sa.Column("erstellt", sa.DateTime(), nullable=False),
        sa.Column("zuletzt_benutzt", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "audit_ereignisse",
        sa.Column("ereignis_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("zeitpunkt", sa.DateTime(), nullable=False, index=True),
        sa.Column("akteur_id", sa.Integer(), sa.ForeignKey("benutzer.benutzer_id"), nullable=True),
        sa.Column("aktion", sa.String(length=64), nullable=False, index=True),
        sa.Column("objekt_typ", sa.String(length=32), nullable=False),
        sa.Column("objekt_id", sa.String(length=32), nullable=True),
        sa.Column("daten", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("audit_ereignisse")
    op.drop_table("passkeys")
    op.drop_table("backup_codes")
    op.drop_table("mail_tokens")
    op.drop_column("benutzer", "totp_bestaetigt_am")
    op.drop_column("benutzer", "totp_aktiv")
    op.drop_column("benutzer", "totp_secret")
    op.drop_column("benutzer", "auth_quelle")
