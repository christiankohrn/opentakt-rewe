"""Rechnungsregeln: Nummern, Summen, Storno, Serien, Mahnungen."""

import re
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Kunde, Option, Position, Rechnung

RECHNUNGSNUMMER = "Rechnungsnummer"
MWST_NORMAL = Decimal("0.19")
MWST_SENKUNG = Decimal("0.16")
MWST_16_START = date(2020, 7, 1)
MWST_19_START = date(2021, 1, 1)
MONATE = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]


def mwst_satz(datum: date) -> Decimal:
    if MWST_16_START <= datum < MWST_19_START:
        return MWST_SENKUNG
    return MWST_NORMAL


def runde_geld(betrag: Decimal) -> Decimal:
    return Decimal(betrag).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def pdf_betraege(netto: Decimal, datum: date, keine_mehrwertsteuer: bool) -> tuple[Decimal, Decimal, Decimal]:
    netto = Decimal(netto)
    if keine_mehrwertsteuer:
        return netto, Decimal("0.00"), netto
    mwst = runde_geld(netto * mwst_satz(datum))
    return netto, mwst, netto + mwst


def format_euro(betrag: Decimal) -> str:
    q = runde_geld(betrag)
    sign = "-" if q < 0 else ""
    q = abs(q)
    whole, frac = f"{q:.2f}".split(".")
    grouped = ""
    while whole:
        grouped = (whole[-3:] + "." + grouped) if grouped else whole[-3:]
        whole = whole[:-3]
    return f"{sign}{grouped},{frac} €"


def format_menge(menge: Decimal) -> str:
    q = runde_geld(menge)
    sign = "-" if q < 0 else ""
    whole, frac = f"{abs(q):.2f}".split(".")
    if frac == "00":
        shown = whole
    elif frac.endswith("0"):
        shown = f"{whole},{frac[0]}"
    else:
        shown = f"{whole},{frac}"
    return sign + shown


def format_rechnungsnummer(heute: date, zaehler: int) -> str:
    return f"{heute:%y}.{zaehler:04d}"


def setze_naechste_nummer(option: Option, text: str, heute: date) -> str:
    treffer = re.fullmatch(r"\d{2}\.(\d{1,6})", text.strip())
    if treffer is None:
        raise ValueError("Format ist yy.nnnn, zum Beispiel 26.3433.")
    zahl = int(treffer.group(1))
    if zahl < 1:
        raise ValueError("Die nächste Nummer muss mindestens 1 sein.")
    option.e_int = zahl - 1
    return format_rechnungsnummer(heute, zahl)


def leistungszeitraum_text(datum: date) -> str:
    return f"{MONATE[datum.month - 1]} {datum.year}"


def add_months(datum: date, monate: int) -> date:
    index = datum.month - 1 + monate
    year = datum.year + index // 12
    month = index % 12 + 1
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return date(year, month, min(datum.day, last.day))


def reverse_charge_text(keine_mehrwertsteuer: bool, umsatzsteuer_id: str | None) -> str | None:
    ust = (umsatzsteuer_id or "").strip()
    if not keine_mehrwertsteuer or not ust:
        return None
    text = f"Steuerschuldnerschaft des Leistungsempfängers {ust}"
    if "FR" in ust:
        text += "\nAutoliquidation"
    return text


def netto_summe(positionen: Iterable[Position]) -> Decimal:
    total = Decimal("0")
    for position in positionen:
        total += Decimal(position.menge) * Decimal(position.preis)
    return total


def berechne(rechnung: Rechnung, positionen: Iterable[Position] | None = None) -> None:
    zeilen = list(positionen if positionen is not None else rechnung.positionen)
    rechnung.netto = netto_summe(zeilen)
    if rechnung.keine_mehrwertsteuer:
        rechnung.brutto = rechnung.netto
    else:
        rechnung.brutto = rechnung.netto * (Decimal("1") + mwst_satz(rechnung.datum))


def fill_kunde(kunde: Kunde, rechnung: Rechnung) -> None:
    rechnung.name1 = kunde.name1 or ""
    rechnung.name2 = kunde.name2 or ""
    rechnung.name3 = kunde.name3 or ""
    rechnung.strasse = kunde.strasse or ""
    rechnung.plz = kunde.plz or ""
    rechnung.ort = kunde.ort or ""
    rechnung.kunde_id = kunde.kunden_id
    rechnung.keine_mehrwertsteuer = bool(kunde.keine_mehrwertsteuer)
    rechnung.umsatzsteuer_id = kunde.umsatzsteuer_id or ""


def _neue_position(**werte) -> Position:
    return Position(
        menge=werte.get("menge", Decimal("0")),
        preis=werte.get("preis", Decimal("0")),
        naechster_preis=werte.get("naechster_preis"),
        naechste_menge=werte.get("naechste_menge"),
        einmalig=bool(werte.get("einmalig", False)),
        bezeichnung=werte.get("bezeichnung") or "",
        freitext=werte.get("freitext") or "",
        mengeneinheit=werte.get("mengeneinheit") or "",
        pos_nr=werte.get("pos_nr"),
    )


def sortierte_positionen(rechnung: Rechnung) -> list[Position]:
    return sorted(
        list(rechnung.positionen),
        key=lambda position: (position.pos_nr if position.pos_nr is not None else 0, position.positionen_id or 0),
    )


def neue_rechnung(session: Session, kunde: Kunde | None, heute: date) -> Rechnung:
    rechnung = Rechnung(
        datum=heute,
        leistungszeitraum=leistungszeitraum_text(heute),
        name1="",
        name2="",
        name3="",
        strasse="",
        plz="",
        ort="",
        umsatzsteuer_id="",
        keine_mehrwertsteuer=False,
        archiv=False,
        netto=Decimal("0"),
        brutto=Decimal("0"),
        bezahlt=Decimal("0"),
        gedruckt_buchhaltung=False,
    )
    session.add(rechnung)
    session.flush()
    if kunde is not None:
        fill_kunde(kunde, rechnung)
    return rechnung


def setze_kunde(rechnung: Rechnung, kunde: Kunde | None, ueberschreiben: bool) -> None:
    if kunde is None:
        rechnung.kunde_id = None
        return
    leer = not (rechnung.name1 or "").strip()
    if ueberschreiben or leer:
        fill_kunde(kunde, rechnung)
        berechne(rechnung)
    else:
        rechnung.kunde_id = kunde.kunden_id


def setze_zahlung(rechnung: Rechnung, betrag: Decimal, datum: date) -> None:
    rechnung.bezahlt = Decimal(betrag)
    rechnung.bezahlt_am = datum


def setze_wiedervorlage(rechnung: Rechnung, termin: date | None, monate: int | None) -> None:
    rechnung.wiedervorlage_termin = termin
    rechnung.wiederholung_monate = monate


def uebernimm_kopf(rechnung: Rechnung, daten) -> None:
    rechnung.datum = daten.datum
    rechnung.name1 = daten.name1 or ""
    rechnung.name2 = daten.name2 or ""
    rechnung.name3 = daten.name3 or ""
    rechnung.strasse = daten.strasse or ""
    rechnung.plz = daten.plz or ""
    rechnung.ort = daten.ort or ""
    rechnung.leistungszeitraum = daten.leistungszeitraum or ""
    rechnung.umsatzsteuer_id = daten.umsatzsteuer_id or ""
    rechnung.keine_mehrwertsteuer = bool(daten.keine_mehrwertsteuer)
    rechnung.archiv = bool(daten.archiv)
    rechnung.notizen_intern = daten.notizen_intern
    if daten.kunde_id is None:
        rechnung.kunde_id = None


def ersetze_positionen(session: Session, rechnung: Rechnung, zeilen) -> None:
    vorhanden = {position.positionen_id: position for position in list(rechnung.positionen)}
    behalten: set[int] = set()
    for index, zeile in enumerate(zeilen):
        if zeile.positionen_id and zeile.positionen_id in vorhanden:
            position = vorhanden[zeile.positionen_id]
            behalten.add(zeile.positionen_id)
        else:
            position = _neue_position()
            rechnung.positionen.append(position)
        position.menge = Decimal(zeile.menge)
        position.preis = Decimal(zeile.preis)
        position.naechster_preis = None if zeile.naechster_preis is None else Decimal(zeile.naechster_preis)
        position.naechste_menge = None if zeile.naechste_menge is None else Decimal(zeile.naechste_menge)
        position.einmalig = bool(zeile.einmalig)
        position.bezeichnung = zeile.bezeichnung or ""
        position.freitext = zeile.freitext or ""
        position.mengeneinheit = zeile.mengeneinheit or ""
        position.pos_nr = index if zeile.pos_nr is None else zeile.pos_nr
    for positionen_id, position in vorhanden.items():
        if positionen_id not in behalten:
            rechnung.positionen.remove(position)
            session.delete(position)
    berechne(rechnung)


def zaehler_holen(session: Session) -> Option:
    stmt = select(Option).where(Option.optionen_id == 1)
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    option = session.scalar(stmt)
    if option is None or option.einstellung != RECHNUNGSNUMMER:
        raise ValueError("Zähler Rechnungsnummer mit OptionenId 1 fehlt.")
    return option


def weise_nummer_zu(session: Session, rechnung: Rechnung, heute: date) -> str:
    if rechnung.rechnungs_nr:
        return rechnung.rechnungs_nr
    option = zaehler_holen(session)
    option.e_int = int(option.e_int) + 1
    rechnung.rechnungs_nr = format_rechnungsnummer(heute, int(option.e_int))
    session.flush()
    return rechnung.rechnungs_nr


def bereite_druck(session: Session, rechnung: Rechnung, heute: date, datum_auf_heute: bool = False) -> str:
    if not rechnung.rechnungs_nr:
        if datum_auf_heute:
            rechnung.datum = heute
            berechne(rechnung)
        return weise_nummer_zu(session, rechnung, heute)
    return rechnung.rechnungs_nr


def kopiere_position(quelle: Position, pos_nr: int, einmalige: bool = False) -> Position | None:
    if not einmalige and quelle.einmalig:
        return None
    preis = Decimal(quelle.preis)
    naechster = quelle.naechster_preis
    if naechster is not None:
        preis = Decimal(naechster)
        naechster = None
    menge = Decimal(quelle.menge)
    naechste_menge = quelle.naechste_menge
    if naechste_menge is not None:
        menge = Decimal(naechste_menge)
        naechste_menge = None
    return _neue_position(
        menge=menge,
        preis=preis,
        naechster_preis=None if naechster is None else Decimal(naechster),
        naechste_menge=None if naechste_menge is None else Decimal(naechste_menge),
        einmalig=quelle.einmalig,
        bezeichnung=quelle.bezeichnung,
        freitext=quelle.freitext,
        mengeneinheit=quelle.mengeneinheit,
        pos_nr=pos_nr,
    )


def kopiere_rechnung(session: Session, quelle: Rechnung, heute: date, positionen: bool = True) -> Rechnung:
    neu = Rechnung(
        datum=heute,
        kunde_id=quelle.kunde_id,
        name1=quelle.name1 or "",
        name2=quelle.name2 or "",
        name3=quelle.name3 or "",
        strasse=quelle.strasse or "",
        plz=quelle.plz or "",
        ort=quelle.ort or "",
        rechnungs_nr=None,
        leistungszeitraum=leistungszeitraum_text(heute),
        umsatzsteuer_id=quelle.umsatzsteuer_id or "",
        keine_mehrwertsteuer=quelle.keine_mehrwertsteuer,
        storno_zu_rechnung_id=quelle.storno_zu_rechnung_id,
        archiv=quelle.archiv,
        wiedervorlage_termin=None,
        wiederholung_monate=None,
        notizen_intern=quelle.notizen_intern,
        netto=Decimal("0"),
        brutto=Decimal("0"),
        bezahlt=Decimal("0"),
        bezahlt_am=None,
        gedruckt_buchhaltung=False,
        stornierte_rechnung_id=quelle.stornierte_rechnung_id,
    )
    if quelle.kunde_id is not None:
        kunde = session.get(Kunde, quelle.kunde_id)
        if kunde is not None:
            fill_kunde(kunde, neu)
    session.add(neu)
    session.flush()
    if positionen:
        nummer = 0
        for position in sortierte_positionen(quelle):
            kopie = kopiere_position(position, nummer, einmalige=False)
            if kopie is None:
                continue
            neu.positionen.append(kopie)
            nummer += 1
    berechne(neu)
    session.flush()
    return neu


def storniere(session: Session, quelle: Rechnung, heute: date) -> Rechnung:
    neu = kopiere_rechnung(session, quelle, heute, positionen=True)
    neu.storno_zu_rechnung_id = quelle.rechnungs_id
    for position in list(neu.positionen):
        position.menge = -Decimal(position.menge)
    berechne(neu)
    quelle.bezahlt = Decimal(quelle.brutto)
    quelle.bezahlt_am = heute
    neu.bezahlt = Decimal(neu.brutto)
    neu.bezahlt_am = heute
    session.flush()
    return neu


def serie_lauf(session: Session, heute: date) -> list[Rechnung]:
    faellig = session.scalars(
        select(Rechnung)
        .where(Rechnung.wiedervorlage_termin.is_not(None))
        .where(Rechnung.wiedervorlage_termin <= heute)
        .options(selectinload(Rechnung.positionen))
    ).all()
    erzeugt: list[Rechnung] = []
    for quelle in faellig:
        alt_termin = quelle.wiedervorlage_termin
        alt_monate = quelle.wiederholung_monate
        neu = kopiere_rechnung(session, quelle, heute, positionen=True)
        if alt_monate is not None and alt_termin is not None:
            neu.wiedervorlage_termin = add_months(alt_termin, int(alt_monate))
            neu.wiederholung_monate = int(alt_monate)
            quelle.wiederholung_monate = None
            quelle.wiedervorlage_termin = None
        else:
            quelle.wiedervorlage_termin = None
        erzeugt.append(neu)
    session.flush()
    return erzeugt


def mahnung_daten(rechnung: Rechnung, heute: date) -> dict:
    betrag = Decimal(rechnung.brutto)
    seit = rechnung.datum + timedelta(days=31)
    bis = heute + timedelta(days=10)
    nummer = rechnung.rechnungs_nr or ""
    text = (
        f"sicherlich ist es Ihnen entgangen unsere Rechnung vom {rechnung.datum:%d.%m.%Y}, "
        f"mit der Rechnungsnummer {nummer}, zu begleichen. Wir möchten daher an die Zahlung erinnern "
        f"und bitten Sie, den offenen Betrag von {format_euro(betrag)} bis zum {bis:%d.%m.%Y} zu begleichen."
        f"\n\nZahlungsverzug besteht seit dem {seit:%d.%m.%Y}"
    )
    return {"betrag": betrag, "seit": seit, "bis": bis, "text": text}


def offene_serie(session: Session) -> list[Rechnung]:
    return list(
        session.scalars(
            select(Rechnung)
            .where(Rechnung.wiedervorlage_termin.is_not(None))
            .order_by(Rechnung.wiedervorlage_termin, Rechnung.rechnungs_id)
        ).all()
    )


def naechste_pos(session: Session, rechnung_id: int) -> int:
    anzahl = session.scalar(select(func.count()).select_from(Position).where(Position.rechnung_id == rechnung_id))
    return int(anzahl or 0)
