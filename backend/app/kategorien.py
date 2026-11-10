"""Konten als Kategorien und globale E-Mail-Adressen für DATEV / Steuerberater."""

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.datev_adressen import ADRESSEN
from app.models import AbrechnungsKriterium, Beleg, Bewegung, ExportVorgang, Kategorie, Option

# schluessel, Anzeigename, Schlüssel in ADRESSEN, weiterverarbeitung, iban, bic
# Startwerte für eine frische Installation. IBAN, BIC und DATEV-Adressen
# trägt jede Installation in den Einstellungen selbst ein.
SEED = (
    ("amex", "Amex", "amex", False, "", ""),
    ("miles", "Lufthansa", "lufthansakk", False, "", ""),
    ("volksbank", "Volksbank", "", True, "", ""),
    ("n26", "N26", "", True, "", ""),
)


def email_fuer(adresse_schluessel: str) -> str:
    if not adresse_schluessel:
        return ""
    return ADRESSEN[adresse_schluessel][0]


def kategorien_sicherstellen(session: Session) -> None:
    vorhanden = session.scalar(select(Kategorie.kategorie_id).limit(1))
    if vorhanden is not None:
        return
    for index, (schluessel, name, adresse, wv, iban, bic) in enumerate(SEED, start=1):
        session.add(Kategorie(
            schluessel=schluessel,
            name=name,
            datev_email=email_fuer(adresse),
            weiterverarbeitung=wv,
            iban=iban,
            bic=bic,
            reihenfolge=index,
        ))
    session.flush()


def kategorien_lesen(session: Session) -> list[Kategorie]:
    kategorien_sicherstellen(session)
    return list(session.scalars(select(Kategorie).order_by(Kategorie.reihenfolge, Kategorie.kategorie_id)))


def kategorie_dict(kategorie: Kategorie) -> dict:
    return {
        "schluessel": kategorie.schluessel,
        "name": kategorie.name,
        "datev_email": kategorie.datev_email or "",
        "weiterverarbeitung": bool(kategorie.weiterverarbeitung),
        "iban": kategorie.iban or "",
        "bic": kategorie.bic or "",
    }


def schluessel_bilden(name: str, vorgabe: str = "") -> str:
    roh = (vorgabe or name).strip().casefold()
    roh = roh.translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
    zeichen = re.sub(r"[^a-z0-9]", "", roh)
    if not zeichen:
        raise ValueError("Der Schlüssel braucht mindestens einen Buchstaben oder eine Ziffer.")
    if len(zeichen) > 20:
        raise ValueError("Der Schlüssel darf höchstens 20 Zeichen haben.")
    return zeichen


def kategorie_anlegen(
    session: Session,
    name: str,
    schluessel: str = "",
    datev_email: str = "",
    weiterverarbeitung: bool = False,
    iban: str = "",
    bic: str = "",
) -> Kategorie:
    anzeige = name.strip()
    if not anzeige:
        raise ValueError("Der Name fehlt.")
    email = datev_email.strip()
    if email and "@" not in email:
        raise ValueError("DATEV-Adresse ist keine E-Mail.")
    key = schluessel_bilden(anzeige, schluessel)
    if session.scalar(select(Kategorie.kategorie_id).where(Kategorie.schluessel == key)):
        raise ValueError("Dieses Konto gibt es schon.")
    naechste = session.scalar(select(func.max(Kategorie.reihenfolge))) or 0
    kategorie = Kategorie(
        schluessel=key,
        name=anzeige,
        datev_email=email,
        weiterverarbeitung=bool(weiterverarbeitung),
        iban=iban.strip().replace(" ", "").upper(),
        bic=bic.strip().replace(" ", "").upper(),
        reihenfolge=int(naechste) + 1,
    )
    session.add(kategorie)
    session.flush()
    return kategorie


def kategorie_aktualisieren(
    session: Session,
    alt_schluessel: str,
    name: str,
    datev_email: str = "",
    weiterverarbeitung: bool = False,
    iban: str = "",
    bic: str = "",
    neuer_schluessel: str = "",
) -> Kategorie:
    kategorie = session.scalar(select(Kategorie).where(Kategorie.schluessel == alt_schluessel))
    if kategorie is None:
        raise ValueError("Kategorie nicht gefunden.")
    anzeige = name.strip()
    if not anzeige:
        raise ValueError("Der Name fehlt.")
    email = datev_email.strip()
    if email and "@" not in email:
        raise ValueError("DATEV-Adresse ist keine E-Mail.")
    ziel_schluessel = schluessel_bilden(anzeige, neuer_schluessel) if neuer_schluessel.strip() else alt_schluessel
    if ziel_schluessel != alt_schluessel:
        vorhanden = session.scalar(select(Kategorie.kategorie_id).where(Kategorie.schluessel == ziel_schluessel))
        if vorhanden is not None:
            raise ValueError(f"Schlüssel {ziel_schluessel} ist schon vergeben.")
        for beleg in session.scalars(select(Beleg).where(Beleg.quelle == alt_schluessel)):
            beleg.quelle = ziel_schluessel
        for bewegung in session.scalars(select(Bewegung).where(Bewegung.quelle == alt_schluessel)):
            bewegung.quelle = ziel_schluessel
        for kriterium in session.scalars(select(AbrechnungsKriterium).where(AbrechnungsKriterium.schluessel == alt_schluessel)):
            kriterium.schluessel = ziel_schluessel
        for vorgang in session.scalars(select(ExportVorgang).where(ExportVorgang.konto == alt_schluessel)):
            vorgang.konto = ziel_schluessel
        kategorie.schluessel = ziel_schluessel
    kategorie.name = anzeige
    kategorie.datev_email = email
    kategorie.weiterverarbeitung = bool(weiterverarbeitung)
    kategorie.iban = iban.strip().replace(" ", "").upper()
    kategorie.bic = bic.strip().replace(" ", "").upper()
    session.flush()
    return kategorie


def kategorie_loeschen(session: Session, schluessel: str) -> None:
    kategorie = session.scalar(select(Kategorie).where(Kategorie.schluessel == schluessel))
    if kategorie is None:
        raise ValueError("Kategorie nicht gefunden.")
    belegt = (
        session.scalar(select(Beleg.beleg_id).where(Beleg.quelle == schluessel).limit(1))
        or session.scalar(select(Bewegung.bewegung_id).where(Bewegung.quelle == schluessel).limit(1))
    )
    if belegt:
        raise ValueError("Das Konto wird noch von Belegen oder Umsätzen verwendet und kann nicht gelöscht werden.")
    for kriterium in list(session.scalars(select(AbrechnungsKriterium).where(AbrechnungsKriterium.schluessel == schluessel))):
        session.delete(kriterium)
    session.delete(kategorie)
    session.flush()


def _option_holen(session: Session, name: str, standard: str = "") -> Option:
    zeile = session.scalar(select(Option).where(Option.einstellung == name))
    if zeile is None:
        zeile = Option(einstellung=name, e_string=standard)
        session.add(zeile)
        session.flush()
    return zeile


def versand_optionen_lesen(session: Session) -> dict:
    stb = _option_holen(session, "StbEmail", "")
    ausgang = _option_holen(session, "DatevAusgangEmail", email_fuer("rechnungsausgang"))
    return {
        "stb_email": (stb.e_string or "").strip(),
        "ausgang_email": (ausgang.e_string or "").strip(),
    }


def versand_optionen_schreiben(session: Session, stb_email: str, ausgang_email: str) -> dict:
    stb_wert = (stb_email or "").strip()
    ausgang_wert = (ausgang_email or "").strip()
    if stb_wert and "@" not in stb_wert:
        raise ValueError("Steuerberater-Adresse ist keine E-Mail.")
    if ausgang_wert and "@" not in ausgang_wert:
        raise ValueError("DATEV-Adresse für Ausgangsrechnungen ist keine E-Mail.")
    stb = _option_holen(session, "StbEmail", "")
    ausgang = _option_holen(session, "DatevAusgangEmail", email_fuer("rechnungsausgang"))
    stb.e_string = stb_wert
    ausgang.e_string = ausgang_wert
    session.flush()
    return versand_optionen_lesen(session)
