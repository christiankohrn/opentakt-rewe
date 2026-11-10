"""Erster Administrator auf leerer Datenbank.

Absichtlich nur ein Konto: Weitere Benutzer legt der Admin in der
Oberfläche an. Beim ersten Login muss ein eigenes Passwort vergeben
werden.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import benutzername_norm
from app.config import get_settings
from app.models import Benutzer
from app.security import hash_password


def seed_passwort() -> str:
    settings = get_settings()
    return settings.admin_passwort or settings.buchhaltung_password


def seed_if_empty(session: Session) -> Benutzer | None:
    if session.scalar(select(Benutzer.benutzer_id).limit(1)) is not None:
        return None
    benutzername = benutzername_norm(get_settings().admin_benutzer)
    passwort = seed_passwort()
    if not benutzername:
        raise ValueError("ADMIN_BENUTZER ist leer.")
    if not passwort:
        raise ValueError(
            "ADMIN_PASSWORT ist nicht gesetzt. Bitte in der Umgebung setzen und neu starten."
        )
    if len(passwort) < 8:
        raise ValueError("ADMIN_PASSWORT braucht mindestens 8 Zeichen.")
    admin = Benutzer(
        benutzername=benutzername,
        name="Administrator",
        passwort_hash=hash_password(passwort),
        rolle="admin",
        aktiv=True,
        passwort_aendern=True,
    )
    session.add(admin)
    session.flush()
    from app.audit import protokollieren

    protokollieren(session, "seed", admin, "system", "0")
    return admin
