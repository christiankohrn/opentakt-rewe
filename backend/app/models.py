from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Kunde(Base):
    __tablename__ = "kunden"

    kunden_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name1: Mapped[str] = mapped_column(Text, default="")
    name2: Mapped[str] = mapped_column(Text, default="")
    name3: Mapped[str] = mapped_column(Text, default="")
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    tel1: Mapped[str | None] = mapped_column(Text, nullable=True)
    tel2: Mapped[str | None] = mapped_column(Text, nullable=True)
    tel3: Mapped[str | None] = mapped_column(Text, nullable=True)
    fax: Mapped[str | None] = mapped_column(Text, nullable=True)
    strasse: Mapped[str] = mapped_column(Text, default="")
    plz: Mapped[str] = mapped_column(Text, default="")
    ort: Mapped[str] = mapped_column(Text, default="")
    stundensatz: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("85"))
    umsatzsteuer_id: Mapped[str] = mapped_column(Text, default="")
    keine_mehrwertsteuer: Mapped[bool] = mapped_column(Boolean, default=False)

    rechnungen: Mapped[list["Rechnung"]] = relationship(back_populates="kunde")


class Rechnung(Base):
    __tablename__ = "rechnungen"

    rechnungs_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    datum: Mapped[date] = mapped_column(Date)
    kunde_id: Mapped[int | None] = mapped_column(ForeignKey("kunden.kunden_id"), nullable=True, index=True)
    name1: Mapped[str] = mapped_column(Text, default="")
    name2: Mapped[str] = mapped_column(Text, default="")
    name3: Mapped[str] = mapped_column(Text, default="")
    strasse: Mapped[str] = mapped_column(Text, default="")
    plz: Mapped[str] = mapped_column(Text, default="")
    ort: Mapped[str] = mapped_column(Text, default="")
    rechnungs_nr: Mapped[str | None] = mapped_column(Text, nullable=True)
    leistungszeitraum: Mapped[str] = mapped_column(Text, default="")
    umsatzsteuer_id: Mapped[str] = mapped_column(Text, default="")
    keine_mehrwertsteuer: Mapped[bool] = mapped_column(Boolean, default=False)
    storno_zu_rechnung_id: Mapped[int | None] = mapped_column(
        ForeignKey("rechnungen.rechnungs_id"), nullable=True, index=True
    )
    archiv: Mapped[bool] = mapped_column(Boolean, default=False)
    stornierte_rechnung_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wiedervorlage_termin: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    wiederholung_monate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notizen_intern: Mapped[str | None] = mapped_column(Text, nullable=True)
    brutto: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    netto: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    bezahlt: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    bezahlt_am: Mapped[date | None] = mapped_column(Date, nullable=True)
    gedruckt_buchhaltung: Mapped[bool] = mapped_column(Boolean, default=False)
    datev_gesendet: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    kunde: Mapped[Kunde | None] = relationship(back_populates="rechnungen")
    positionen: Mapped[list["Position"]] = relationship(
        back_populates="rechnung",
        cascade="all, delete-orphan",
        order_by="Position.pos_nr",
    )


class Position(Base):
    __tablename__ = "positionen"

    positionen_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rechnung_id: Mapped[int] = mapped_column(
        ForeignKey("rechnungen.rechnungs_id", ondelete="CASCADE"), index=True
    )
    menge: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    preis: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    naechster_preis: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    naechste_menge: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    einmalig: Mapped[bool] = mapped_column(Boolean, default=False)
    bezeichnung: Mapped[str] = mapped_column(Text, default="")
    freitext: Mapped[str] = mapped_column(Text, default="")
    mengeneinheit: Mapped[str] = mapped_column(Text, default="")
    pos_nr: Mapped[int | None] = mapped_column(Integer, nullable=True)

    rechnung: Mapped[Rechnung] = relationship(back_populates="positionen")


class Beleg(Base):
    __tablename__ = "belege"

    beleg_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    dateiname: Mapped[str] = mapped_column(Text, nullable=False)
    art: Mapped[str] = mapped_column(String(20), nullable=False, default="beleg")
    quelle: Mapped[str] = mapped_column(String(20), nullable=False, default="datei")
    betrag: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    datum: Mapped[date | None] = mapped_column(Date, nullable=True)
    partner: Mapped[str] = mapped_column(Text, default="")
    betrag_herkunft: Mapped[str] = mapped_column(String(20), default="")
    datum_herkunft: Mapped[str] = mapped_column(String(20), default="")
    partner_herkunft: Mapped[str] = mapped_column(String(20), default="")
    rechnungsnummer: Mapped[str] = mapped_column(Text, default="")
    text_auszug: Mapped[str] = mapped_column(Text, default="")
    pruefung: Mapped[str] = mapped_column(Text, default="")
    datei: Mapped[str] = mapped_column(Text, nullable=False)
    erstellt: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    datev_gesendet: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    geschaeftspartner_id: Mapped[int | None] = mapped_column(ForeignKey("geschaeftspartner.partner_id"), nullable=True)


class Bewegung(Base):
    __tablename__ = "bewegungen"

    bewegung_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quelle: Mapped[str] = mapped_column(String(20), nullable=False)
    datum: Mapped[date] = mapped_column(Date, nullable=False)
    betrag: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    waehrung: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    gegenpartei: Mapped[str] = mapped_column(Text, default="")
    zweck: Mapped[str] = mapped_column(Text, default="")
    fingerabdruck: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    import_beleg_id: Mapped[int | None] = mapped_column(ForeignKey("belege.beleg_id"), nullable=True)
    beleg_id: Mapped[int | None] = mapped_column(ForeignKey("belege.beleg_id"), nullable=True, unique=True)
    zuordnung: Mapped[str] = mapped_column(String(20), default="")
    geprueft: Mapped[bool] = mapped_column(Boolean, default=False)
    datev_geliefert: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    beleg: Mapped[Beleg | None] = relationship(foreign_keys=[beleg_id])


class BewegungBeleg(Base):
    __tablename__ = "bewegung_belege"
    __table_args__ = (UniqueConstraint("bewegung_id", "beleg_id"),)

    bewegung_beleg_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bewegung_id: Mapped[int] = mapped_column(ForeignKey("bewegungen.bewegung_id"), nullable=False)
    beleg_id: Mapped[int] = mapped_column(ForeignKey("belege.beleg_id"), nullable=False, unique=True)
    zuordnung: Mapped[str] = mapped_column(String(20), default="")


class AbrechnungsKriterium(Base):
    __tablename__ = "abrechnungskriterien"

    kriterium_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schluessel: Mapped[str] = mapped_column(String(20), nullable=False)
    art: Mapped[str] = mapped_column(String(20), nullable=False)
    muster: Mapped[str] = mapped_column(Text, nullable=False)


class Geschaeftspartner(Base):
    __tablename__ = "geschaeftspartner"

    partner_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    ust_id: Mapped[str] = mapped_column(Text, default="")
    steuernummer: Mapped[str] = mapped_column(Text, default="")
    iban: Mapped[str] = mapped_column(Text, default="")
    datum_muster: Mapped[str] = mapped_column(Text, default="")
    nummer_muster: Mapped[str] = mapped_column(Text, default="")
    betrag_muster: Mapped[str] = mapped_column(Text, default="")


class Kategorie(Base):
    __tablename__ = "kategorien"

    kategorie_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schluessel: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    datev_email: Mapped[str] = mapped_column(Text, default="")
    weiterverarbeitung: Mapped[bool] = mapped_column(Boolean, default=False)
    iban: Mapped[str] = mapped_column(Text, default="")
    bic: Mapped[str] = mapped_column(Text, default="")
    reihenfolge: Mapped[int] = mapped_column(Integer, default=0)


class ExportVorgang(Base):
    __tablename__ = "export_vorgaenge"

    export_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    zeitpunkt: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    art: Mapped[str] = mapped_column(String(20), nullable=False, default="email")
    konto: Mapped[str] = mapped_column(String(20), default="")
    zusammenfassung: Mapped[str] = mapped_column(Text, default="")
    daten_json: Mapped[str] = mapped_column(Text, default="{}")


class Benutzer(Base):
    __tablename__ = "benutzer"

    benutzer_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    benutzername: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, default="")
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    passwort_hash: Mapped[str] = mapped_column(Text, nullable=False)
    auth_quelle: Mapped[str] = mapped_column(String(16), default="local")
    rolle: Mapped[str] = mapped_column(String(20), default="benutzer")
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    session_rev: Mapped[int] = mapped_column(Integer, default=0)
    passwort_aendern: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_aktiv: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_bestaetigt_am: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MailToken(Base):
    __tablename__ = "mail_tokens"

    token_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    benutzer_id: Mapped[int] = mapped_column(ForeignKey("benutzer.benutzer_id"), index=True)
    zweck: Mapped[str] = mapped_column(String(16), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    laeuft_ab: Mapped[datetime] = mapped_column(DateTime, index=True)
    benutzt_am: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    erstellt: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class BackupCode(Base):
    __tablename__ = "backup_codes"

    code_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    benutzer_id: Mapped[int] = mapped_column(ForeignKey("benutzer.benutzer_id"), index=True)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    benutzt_am: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    erstellt: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Passkey(Base):
    __tablename__ = "passkeys"

    passkey_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    benutzer_id: Mapped[int] = mapped_column(ForeignKey("benutzer.benutzer_id"), index=True)
    credential_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    transports: Mapped[str | None] = mapped_column(String(120), nullable=True)
    name: Mapped[str] = mapped_column(String(120), default="Passkey")
    erstellt: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    zuletzt_benutzt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditEreignis(Base):
    __tablename__ = "audit_ereignisse"

    ereignis_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    zeitpunkt: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    akteur_id: Mapped[int | None] = mapped_column(ForeignKey("benutzer.benutzer_id"), nullable=True)
    aktion: Mapped[str] = mapped_column(String(64), index=True)
    objekt_typ: Mapped[str] = mapped_column(String(32))
    objekt_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    daten: Mapped[str | None] = mapped_column(Text, nullable=True)


class Option(Base):
    __tablename__ = "optionen"

    optionen_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    einstellung: Mapped[str] = mapped_column(Text, default="")
    e_int: Mapped[int] = mapped_column(Integer, default=0)
    e_decimal: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    e_string: Mapped[str] = mapped_column(Text, default="")
    e_bool: Mapped[bool] = mapped_column(Boolean, default=False)
