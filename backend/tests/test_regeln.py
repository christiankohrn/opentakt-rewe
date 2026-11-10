from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.domain import (
    add_months,
    berechne,
    bereite_druck,
    format_euro,
    kopiere_rechnung,
    mahnung_daten,
    mwst_satz,
    neue_rechnung,
    pdf_betraege,
    reverse_charge_text,
    runde_geld,
    serie_lauf,
    setze_naechste_nummer,
    storniere,
    zaehler_holen,
)
from app.epc import epc_payload
from app.models import Kunde, Option, Position, Rechnung
from app.routes import rechnungen, rechnungen_filtern, rechnungen_summen
from app.seller import bank


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", future=True)

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as db:
        db.add(Option(optionen_id=1, einstellung="Rechnungsnummer", e_int=3431, e_decimal=Decimal("0"), e_string="", e_bool=False))
        db.add(Option(optionen_id=3, einstellung="Rechnungsnummer", e_int=0, e_decimal=Decimal("0"), e_string="", e_bool=False))
        db.commit()
        yield db


def test_nummer_format_und_nur_zaehler_eins(session):
    rechnung = neue_rechnung(session, None, date(2026, 11, 8))
    assert rechnung.rechnungs_nr is None
    nummer = bereite_druck(session, rechnung, date(2026, 11, 8))
    assert nummer == "26.3432"
    assert session.get(Option, 1).e_int == 3432
    assert session.get(Option, 3).e_int == 0
    assert bereite_druck(session, rechnung, date(2027, 1, 1)) == "26.3432"
    weitere = neue_rechnung(session, None, date(2009, 5, 1))
    assert bereite_druck(session, weitere, date(2009, 5, 1)) == "09.3433"


def test_mwst_zeitraeume_und_pdf_rundung():
    rechnung = Rechnung(datum=date(2020, 6, 30), keine_mehrwertsteuer=False)
    position = Position(menge=Decimal("1"), preis=Decimal("10.01"))
    berechne(rechnung, [position])
    assert rechnung.netto == Decimal("10.01")
    assert rechnung.brutto == Decimal("10.01") * Decimal("1.19")
    assert mwst_satz(date(2020, 6, 30)) == Decimal("0.19")

    rechnung.datum = date(2020, 7, 1)
    berechne(rechnung, [position])
    assert rechnung.brutto == Decimal("10.01") * Decimal("1.16")
    rechnung.datum = date(2020, 12, 31)
    berechne(rechnung, [position])
    assert rechnung.brutto == Decimal("10.01") * Decimal("1.16")
    rechnung.datum = date(2021, 1, 1)
    berechne(rechnung, [position])
    assert rechnung.brutto == Decimal("10.01") * Decimal("1.19")
    assert rechnung.brutto == Decimal("11.9119")

    rechnung.keine_mehrwertsteuer = True
    berechne(rechnung, [position])
    assert rechnung.brutto == rechnung.netto == Decimal("10.01")

    netto, mwst, brutto = pdf_betraege(Decimal("10.01"), date(2026, 11, 8), False)
    assert mwst == Decimal("1.90")
    assert brutto == Decimal("11.91")
    assert runde_geld(Decimal("1.005")) == Decimal("1.01")
    assert runde_geld(Decimal("-1.005")) == Decimal("-1.01")


def test_reverse_charge_nur_mit_fr_und_ohne_mwst():
    assert reverse_charge_text(True, "FR123") == "Steuerschuldnerschaft des Leistungsempfängers FR123\nAutoliquidation"
    assert reverse_charge_text(True, "DE123") == "Steuerschuldnerschaft des Leistungsempfängers DE123"
    assert reverse_charge_text(False, "FR123") is None
    assert reverse_charge_text(True, "  ") is None


def test_mahnung_voller_brutto_ohne_abzug():
    rechnung = Rechnung(
        datum=date(2026, 1, 1),
        rechnungs_nr="26.1000",
        brutto=Decimal("119.00"),
        bezahlt=Decimal("20.00"),
    )
    daten = mahnung_daten(rechnung, date(2026, 3, 1))
    assert daten["betrag"] == Decimal("119.00")
    assert "119,00 €" in daten["text"]
    assert "99,00" not in daten["text"]
    assert daten["seit"] == date(2026, 2, 1)
    assert "01.02.2026" in daten["text"]
    assert daten["bis"] == date(2026, 3, 11)
    assert "26.1000" in daten["text"]


def test_epc_zweck_ist_rechnungsnummer():
    payload = epc_payload(
        "Muster GmbH",
        "DE89 3704 0044 0532 0130 00",
        "COBADEFFXXX",
        Decimal("11.91"),
        "26.3432",
    )
    assert payload.startswith("BCD\n2\n1\nSCT\nCOBADEFFXXX\nMuster GmbH\n")
    assert "DE89370400440532013000" in payload
    assert "EUR11.91" in payload
    assert "26.3432" in payload
    with pytest.raises(ValueError):
        epc_payload("Muster GmbH", "DE89", "COBADEFFXXX", Decimal("0"), "26.1")


def test_nur_eine_bank():
    assert bank().name == "Musterbank"
    assert bank().bic == "COBADEFFXXX"
    assert "factoring" not in Kunde.__table__.columns
    assert "factoring" not in Rechnung.__table__.columns
    assert "serienpositionen" not in Kunde.metadata.tables


def _kunde(session, name="Alt GmbH") -> Kunde:
    kunde = Kunde(
        name1=name,
        name2="",
        name3="",
        strasse="Altstr. 1",
        plz="12345",
        ort="Musterstadt",
        stundensatz=Decimal("85"),
        umsatzsteuer_id="DE123",
        keine_mehrwertsteuer=False,
    )
    session.add(kunde)
    session.flush()
    return kunde


def test_storno_negiert_und_markiert_beide_bezahlt(session):
    heute = date(2026, 11, 8)
    kunde = _kunde(session)
    rechnung = neue_rechnung(session, kunde, date(2026, 1, 15))
    rechnung.positionen.append(Position(
        menge=Decimal("1"), preis=Decimal("10"), bezeichnung="Einmal", einmalig=True,
        freitext="", mengeneinheit="", pos_nr=0,
    ))
    rechnung.positionen.append(Position(
        menge=Decimal("2"), preis=Decimal("5"), naechster_preis=Decimal("7"), naechste_menge=Decimal("3"),
        bezeichnung="Abo", einmalig=False, freitext="", mengeneinheit="Std", pos_nr=1,
    ))
    berechne(rechnung)
    rechnung.rechnungs_nr = "26.1000"
    rechnung.bezahlt = Decimal("1")
    rechnung.gedruckt_buchhaltung = True
    kunde.name1 = "Neu GmbH"
    kunde.strasse = "Neustr. 9"
    session.flush()

    neu = storniere(session, rechnung, heute)
    assert neu.rechnungs_nr is None
    assert neu.storno_zu_rechnung_id == rechnung.rechnungs_id
    assert neu.name1 == "Neu GmbH"
    assert neu.strasse == "Neustr. 9"
    assert len(list(neu.positionen)) == 1
    position = list(neu.positionen)[0]
    assert position.menge == Decimal("-3")
    assert position.preis == Decimal("7")
    assert position.naechster_preis is None
    assert position.naechste_menge is None
    assert rechnung.bezahlt == rechnung.brutto
    assert rechnung.bezahlt_am == heute
    assert neu.bezahlt == neu.brutto
    assert neu.bezahlt_am == heute
    assert neu.brutto < 0
    assert neu.gedruckt_buchhaltung is False
    assert neu.wiedervorlage_termin is None


def test_serie_eine_periode_ohne_aufholen(session):
    heute = date(2026, 11, 8)
    kunde = _kunde(session)
    rechnung = neue_rechnung(session, kunde, date(2026, 1, 1))
    rechnung.rechnungs_nr = "26.1000"
    rechnung.bezahlt = Decimal("50")
    rechnung.bezahlt_am = date(2026, 2, 1)
    rechnung.gedruckt_buchhaltung = True
    rechnung.wiedervorlage_termin = date(2026, 8, 8)
    rechnung.wiederholung_monate = 1
    rechnung.notizen_intern = "intern"
    rechnung.positionen.append(Position(
        menge=Decimal("1"), preis=Decimal("10"), bezeichnung="einmal", einmalig=True,
        freitext="", mengeneinheit="", pos_nr=0,
    ))
    rechnung.positionen.append(Position(
        menge=Decimal("2"), preis=Decimal("5"), naechster_preis=Decimal("8"), naechste_menge=Decimal("4"),
        bezeichnung="serie", einmalig=False, freitext="", mengeneinheit="", pos_nr=1,
    ))
    berechne(rechnung)
    kunde.name1 = "Neu GmbH"
    kunde.ort = "Köln"
    spaeter = neue_rechnung(session, kunde, heute)
    spaeter.wiedervorlage_termin = date(2026, 12, 1)
    spaeter.wiederholung_monate = 1
    session.flush()

    erzeugt = serie_lauf(session, heute)
    assert len(erzeugt) == 1
    neu = erzeugt[0]
    assert rechnung.wiedervorlage_termin is None
    assert rechnung.wiederholung_monate is None
    assert rechnung.rechnungs_nr == "26.1000"
    assert neu.rechnungs_nr is None
    assert neu.bezahlt == 0
    assert neu.bezahlt_am is None
    assert neu.gedruckt_buchhaltung is False
    assert neu.datum == heute
    assert neu.leistungszeitraum == "November 2026"
    assert neu.wiedervorlage_termin == date(2026, 9, 8)
    assert neu.wiederholung_monate == 1
    assert neu.name1 == "Neu GmbH"
    assert neu.ort == "Köln"
    assert neu.notizen_intern == "intern"
    assert len(list(neu.positionen)) == 1
    position = list(neu.positionen)[0]
    assert position.preis == Decimal("8")
    assert position.menge == Decimal("4")
    assert position.naechster_preis is None
    assert position.einmalig is False
    assert spaeter.wiedervorlage_termin == date(2026, 12, 1)
    assert session.scalar(select(func.count()).select_from(Rechnung)) == 3


def test_serie_ohne_intervall_loescht_nur_den_termin(session):
    heute = date(2026, 11, 8)
    kunde = _kunde(session, "Einmal")
    rechnung = neue_rechnung(session, kunde, date(2026, 5, 1))
    rechnung.wiedervorlage_termin = heute
    rechnung.wiederholung_monate = None
    session.flush()
    erzeugt = serie_lauf(session, heute)
    assert len(erzeugt) == 1
    assert rechnung.wiedervorlage_termin is None
    assert erzeugt[0].wiedervorlage_termin is None
    assert erzeugt[0].wiederholung_monate is None
    assert erzeugt[0].rechnungs_nr is None


def test_add_months_klemmt_den_monatsletzten():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)


def test_format_euro_gruppiert_tausender():
    assert format_euro(Decimal("1950")) == "1.950,00 €"
    assert format_euro(Decimal("3250")) == "3.250,00 €"
    assert format_euro(Decimal("3867.5")) == "3.867,50 €"
    assert format_euro(Decimal("90")) == "90,00 €"
    assert format_euro(Decimal("-325.5")) == "-325,50 €"


def test_liste_aktuell_laesst_bezahlt_und_archiv_weg(session):
    def anlegen(**werte):
        rechnung = Rechnung(datum=date(2026, 11, 1), **werte)
        session.add(rechnung)
        return rechnung

    entwurf = anlegen(name1="Alpha", brutto=Decimal("10"))
    offen = anlegen(name1="Alpha", rechnungs_nr="26.1", brutto=Decimal("20"), bezahlt=Decimal("5"))
    bezahlt = anlegen(name1="Alpha", rechnungs_nr="26.2", brutto=Decimal("30"), bezahlt=Decimal("30"))
    archiv = anlegen(name1="Alpha", rechnungs_nr="26.3", brutto=Decimal("40"), archiv=True)
    fremd = anlegen(name1="Beta", rechnungs_nr="26.4", brutto=Decimal("7"))
    session.flush()
    entwurf.positionen.append(Position(
        menge=Decimal("1"), preis=Decimal("10"), bezeichnung="Hosting",
        freitext="", mengeneinheit="", pos_nr=0,
    ))
    session.flush()

    def ids(ansicht, name="", position=""):
        return {row.rechnungs_id for row in session.scalars(rechnungen_filtern(ansicht, name, position, None))}

    assert ids("aktuell") == {entwurf.rechnungs_id, offen.rechnungs_id, fremd.rechnungs_id}
    assert bezahlt.rechnungs_id in ids("alle") and archiv.rechnungs_id in ids("alle")
    assert ids("archiv") == {archiv.rechnungs_id}
    assert fremd.rechnungs_id not in ids("alle", "alp")
    assert ids("alle", "Alpha", "host") == {entwurf.rechnungs_id}
    assert ids("alle", "26.4") == {fremd.rechnungs_id}

    summen = rechnungen_summen(db=session, _=None)
    assert Decimal(summen["zu_berechnen"]) == Decimal("10")
    assert Decimal(summen["offen"]) == Decimal("22")
    summen_archiv_filter = rechnungen_summen(name="Alpha", db=session, _=None)
    assert Decimal(summen_archiv_filter["offen"]) == Decimal("15")
    assert Decimal(summen_archiv_filter["zu_berechnen"]) == Decimal("10")


def test_sortierung_entwurf_dann_nummer_und_seite(session):
    def anlegen(**werte):
        rechnung = Rechnung(datum=date(2026, 11, 1), **werte)
        session.add(rechnung)
        return rechnung

    entwurf = anlegen(name1="Sort", brutto=Decimal("1"))
    neu = anlegen(name1="Sort", rechnungs_nr="26.3432", brutto=Decimal("2"))
    alt = anlegen(name1="Sort", rechnungs_nr="26.3431", brutto=Decimal("3"), bezahlt=Decimal("1"))
    bezahlt = anlegen(name1="Sort", rechnungs_nr="26.3430", brutto=Decimal("4"), bezahlt=Decimal("4"))
    archiv = anlegen(name1="Sort", rechnungs_nr="26.3429", brutto=Decimal("5"), archiv=True)
    session.flush()

    def reihenfolge(ansicht, **kwargs):
        seite = rechnungen(ansicht=ansicht, name="Sort", db=session, _=None, **kwargs)
        return [zeile["rechnungs_id"] for zeile in seite["zeilen"]], seite["gesamt"]

    assert reihenfolge("aktuell")[0] == [entwurf.rechnungs_id, neu.rechnungs_id, alt.rechnungs_id]
    assert reihenfolge("alle")[0] == [neu.rechnungs_id, alt.rechnungs_id, bezahlt.rechnungs_id, archiv.rechnungs_id, entwurf.rechnungs_id]
    assert reihenfolge("archiv")[0] == [archiv.rechnungs_id]
    ids, gesamt = reihenfolge("aktuell", limit=1, offset=1)
    assert gesamt == 3
    assert ids == [neu.rechnungs_id]
    nummer = reihenfolge("alle", spalte="nummer", richtung="auf")[0]
    assert nummer[0] == archiv.rechnungs_id
    assert nummer[-1] == entwurf.rechnungs_id


def test_naechste_rechnungsnummer_setzt_den_zaehler(session):
    option = zaehler_holen(session)
    assert setze_naechste_nummer(option, "26.3500", date(2026, 11, 8)) == "26.3500"
    assert option.e_int == 3499
    with pytest.raises(ValueError):
        setze_naechste_nummer(option, "3433", date(2026, 11, 8))


def test_kopie_ohne_nummer(session):
    kunde = _kunde(session, "Kopie")
    rechnung = neue_rechnung(session, kunde, date(2026, 4, 1))
    rechnung.rechnungs_nr = "26.0001"
    rechnung.gedruckt_buchhaltung = True
    rechnung.bezahlt = Decimal("10")
    session.flush()
    neu = kopiere_rechnung(session, rechnung, date(2026, 11, 8))
    assert neu.rechnungs_nr is None
    assert neu.bezahlt == 0
    assert neu.gedruckt_buchhaltung is False
