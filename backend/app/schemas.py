from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    benutzername: str = ""
    password: str


class PasswortIn(BaseModel):
    alt: str = ""
    neu: str = ""


class MfaIn(BaseModel):
    code: str = ""


class PasskeyOptionenIn(BaseModel):
    benutzername: str = ""


class PasskeyVerifyIn(BaseModel):
    credential: dict


class PasskeyRegistrierenIn(BaseModel):
    credential: dict
    name: str = ""


class PasskeyUmbenennenIn(BaseModel):
    name: str = ""


class VergessenIn(BaseModel):
    kennung: str = ""


class TokenSetzenIn(BaseModel):
    token: str = ""
    passwort: str = ""


class TotpAktivierenIn(BaseModel):
    code: str = ""


class TotpDeaktivierenIn(BaseModel):
    passwort: str = ""
    code: str = ""


class BenutzerNeuIn(BaseModel):
    benutzername: str
    name: str = ""
    email: str = ""
    passwort: str = ""
    rolle: str = "benutzer"
    einladung: bool = False


class BenutzerPatchIn(BaseModel):
    name: str | None = None
    email: str | None = None
    rolle: str | None = None
    aktiv: bool | None = None
    passwort: str | None = None


class PositionIn(BaseModel):
    positionen_id: int | None = None
    menge: Decimal = Decimal("0")
    preis: Decimal = Decimal("0")
    naechster_preis: Decimal | None = None
    naechste_menge: Decimal | None = None
    einmalig: bool = False
    bezeichnung: str = ""
    freitext: str = ""
    mengeneinheit: str = ""
    pos_nr: int | None = None


class RechnungIn(BaseModel):
    datum: date
    kunde_id: int | None = None
    name1: str = ""
    name2: str = ""
    name3: str = ""
    strasse: str = ""
    plz: str = ""
    ort: str = ""
    leistungszeitraum: str = ""
    umsatzsteuer_id: str = ""
    keine_mehrwertsteuer: bool = False
    archiv: bool = False
    notizen_intern: str | None = None
    positionen: list[PositionIn] = []


class KundeIn(BaseModel):
    name1: str = ""
    name2: str = ""
    name3: str = ""
    email: str | None = None
    tel1: str | None = None
    tel2: str | None = None
    tel3: str | None = None
    fax: str | None = None
    strasse: str = ""
    plz: str = ""
    ort: str = ""
    stundensatz: Decimal = Decimal("85")
    umsatzsteuer_id: str = ""
    keine_mehrwertsteuer: bool = False


class KundeWahl(BaseModel):
    kunde_id: int | None = None
    ueberschreiben: bool = False


class ZahlungIn(BaseModel):
    betrag: Decimal
    datum: date


class WiedervorlageIn(BaseModel):
    termin: date | None = None
    monate: int | None = Field(default=None, ge=1, le=120)


class DruckIn(BaseModel):
    datum_auf_heute: bool = False


class MailIn(BaseModel):
    art: Literal["rechnung", "mahnung"] = "rechnung"


class NeueRechnungIn(BaseModel):
    kunde_id: int | None = None


class NummerIn(BaseModel):
    naechste: str


class KategorieIn(BaseModel):
    name: str
    datev_email: str = ""
    weiterverarbeitung: bool = False
    iban: str = ""
    bic: str = ""
    neuer_schluessel: str = ""


class KategorieNeuIn(BaseModel):
    name: str
    schluessel: str = ""
    datev_email: str = ""
    weiterverarbeitung: bool = False
    iban: str = ""
    bic: str = ""


class VersandOptionenIn(BaseModel):
    stb_email: str = ""
    ausgang_email: str = ""


class StammdatenIn(BaseModel):
    name: str = ""
    strasse_brief: str = ""
    strasse_xml: str = ""
    plz: str = ""
    ort: str = ""
    land: str = "DE"
    telefon: str = ""
    email: str = ""
    steuernummer: str = ""
    ust_id: str = ""
    bank_name: str = ""
    bank_iban: str = ""
    bank_bic: str = ""
    fusszeile: str = ""
    zahlungstext: str = ""
    zahlungsziel_tage: int = Field(default=10, ge=0, le=365)
    einleitungstext: str = ""
    auftrag_referenz: str = ""
    layout_vorlage: str = "standard"


class SmtpIn(BaseModel):
    host: str = ""
    port: int = Field(default=587, ge=1, le=65535)
    benutzer: str = ""
    passwort: str = ""
    absender: str = ""
    tls: bool = True


class AzureIn(BaseModel):
    endpoint: str = ""
    deployment: str = ""
    schluessel: str = ""


class PostfachIn(BaseModel):
    host: str = ""
    port: int = Field(default=993, ge=1, le=65535)
    benutzer: str = ""
    passwort: str = ""
    ordner: str = "INBOX"
    erledigt: str = ""
    quelle: str = "eingang"
    tls: bool = True
