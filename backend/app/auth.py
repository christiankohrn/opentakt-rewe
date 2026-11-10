"""Anmeldung mit Benutzerkonten und Rollen.

Die Sitzung merkt sich Benutzer-ID und Revisionszähler. Ändert der Admin
Passwort oder Rolle, steigt die Revision und fremde Sitzungen verlieren
ihre Gültigkeit.
"""

import re

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Benutzer
from app.security import verify_password

ROLLEN = ("admin", "benutzer")
_BENUTZERNAME = re.compile(r"[a-z0-9._-]{2,80}")


def benutzername_norm(wert: str) -> str:
    return (wert or "").strip().casefold()


def benutzername_gueltig(wert: str) -> bool:
    return _BENUTZERNAME.fullmatch(benutzername_norm(wert) or "") is not None


def authenticate(session: Session, benutzername: str, passwort: str) -> Benutzer | None:
    key = benutzername_norm(benutzername)
    if not key or not passwort:
        return None
    benutzer = session.scalar(select(Benutzer).where(func.lower(Benutzer.benutzername) == key))
    if benutzer is not None and benutzer.auth_quelle == "local" and verify_password(passwort, benutzer.passwort_hash):
        return benutzer if benutzer.aktiv else None
    if get_settings().ldap_enabled:
        from app.ldap_auth import try_ldap_login

        return try_ldap_login(session, key, passwort, vorhanden=benutzer)
    return None


def write_session(request: Request, benutzer: Benutzer) -> None:
    request.session.clear()
    request.session["uid"] = benutzer.benutzer_id
    request.session["rev"] = int(benutzer.session_rev or 0)


def bump_session_rev(benutzer: Benutzer) -> None:
    benutzer.session_rev = int(benutzer.session_rev or 0) + 1


def current_benutzer(request: Request, session: Session, *, allow_passwort_aendern: bool = False) -> Benutzer:
    uid = request.session.get("uid")
    if not uid:
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")
    benutzer = session.get(Benutzer, uid)
    if benutzer is None or not benutzer.aktiv:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")
    if int(request.session.get("rev") or 0) != int(benutzer.session_rev or 0):
        request.session.clear()
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")
    if benutzer.passwort_aendern and not allow_passwort_aendern:
        raise HTTPException(status_code=403, detail="Bitte zuerst das Passwort ändern.")
    return benutzer


def require_login(request: Request, session: Session = Depends(get_db)) -> Benutzer:
    return current_benutzer(request, session)


def require_admin(request: Request, session: Session = Depends(get_db)) -> Benutzer:
    benutzer = current_benutzer(request, session)
    if benutzer.rolle != "admin":
        raise HTTPException(status_code=403, detail="Nur Administrator.")
    return benutzer


def benutzer_dict(benutzer: Benutzer) -> dict:
    return {
        "benutzer_id": benutzer.benutzer_id,
        "benutzername": benutzer.benutzername,
        "name": benutzer.name or "",
        "email": benutzer.email or "",
        "rolle": benutzer.rolle,
        "aktiv": bool(benutzer.aktiv),
        "passwort_aendern": bool(benutzer.passwort_aendern),
        "auth_quelle": benutzer.auth_quelle or "local",
        "totp_aktiv": bool(benutzer.totp_aktiv),
    }
