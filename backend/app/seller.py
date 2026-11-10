"""Stammdaten und Rechnungslayout-Konfiguration.

Alle unternehmensbezogenen Angaben (Name, Adresse, Bank, Steuer, Fußzeile,
Zahlungsziel) werden dynamisch aus der Datenbank (`optionen`) geladen.
Das Rechnungslayout ist über `RechnungsLayout` entkoppelt, sodass Kunden später
eigene Layouts hinterlegen können, während das Standardlayout rein schwarz-weiß
und ohne Briefpapier/Farben arbeitet.
"""

from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Option


class Bank(NamedTuple):
    name: str
    iban: str
    bic: str


@dataclass
class Stammdaten:
    # Neutrale Beispielwerte. Echte Daten gehören in die Einstellungen
    # (Stammdaten-Seite) und damit in die Datenbank, nicht in den Code.
    # Die IBAN ist das offizielle deutsche Prüfbeispiel der Bundesbank.
    name: str = "Muster GmbH"
    strasse_brief: str = "Musterstraße 1"
    strasse_xml: str = "Musterstrasse 1"
    plz: str = "12345"
    ort: str = "Musterstadt"
    land: str = "DE"
    telefon: str = ""
    email: str = ""
    steuernummer: str = ""
    ust_id: str = ""
    bank_name: str = "Musterbank"
    bank_iban: str = "DE89 3704 0044 0532 0130 00"
    bank_bic: str = "COBADEFFXXX"
    fusszeile: str = ""
    zahlungstext: str = "Zahlung: 10 Tage netto"
    zahlungsziel_tage: int = 10
    einleitungstext: str = "Hiermit stellen wir Ihnen folgende Leistungen in Rechnung:"
    auftrag_referenz: str = "Ihr Auftrag"
    layout_vorlage: str = "standard"

    @property
    def bank(self) -> Bank:
        return Bank(self.bank_name, self.bank_iban, self.bank_bic)

    @property
    def absenderzeile(self) -> str:
        teile = [
            self.name.strip(),
            self.strasse_brief.strip(),
            f"{self.plz.strip()} {self.ort.strip()}".strip(),
        ]
        return " • ".join(t for t in teile if t)


@dataclass
class RechnungsLayout:
    """Layout-Konfiguration für Rechnungen (später pro Kunde/Mandant anpassbar)."""

    vorlage: str = "standard"
    nutze_briefpapier: bool = False
    zeige_qr_code: bool = True
    zeige_absenderzeile: bool = True
    zeige_kontaktdaten: bool = True
    zeige_fusszeile: bool = True


# Rückwärtskompatible Standardwerte für bestehenden Code / Tests ohne DB-Session
STANDARD_STAMMDATEN = Stammdaten()
SELLER_NAME = STANDARD_STAMMDATEN.name
SELLER_STREET_XML = STANDARD_STAMMDATEN.strasse_xml
SELLER_STREET_LETTER = STANDARD_STAMMDATEN.strasse_brief
SELLER_PLZ = STANDARD_STAMMDATEN.plz
SELLER_ORT = STANDARD_STAMMDATEN.ort
SELLER_PHONE = STANDARD_STAMMDATEN.telefon
SELLER_EMAIL = STANDARD_STAMMDATEN.email
STEUERNUMMER = STANDARD_STAMMDATEN.steuernummer
UST_ID = STANDARD_STAMMDATEN.ust_id
ZAHLUNG = STANDARD_STAMMDATEN.zahlungstext
TAGLINE = STANDARD_STAMMDATEN.fusszeile
AUFTRAG = STANDARD_STAMMDATEN.auftrag_referenz
STANDARD_BANK = STANDARD_STAMMDATEN.bank


def bank(stammdaten: Stammdaten | None = None) -> Bank:
    return (stammdaten or STANDARD_STAMMDATEN).bank


def iban_kompakt(iban: str) -> str:
    return (iban or "").replace(" ", "")


_STAMMDATEN_FELDER: tuple[tuple[str, str, str], ...] = (
    ("name", "Stammdaten_Name", STANDARD_STAMMDATEN.name),
    ("strasse_brief", "Stammdaten_StrasseBrief", STANDARD_STAMMDATEN.strasse_brief),
    ("strasse_xml", "Stammdaten_StrasseXml", STANDARD_STAMMDATEN.strasse_xml),
    ("plz", "Stammdaten_Plz", STANDARD_STAMMDATEN.plz),
    ("ort", "Stammdaten_Ort", STANDARD_STAMMDATEN.ort),
    ("land", "Stammdaten_Land", STANDARD_STAMMDATEN.land),
    ("telefon", "Stammdaten_Telefon", STANDARD_STAMMDATEN.telefon),
    ("email", "Stammdaten_Email", STANDARD_STAMMDATEN.email),
    ("steuernummer", "Stammdaten_Steuernummer", STANDARD_STAMMDATEN.steuernummer),
    ("ust_id", "Stammdaten_UstId", STANDARD_STAMMDATEN.ust_id),
    ("bank_name", "Stammdaten_BankName", STANDARD_STAMMDATEN.bank_name),
    ("bank_iban", "Stammdaten_BankIban", STANDARD_STAMMDATEN.bank_iban),
    ("bank_bic", "Stammdaten_BankBic", STANDARD_STAMMDATEN.bank_bic),
    ("fusszeile", "Stammdaten_Fusszeile", STANDARD_STAMMDATEN.fusszeile),
    ("zahlungstext", "Stammdaten_Zahlungstext", STANDARD_STAMMDATEN.zahlungstext),
    ("einleitungstext", "Stammdaten_Einleitungstext", STANDARD_STAMMDATEN.einleitungstext),
    ("auftrag_referenz", "Stammdaten_AuftragReferenz", STANDARD_STAMMDATEN.auftrag_referenz),
    ("layout_vorlage", "Stammdaten_LayoutVorlage", STANDARD_STAMMDATEN.layout_vorlage),
)


def stammdaten_sicherstellen(session: Session) -> None:
    vorhanden = {
        zeile.einstellung: zeile
        for zeile in session.scalars(select(Option).where(Option.einstellung.like("Stammdaten_%")))
    }
    geaendert = False
    for _attr, schluessel, standard in _STAMMDATEN_FELDER:
        if schluessel not in vorhanden:
            session.add(Option(einstellung=schluessel, e_string=standard))
            geaendert = True
    if "Stammdaten_ZahlungszielTage" not in vorhanden:
        session.add(Option(einstellung="Stammdaten_ZahlungszielTage", e_int=STANDARD_STAMMDATEN.zahlungsziel_tage))
        geaendert = True
    if geaendert:
        session.flush()


def stammdaten_lesen(session: Session | None = None) -> Stammdaten:
    if session is None:
        return Stammdaten()
    stammdaten_sicherstellen(session)
    zeilen = {
        zeile.einstellung: zeile
        for zeile in session.scalars(select(Option).where(Option.einstellung.like("Stammdaten_%")))
    }
    werte: dict[str, str | int] = {}
    for attr, schluessel, standard in _STAMMDATEN_FELDER:
        opt = zeilen.get(schluessel)
        werte[attr] = (opt.e_string if opt is not None and opt.e_string is not None else standard)
    tage_opt = zeilen.get("Stammdaten_ZahlungszielTage")
    werte["zahlungsziel_tage"] = int(tage_opt.e_int) if tage_opt is not None and tage_opt.e_int else 10
    return Stammdaten(**werte)


def stammdaten_dict(stammdaten: Stammdaten) -> dict:
    return {
        "name": stammdaten.name,
        "strasse_brief": stammdaten.strasse_brief,
        "strasse_xml": stammdaten.strasse_xml,
        "plz": stammdaten.plz,
        "ort": stammdaten.ort,
        "land": stammdaten.land,
        "telefon": stammdaten.telefon,
        "email": stammdaten.email,
        "steuernummer": stammdaten.steuernummer,
        "ust_id": stammdaten.ust_id,
        "bank_name": stammdaten.bank_name,
        "bank_iban": stammdaten.bank_iban,
        "bank_bic": stammdaten.bank_bic,
        "fusszeile": stammdaten.fusszeile,
        "zahlungstext": stammdaten.zahlungstext,
        "zahlungsziel_tage": stammdaten.zahlungsziel_tage,
        "einleitungstext": stammdaten.einleitungstext,
        "auftrag_referenz": stammdaten.auftrag_referenz,
        "layout_vorlage": stammdaten.layout_vorlage,
    }


def stammdaten_schreiben(session: Session, daten: dict) -> Stammdaten:
    stammdaten_sicherstellen(session)
    zeilen = {
        zeile.einstellung: zeile
        for zeile in session.scalars(select(Option).where(Option.einstellung.like("Stammdaten_%")))
    }
    strasse_brief = str(daten.get("strasse_brief", "")).strip()
    strasse_xml = str(daten.get("strasse_xml", "")).strip() or strasse_brief.replace("ß", "ss")
    werte = {
        **daten,
        "strasse_brief": strasse_brief,
        "strasse_xml": strasse_xml,
    }
    for attr, schluessel, _standard in _STAMMDATEN_FELDER:
        if attr in werte and schluessel in zeilen:
            zeilen[schluessel].e_string = str(werte[attr] or "").strip()
    if "zahlungsziel_tage" in werte and "Stammdaten_ZahlungszielTage" in zeilen:
        tage = int(werte["zahlungsziel_tage"] or 10)
        zeilen["Stammdaten_ZahlungszielTage"].e_int = max(0, min(365, tage))
    session.flush()
    return stammdaten_lesen(session)
