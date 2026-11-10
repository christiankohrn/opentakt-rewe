"""Einladungen und Passwort-Resets per E-Mail.

Tokens stehen nur als Hash in der Datenbank. Einladungen gelten 7 Tage,
Resets eine Stunde. Die Antworten verraten nie, ob ein Konto existiert.
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import benutzername_norm
from app.branding import PRODUCT_NAME
from app.config import get_settings
from app.mailer import SmtpFehlt, senden_text
from app.models import Benutzer, MailToken
from app.zeit import utcnow

EINLADUNG_TAGE = 7
RESET_STUNDEN = 1
RESET_WARTE_MINUTEN = 10


class MailFehler(Exception):
    pass


def _token_hash(roh: str) -> str:
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()


def email_norm(wert: str | None) -> str | None:
    if wert is None:
        return None
    sauber = wert.strip().lower()
    return sauber or None


def email_gueltig(wert: str | None) -> bool:
    email = email_norm(wert)
    if not email or " " in email or email.count("@") != 1:
        return False
    lokal, domain = email.split("@", 1)
    if not lokal or not domain or domain.startswith(".") or domain.endswith("."):
        return False
    return domain == "localhost" or "." in domain


def smtp_bereit() -> bool:
    settings = get_settings()
    return bool(settings.smtp_host and settings.smtp_from)


def zugangstoken_erstellen(session: Session, benutzer: Benutzer, zweck: str) -> str:
    alt = list(
        session.scalars(
            select(MailToken).where(
                MailToken.benutzer_id == benutzer.benutzer_id,
                MailToken.zweck == zweck,
                MailToken.benutzt_am.is_(None),
            )
        )
    )
    for zeile in alt:
        session.delete(zeile)
    roh = secrets.token_urlsafe(32)
    jetzt = utcnow()
    ttl = timedelta(days=EINLADUNG_TAGE) if zweck == "einladung" else timedelta(hours=RESET_STUNDEN)
    session.add(
        MailToken(
            benutzer_id=benutzer.benutzer_id,
            zweck=zweck,
            token_hash=_token_hash(roh),
            laeuft_ab=jetzt + ttl,
            erstellt=jetzt,
        )
    )
    session.flush()
    return roh


def zugangstoken_suchen(session: Session, roh: str) -> MailToken | None:
    token = (roh or "").strip()
    if not token or len(token) > 200:
        return None
    zeile = session.scalar(select(MailToken).where(MailToken.token_hash == _token_hash(token)))
    if zeile is None or zeile.benutzt_am is not None:
        return None
    if zeile.laeuft_ab <= utcnow():
        return None
    return zeile


def offene_einladung(session: Session, benutzer: Benutzer) -> bool:
    zeile = session.scalar(
        select(MailToken).where(
            MailToken.benutzer_id == benutzer.benutzer_id,
            MailToken.zweck == "einladung",
            MailToken.benutzt_am.is_(None),
        )
    )
    return bool(zeile and zeile.laeuft_ab > utcnow())


def frisches_token(session: Session, benutzer: Benutzer, zweck: str, innerhalb: timedelta) -> MailToken | None:
    jetzt = utcnow()
    zeilen = list(
        session.scalars(
            select(MailToken).where(
                MailToken.benutzer_id == benutzer.benutzer_id,
                MailToken.zweck == zweck,
                MailToken.benutzt_am.is_(None),
            )
        )
    )
    for zeile in zeilen:
        if jetzt - zeile.erstellt < innerhalb:
            return zeile
    return None


def zugangs_url(token: str) -> str:
    basis = get_settings().public_url.rstrip("/")
    return f"{basis}/passwort-setzen?token={token}"


def _anmelde_url() -> str:
    return get_settings().public_url.rstrip("/")


def einladung_text(benutzer: Benutzer, token: str) -> str:
    return (
        f"Hallo {benutzer.name or benutzer.benutzername},\n\n"
        f"für dich wurde ein Zugang zu {PRODUCT_NAME} eingerichtet.\n\n"
        f"Benutzername: {benutzer.benutzername}\n"
        f"Anmeldung: {_anmelde_url()}\n\n"
        f"Bitte setze dein Passwort über diesen Link (gültig {EINLADUNG_TAGE} Tage):\n"
        f"{zugangs_url(token)}\n\n"
        "Falls du diese Mail nicht erwartet hast, kannst du sie ignorieren.\n"
    )


def reset_text(benutzer: Benutzer, token: str) -> str:
    return (
        f"Hallo {benutzer.name or benutzer.benutzername},\n\n"
        f"für dein Konto {benutzer.benutzername} wurde ein neues Passwort angefordert.\n\n"
        f"Link zum Setzen (gültig {RESET_STUNDEN} Stunde):\n"
        f"{zugangs_url(token)}\n\n"
        "Wenn du das nicht warst, ignoriere die Mail. Dein bisheriges Passwort bleibt gültig.\n"
    )


def zugangsmail_senden(session: Session, benutzer: Benutzer, zweck: str) -> None:
    email = email_norm(benutzer.email)
    if not email_gueltig(email):
        raise MailFehler("Gültige E-Mail-Adresse erforderlich.")
    if benutzer.auth_quelle != "local":
        raise MailFehler("Das Passwort wird im Benutzerverzeichnis geändert.")
    if not benutzer.aktiv:
        raise MailFehler("Benutzer ist inaktiv.")
    if not smtp_bereit():
        raise MailFehler("Mailserver ist nicht eingerichtet.")
    token = zugangstoken_erstellen(session, benutzer, zweck)
    if zweck == "reset":
        betreff = f"{PRODUCT_NAME}: Passwort zurücksetzen"
        text = reset_text(benutzer, token)
    else:
        betreff = f"{PRODUCT_NAME}: Zugang einrichten"
        text = einladung_text(benutzer, token)
    try:
        senden_text(email, betreff, text)
    except SmtpFehlt:
        raise MailFehler("Mailserver ist nicht eingerichtet.") from None
    except RuntimeError as exc:
        raise MailFehler(str(exc)) from None


def benutzer_finden(session: Session, kennung: str) -> Benutzer | None:
    key = (kennung or "").strip()
    if not key:
        return None
    benutzer = session.scalar(
        select(Benutzer).where(func.lower(Benutzer.benutzername) == benutzername_norm(key))
    )
    if benutzer is not None:
        return benutzer
    email = email_norm(key)
    if not email:
        return None
    return session.scalar(select(Benutzer).where(func.lower(Benutzer.email) == email))
