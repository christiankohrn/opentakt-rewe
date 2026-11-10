"""Benutzerkonten. Nur Administratoren verwalten Konten."""

import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import benutzername_gueltig, benutzername_norm, bump_session_rev
from app.models import Benutzer
from app.security import hash_password

MIN_PASSWORT = 8


def _aktive_admins(session: Session) -> int:
    return (
        session.scalar(
            select(func.count()).select_from(Benutzer).where(Benutzer.rolle == "admin", Benutzer.aktiv.is_(True))
        )
        or 0
    )


def _letzter_admin(session: Session, benutzer: Benutzer) -> bool:
    return benutzer.rolle == "admin" and bool(benutzer.aktiv) and _aktive_admins(session) <= 1


def benutzer_anlegen(
    session: Session,
    benutzername: str,
    name: str,
    email: str,
    passwort: str,
    rolle: str,
    einladung: bool = False,
) -> Benutzer:
    from app.zugangsmail import email_gueltig, smtp_bereit

    key = benutzername_norm(benutzername)
    if not benutzername_gueltig(benutzername):
        raise ValueError("Benutzername: 2 bis 80 Zeichen aus a-z, 0-9, Punkt, Unter- und Bindestrich.")
    if session.scalar(select(Benutzer.benutzer_id).where(func.lower(Benutzer.benutzername) == key)):
        raise ValueError("Diesen Benutzernamen gibt es schon.")
    if rolle not in ("admin", "benutzer"):
        raise ValueError("Rolle ist admin oder benutzer.")
    adresse = (email or "").strip() or None
    if einladung:
        if not email_gueltig(adresse):
            raise ValueError("Gültige E-Mail-Adresse erforderlich.")
        if not smtp_bereit():
            raise ValueError("Mailserver ist nicht eingerichtet.")
        start_hash = hash_password(secrets.token_urlsafe(32))
    else:
        if len(passwort or "") < MIN_PASSWORT:
            raise ValueError(f"Passwort braucht mindestens {MIN_PASSWORT} Zeichen.")
        start_hash = hash_password(passwort)
    benutzer = Benutzer(
        benutzername=key,
        name=(name or "").strip(),
        email=adresse,
        passwort_hash=start_hash,
        rolle=rolle,
        aktiv=True,
        passwort_aendern=True,
    )
    session.add(benutzer)
    session.flush()
    return benutzer


def benutzer_aktualisieren(
    session: Session,
    benutzer_id: int,
    bearbeiter: Benutzer,
    name: str | None = None,
    email: str | None = None,
    rolle: str | None = None,
    aktiv: bool | None = None,
    passwort: str | None = None,
) -> Benutzer:
    benutzer = session.get(Benutzer, benutzer_id)
    if benutzer is None:
        raise ValueError("Benutzer nicht gefunden.")
    selbst = benutzer.benutzer_id == bearbeiter.benutzer_id
    if rolle is not None and rolle != benutzer.rolle:
        if rolle not in ("admin", "benutzer"):
            raise ValueError("Rolle ist admin oder benutzer.")
        if selbst:
            raise ValueError("Die eigene Rolle lässt sich nicht ändern.")
        if _letzter_admin(session, benutzer):
            raise ValueError("Der letzte Administrator bleibt Administrator.")
        benutzer.rolle = rolle
        bump_session_rev(benutzer)
    if aktiv is not None and bool(aktiv) != bool(benutzer.aktiv):
        if selbst:
            raise ValueError("Das eigene Konto lässt sich nicht sperren.")
        if not aktiv and _letzter_admin(session, benutzer):
            raise ValueError("Der letzte Administrator bleibt aktiv.")
        benutzer.aktiv = bool(aktiv)
        bump_session_rev(benutzer)
    if name is not None:
        benutzer.name = name.strip()
    if email is not None:
        benutzer.email = email.strip() or None
    if passwort:
        if benutzer.auth_quelle != "local":
            raise ValueError("Das Passwort wird im Benutzerverzeichnis geändert.")
        if len(passwort) < MIN_PASSWORT:
            raise ValueError(f"Passwort braucht mindestens {MIN_PASSWORT} Zeichen.")
        benutzer.passwort_hash = hash_password(passwort)
        benutzer.passwort_aendern = True
        bump_session_rev(benutzer)
    session.flush()
    return benutzer


def benutzer_loeschen(session: Session, benutzer_id: int, bearbeiter: Benutzer) -> None:
    benutzer = session.get(Benutzer, benutzer_id)
    if benutzer is None:
        raise ValueError("Benutzer nicht gefunden.")
    if benutzer.benutzer_id == bearbeiter.benutzer_id:
        raise ValueError("Das eigene Konto lässt sich nicht löschen.")
    if _letzter_admin(session, benutzer):
        raise ValueError("Der letzte Administrator lässt sich nicht löschen.")
    session.delete(benutzer)
    session.flush()


def eigenes_passwort(session: Session, benutzer: Benutzer, alt: str, neu: str) -> None:
    from app.security import verify_password

    if benutzer.auth_quelle != "local":
        raise ValueError("Das Passwort wird im Benutzerverzeichnis geändert.")
    if not verify_password(alt or "", benutzer.passwort_hash):
        raise ValueError("Altes Passwort falsch.")
    if (alt or "") == (neu or ""):
        raise ValueError("Neues Passwort muss anders sein.")
    if len(neu or "") < MIN_PASSWORT:
        raise ValueError(f"Passwort braucht mindestens {MIN_PASSWORT} Zeichen.")
    benutzer.passwort_hash = hash_password(neu)
    benutzer.passwort_aendern = False
    bump_session_rev(benutzer)
    session.flush()
