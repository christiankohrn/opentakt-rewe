"""Zwei-Faktor per Authenticator-App (TOTP) plus einmalige Backup-Codes."""

import secrets

import pyotp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackupCode, Benutzer
from app.security import hash_password, verify_password
from app.zeit import utcnow

BACKUP_CODE_ANZAHL = 10
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # ohne 0/O und 1/I


def neues_geheimnis() -> str:
    """Frisches base32-TOTP-Geheimnis für gängige Authenticator-Apps."""
    return pyotp.random_base32()


def totp_uri(secret: str, benutzername: str, aussteller: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=benutzername, issuer_name=aussteller)


def code_pruefen(secret: str | None, code: str) -> bool:
    if not secret or not code:
        return False
    sauber = code.strip().replace(" ", "")
    if not sauber.isdigit():
        return False
    # valid_window=1 verträgt ±30 s Uhrversatz zwischen Server und Handy.
    return pyotp.TOTP(secret).verify(sauber, valid_window=1)


def qr_svg_data_uri(uri: str) -> str:
    """otpauth-URI als base64-SVG zur Anzeige in <img src>."""
    import base64
    import io

    import segno

    qr = segno.make(uri, error="m")
    puffer = io.BytesIO()
    qr.save(puffer, kind="svg", scale=5, border=2)
    b64 = base64.b64encode(puffer.getvalue()).decode("ascii")
    return "data:image/svg+xml;base64," + b64


def _norm_backup(code: str) -> str:
    return code.strip().upper().replace("-", "").replace(" ", "")


def backup_codes_erzeugen(session: Session, benutzer: Benutzer) -> list[str]:
    """Ersetzt alle Backup-Codes durch einen frischen Satz und gibt ihn einmal im Klartext zurück."""
    for zeile in session.scalars(select(BackupCode).where(BackupCode.benutzer_id == benutzer.benutzer_id)):
        session.delete(zeile)
    codes: list[str] = []
    for _ in range(BACKUP_CODE_ANZAHL):
        roh = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(10))
        codes.append(f"{roh[:5]}-{roh[5:]}")
        session.add(BackupCode(benutzer_id=benutzer.benutzer_id, code_hash=hash_password(roh), erstellt=utcnow()))
    return codes


def backup_code_verbrauchen(session: Session, benutzer: Benutzer, code: str) -> bool:
    roh = _norm_backup(code)
    if not roh:
        return False
    for zeile in session.scalars(
        select(BackupCode).where(
            BackupCode.benutzer_id == benutzer.benutzer_id, BackupCode.benutzt_am.is_(None)
        )
    ):
        if verify_password(roh, zeile.code_hash):
            zeile.benutzt_am = utcnow()
            return True
    return False


def backup_codes_uebrig(session: Session, benutzer: Benutzer) -> int:
    return int(
        session.query(BackupCode)
        .filter(BackupCode.benutzer_id == benutzer.benutzer_id, BackupCode.benutzt_am.is_(None))
        .count()
    )


def totp_loeschen(session: Session, benutzer: Benutzer) -> None:
    for zeile in session.scalars(select(BackupCode).where(BackupCode.benutzer_id == benutzer.benutzer_id)):
        session.delete(zeile)
    benutzer.totp_secret = None
    benutzer.totp_aktiv = False
    benutzer.totp_bestaetigt_am = None
