from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.auszuege import parse_volksbank_csv
from app.belege import datev_zip, importiere, manuell, senden, zuordnen
from app.config import get_settings
from app.datev_adressen import ADRESSEN, vorschlag
from app.db import Base
from app.mailer import SmtpFehlt
from app.models import Beleg, Bewegung


@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("BELEG_ORDNER", str(tmp_path))
    monkeypatch.setenv("MUSTANG_JAR", "")
    monkeypatch.setenv("MUSTANG_JAVA", "")
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("SMTP_FROM", "")
    get_settings.cache_clear()
    engine = create_engine("sqlite://", future=True)

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as db:
        yield db
    get_settings.cache_clear()


def test_adressen_startwerte():
    assert ADRESSEN["amex"] == ("", "Amex")
    assert ADRESSEN["lufthansakk"] == ("", "Lufthansa")
    assert ADRESSEN["rechnungsausgang"] == ("", "Rechnungsausgang")
    assert vorschlag("miles") == "lufthansakk"
    assert vorschlag("n26") is None
    assert vorschlag("volksbank") is None
    assert "konto" not in ADRESSEN


def test_volksbank_csv():
    roh = (
        "Umsatzanzeige\n"
        "Buchungstag;Valuta;Auftraggeber/Zahlungsempfänger;Verwendungszweck;Betrag;Währung\n"
        "02.11.2026;02.11.2026;Bäcker Müller;Rechnung 12;-18,50;EUR\n"
    ).encode("utf-8")
    umsaetze = parse_volksbank_csv(roh)
    assert umsaetze[0]["betrag"] == Decimal("-18.50")
    assert umsaetze[0]["gegenpartei"] == "Bäcker Müller"


def test_nur_eindeutige_zuordnung(session):
    session.add(Bewegung(
        quelle="amex", datum=date(2026, 10, 21), betrag=Decimal("-177.63"), waehrung="EUR",
        gegenpartei="HETZNER ONLINE GMBH", zweck="", fingerabdruck="a", zuordnung="",
    ))
    session.add(Bewegung(
        quelle="amex", datum=date(2026, 10, 22), betrag=Decimal("-177.63"), waehrung="EUR",
        gegenpartei="HETZNER ONLINE GMBH", zweck="", fingerabdruck="b", zuordnung="",
    ))
    session.add(Beleg(
        sha256="1", dateiname="hetzner.pdf", art="beleg", quelle="amex", betrag=Decimal("177.63"),
        datum=date(2026, 10, 21), text_auszug="Hetzner Online GmbH Rechnung 177,63",
        pruefung="", datei="1.pdf", erstellt=date(2026, 11, 8),
    ))
    session.flush()
    assert zuordnen(session) == 0
    assert session.scalar(select(Bewegung).where(Bewegung.beleg_id.is_not(None))) is None


def test_ein_treffer_wird_zugeordnet(session):
    session.add(Bewegung(
        quelle="amex", datum=date(2026, 10, 21), betrag=Decimal("-12.99"), waehrung="EUR",
        gegenpartei="PAYPAL *ARLO", zweck="", fingerabdruck="c", zuordnung="",
    ))
    beleg = Beleg(
        sha256="2", dateiname="arlo.pdf", art="beleg", quelle="amex", betrag=Decimal("12.99"),
        datum=date(2026, 10, 23), text_auszug="Arlo Europe Rechnung Gesamtbetrag 12,99",
        pruefung="", datei="2.pdf", erstellt=date(2026, 11, 8),
    )
    session.add(beleg)
    session.flush()
    assert zuordnen(session) == 1
    bewegung = session.scalar(select(Bewegung))
    assert bewegung.zuordnung == "automatisch"
    assert bewegung.beleg_id == beleg.beleg_id


def test_eingang_wird_nicht_abgelehnt(session, tmp_path):
    inhalt = b"%PDF-1.4\nkein zugferd\n"
    ergebnis = importiere(session, "eingang.pdf", inhalt, "eingang", "eingang")
    session.flush()
    beleg = session.get(Beleg, ergebnis["beleg_id"])
    assert beleg is not None
    assert "gespeichert" in beleg.pruefung.casefold() or "validator" in beleg.pruefung.casefold()
    assert (tmp_path / beleg.datei).read_bytes() == inhalt


def test_zip_enthaelt_original_ohne_buchungssatz(session, tmp_path):
    importiere(session, "beleg.txt", b"Hetzner Rechnung Gesamtbetrag 12,99\n01.10.2026\n", "beleg", "amex")
    session.flush()
    paket = datev_zip(session)
    import zipfile
    import io
    with zipfile.ZipFile(io.BytesIO(paket)) as archiv:
        namen = archiv.namelist()
        xml = archiv.read("document.xml").decode("utf-8")
        assert "accountsPayableLedger" not in xml
        assert "Buchungssätze folgen später" in xml
        beleg_name = next(name for name in namen if name.startswith("belege/"))
        assert archiv.read(beleg_name) == b"Hetzner Rechnung Gesamtbetrag 12,99\n01.10.2026\n"
        assert b"Gegenpartei" in archiv.read("bewegungen.csv")


def test_konto_versand_ohne_erfundene_adresse(session):
    beleg = Beleg(
        sha256="3", dateiname="n26.pdf", art="abrechnung", quelle="n26", betrag=None,
        datum=None, text_auszug="", pruefung="", datei="3.pdf", erstellt=date(2026, 11, 8),
    )
    session.add(beleg)
    session.flush()
    with pytest.raises(ValueError, match="Konto"):
        senden(session, beleg.beleg_id, None)


def test_smtp_fehlt(session, tmp_path):
    (tmp_path / "4.pdf").write_bytes(b"pdf")
    beleg = Beleg(
        sha256="4", dateiname="amex.pdf", art="abrechnung", quelle="amex", betrag=None,
        datum=None, text_auszug="", pruefung="", datei="4.pdf", erstellt=date(2026, 11, 8),
    )
    session.add(beleg)
    session.flush()
    with pytest.raises(SmtpFehlt):
        senden(session, beleg.beleg_id, None)


def test_betrag_ohne_namen_bleibt_geraten(session):
    session.add(Bewegung(
        quelle="n26", datum=date(2026, 10, 8), betrag=Decimal("-4.74"), waehrung="EUR",
        gegenpartei="Unbekannt", zweck="", fingerabdruck="g", zuordnung="",
    ))
    session.add(Beleg(
        sha256="9", dateiname="fremd.pdf", art="beleg", quelle="n26", betrag=Decimal("4.74"),
        datum=date(2026, 10, 8), text_auszug="Andere Firma Rechnung",
        pruefung="", datei="9.pdf", erstellt=date(2026, 11, 8),
    ))
    session.flush()
    assert zuordnen(session) == 1
    bewegung = session.scalar(select(Bewegung))
    assert bewegung.zuordnung == "geraten"


def test_manuell(session):
    bewegung = Bewegung(
        quelle="n26", datum=date(2026, 10, 2), betrag=Decimal("-18.50"), waehrung="EUR",
        gegenpartei="Bäcker", zweck="", fingerabdruck="d", zuordnung="",
    )
    beleg = Beleg(
        sha256="5", dateiname="bon.jpg", art="scan", quelle="scan", betrag=None,
        datum=None, text_auszug="", pruefung="", datei="5.jpg", erstellt=date(2026, 11, 8),
    )
    session.add(bewegung)
    session.add(beleg)
    session.flush()
    manuell(session, bewegung.bewegung_id, beleg.beleg_id)
    assert bewegung.zuordnung == "manuell"


def test_konto_filter(session):
    from app.belege_routes import belege_liste, bewegungen_liste
    from fastapi import HTTPException

    beleg = Beleg(
        sha256="k", dateiname="bon.pdf", art="beleg", quelle="datei", betrag=Decimal("-5.00"),
        datum=date(2026, 11, 1), text_auszug="", pruefung="", datei="k.pdf", erstellt=date(2026, 11, 1),
    )
    session.add(beleg)
    session.flush()
    session.add(Bewegung(
        quelle="n26", datum=date(2026, 11, 1), betrag=Decimal("-5.00"), waehrung="EUR",
        gegenpartei="Laden", zweck="Einkauf", fingerabdruck="n26-k", beleg_id=beleg.beleg_id,
    ))
    session.add(Bewegung(
        quelle="amex", datum=date(2026, 11, 2), betrag=Decimal("-8.00"), waehrung="EUR",
        gegenpartei="Hotel", zweck="Reise", fingerabdruck="amex-k",
    ))
    session.flush()
    nur_n26 = bewegungen_liste("n26", session)
    assert [zeile["quelle"] for zeile in nur_n26] == ["n26"]
    belege = belege_liste("n26", session)
    assert [zeile["beleg_id"] for zeile in belege] == [beleg.beleg_id]
    assert belege[0]["eingang"] == "2026-11-01"
    with pytest.raises(HTTPException):
        bewegungen_liste("sonstige", session)


def test_konto_anlegen_und_loeschen(session):
    from app.kategorien import kategorie_anlegen, kategorie_loeschen

    konto = kategorie_anlegen(session, "Sparkasse Köln", "", "")
    assert konto.schluessel == "sparkassekoeln"
    importiere(session, "bon.pdf", b"%PDF-1.4\n", "beleg", "sparkassekoeln")
    with pytest.raises(ValueError, match="verwendet"):
        kategorie_loeschen(session, "sparkassekoeln")
    leer = kategorie_anlegen(session, "Bar", "bar", "")
    kategorie_loeschen(session, leer.schluessel)
    assert session.scalar(select(type(leer)).where(type(leer).schluessel == "bar")) is None


def test_stb_zip_enthaelt_kompakte_ausgangsrechnung(session):
    import io
    import zipfile

    from app.domain import berechne
    from app.erechnung import erechnung_aus_pdf
    from app.models import Position, Rechnung
    from app.pdf import rechnung_pdf

    rechnung = Rechnung(
        datum=date(2026, 11, 2),
        name1="Beispiel GmbH",
        strasse="Hafenstr. 1",
        plz="50667",
        ort="Köln",
        rechnungs_nr="26.3432",
        leistungszeitraum="Oktober 2026",
        keine_mehrwertsteuer=False,
        umsatzsteuer_id="",
    )
    rechnung.positionen.append(Position(menge=Decimal("1"), preis=Decimal("100"), bezeichnung="Tag", mengeneinheit="Tag", pos_nr=0))
    berechne(rechnung)
    entwurf = Rechnung(datum=date(2026, 11, 2), name1="Entwurf", rechnungs_nr=None)
    session.add(rechnung)
    session.add(entwurf)
    session.flush()
    mit_papier = rechnung_pdf(rechnung, briefpapier=True)
    paket = datev_zip(session, nur_ungeliefert=True, als_geliefert_markieren=True)
    with zipfile.ZipFile(io.BytesIO(paket)) as archiv:
        namen = [name for name in archiv.namelist() if name.startswith("ausgangsrechnungen/")]
        assert namen == ["ausgangsrechnungen/Ausgangsrechnung-26.3432.pdf"]
        kompakt = archiv.read(namen[0])
        assert len(kompakt) < len(mit_papier)
        assert "ausgangsrechnungen/Ausgangsrechnung-26.3432.pdf" in archiv.read("document.xml").decode("utf-8")
        daten = erechnung_aus_pdf(kompakt)
    assert daten and daten["nummer"] == "26.3432"
    assert rechnung.datev_gesendet is not None
    assert rechnung.gedruckt_buchhaltung is True
    assert entwurf.datev_gesendet is None
    erneut = datev_zip(session, nur_ungeliefert=True, als_geliefert_markieren=True)
    with zipfile.ZipFile(io.BytesIO(erneut)) as archiv:
        assert not any(name.startswith("ausgangsrechnungen/") for name in archiv.namelist())


def test_start_wendet_migrationen_an(tmp_path, monkeypatch):
    from alembic import command
    from sqlalchemy import create_engine, inspect

    from app.db import Base
    from app.migration import alembic_konfiguration, migrationen_anwenden
    import app.models  # noqa: F401

    url = "sqlite:///" + (tmp_path / "buchhaltung.db").as_posix()
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("BUCHHALTUNG_SESSION_SECRET", "test")
    monkeypatch.setenv("BUCHHALTUNG_ENV_DATEI", str(tmp_path / "keine.env"))
    get_settings.cache_clear()
    try:
        from app.db import init_engine

        engine = init_engine(url)
        Base.metadata.create_all(engine)
        with engine.begin() as verbindung:
            verbindung.exec_driver_sql("ALTER TABLE rechnungen DROP COLUMN datev_gesendet")
            verbindung.exec_driver_sql("ALTER TABLE belege DROP COLUMN ocr_status")
            verbindung.exec_driver_sql("ALTER TABLE kategorien DROP COLUMN weiterverarbeitung")
            verbindung.exec_driver_sql("ALTER TABLE kategorien DROP COLUMN iban")
            verbindung.exec_driver_sql("ALTER TABLE kategorien DROP COLUMN bic")
            verbindung.exec_driver_sql("DROP TABLE mail_importe")
            verbindung.exec_driver_sql("DROP TABLE export_vorgaenge")
            verbindung.exec_driver_sql("DROP TABLE benutzer")
            verbindung.exec_driver_sql("DROP TABLE mail_tokens")
            verbindung.exec_driver_sql("DROP TABLE backup_codes")
            verbindung.exec_driver_sql("DROP TABLE passkeys")
            verbindung.exec_driver_sql("DROP TABLE audit_ereignisse")
        command.stamp(alembic_konfiguration(), "0006_lieferung")
        migrationen_anwenden()
        spalten = {spalte["name"] for spalte in inspect(engine).get_columns("rechnungen")}
        assert "datev_gesendet" in spalten
        kat_spalten = {spalte["name"] for spalte in inspect(engine).get_columns("kategorien")}
        assert {"weiterverarbeitung", "iban", "bic"} <= kat_spalten
        tabellen = inspect(engine).get_table_names()
        assert "mail_importe" in tabellen
        beleg_spalten = {spalte["name"] for spalte in inspect(engine).get_columns("belege")}
        assert "ocr_status" in beleg_spalten
        assert "export_vorgaenge" in tabellen
        assert "benutzer" in tabellen
        assert {"mail_tokens", "backup_codes", "passkeys", "audit_ereignisse"} <= set(tabellen)
        benutzer_spalten = {spalte["name"] for spalte in inspect(engine).get_columns("benutzer")}
        assert {"auth_quelle", "totp_secret", "totp_aktiv", "totp_bestaetigt_am"} <= benutzer_spalten
        migrationen_anwenden()
    finally:
        get_settings.cache_clear()


def test_geldeingang_ordnet_ausgangsrechnung_zu_und_markiert_bezahlt(session):
    from app.domain import berechne
    from app.models import Position, Rechnung

    rechnung = Rechnung(
        datum=date(2026, 10, 5),
        name1="Musterkunde GmbH",
        rechnungs_nr="26.3404",
        keine_mehrwertsteuer=False,
    )
    rechnung.positionen.append(Position(menge=Decimal("1"), preis=Decimal("1282.504202"), bezeichnung="Service", pos_nr=0))
    berechne(rechnung)
    session.add(rechnung)
    bewegung = Bewegung(
        quelle="n26",
        datum=date(2026, 10, 15),
        betrag=Decimal("1526.18"),
        waehrung="EUR",
        gegenpartei="Musterkunde GmbH",
        zweck="Gutschriften Rg 26 3404 K Nr",
        fingerabdruck="n26-eingang-3404",
    )
    session.add(bewegung)
    session.flush()
    assert zuordnen(session) == 1
    assert bewegung.beleg_id is not None
    assert bewegung.zuordnung == "automatisch"
    assert rechnung.bezahlt == rechnung.brutto
    assert rechnung.bezahlt_am == date(2026, 10, 15)


def test_beleg_gruppen_begrenzt_auf_30_tage_bis_auf_knopfdruck(session):
    from app.belege import beleg_gruppen

    bewegung = Bewegung(
        quelle="amex",
        datum=date(2026, 11, 1),
        betrag=Decimal("-50.00"),
        waehrung="EUR",
        gegenpartei="Hetzner",
        zweck="",
        fingerabdruck="amex-30t",
    )
    nah = Beleg(
        sha256="nah",
        dateiname="nah.pdf",
        art="beleg",
        quelle="amex",
        betrag=Decimal("50.00"),
        datum=date(2026, 10, 20),
        partner="Hetzner",
        text_auszug="Hetzner",
        pruefung="",
        datei="nah.pdf",
        erstellt=date(2026, 10, 20),
    )
    alt = Beleg(
        sha256="alt",
        dateiname="alt.pdf",
        art="beleg",
        quelle="amex",
        betrag=Decimal("50.00"),
        datum=date(2026, 8, 1),
        partner="Hetzner",
        text_auszug="Hetzner",
        pruefung="",
        datei="alt.pdf",
        erstellt=date(2026, 8, 1),
    )
    session.add_all([bewegung, nah, alt])
    session.flush()
    standard = beleg_gruppen(session, bewegung, alle=False)
    assert [e["beleg_id"] for e in standard["vorschlaege"]] == [nah.beleg_id]
    assert standard["ausgeblendet"] == 1
    komplett = beleg_gruppen(session, bewegung, alle=True)
    assert {e["beleg_id"] for e in komplett["vorschlaege"]} == {nah.beleg_id, alt.beleg_id}
    assert komplett["ausgeblendet"] == 0


def test_belege_konto_aendern(session):
    from app.belege_routes import BelegeKontoIn, belege_konto_setzen

    erster = Beleg(
        sha256="k1",
        dateiname="eins.pdf",
        art="beleg",
        quelle="amex",
        betrag=Decimal("10.00"),
        datum=date(2026, 11, 1),
        text_auszug="",
        pruefung="",
        datei="k1.pdf",
        erstellt=date(2026, 11, 1),
    )
    zweiter = Beleg(
        sha256="k2",
        dateiname="zwei.pdf",
        art="beleg",
        quelle="amex",
        betrag=Decimal("20.00"),
        datum=date(2026, 11, 1),
        text_auszug="",
        pruefung="",
        datei="k2.pdf",
        erstellt=date(2026, 11, 1),
    )
    session.add_all([erster, zweiter])
    session.flush()
    antwort = belege_konto_setzen(BelegeKontoIn(beleg_ids=[erster.beleg_id, zweiter.beleg_id], quelle="n26"), session)
    assert antwort == {"geaendert": 2, "quelle": "n26"}
    assert erster.quelle == "n26"
    assert zweiter.quelle == "n26"


def test_weiterverarbeitung_9226961_und_email_export_und_schluessel_rename(session, tmp_path, monkeypatch):
    from app.belege import _document_xml, datev_weiterverarbeitung_csv, email_export_ausfuehren, export_vorgaenge_liste
    from app.kategorien import kategorie_aktualisieren, kategorie_anlegen, versand_optionen_schreiben

    # 1. XML-Header enthält xsi:schemaLocation
    xml = _document_xml([("bewegungen.csv", None)])
    assert 'xsi:schemaLocation="http://xml.datev.de/bedi/tps/document/v05.0 Document_v050.xsd"' in xml

    # 2. Konto anlegen und Schlüssel umbenennen kaskadiert
    konto = kategorie_anlegen(
        session,
        "Mein Konto",
        "meinkonto",
        "konto@uploadmail.datev.de",
        weiterverarbeitung=True,
        iban="DE89370400440532013000",
        bic="COBADEFFXXX",
    )
    (tmp_path / "beleg1.pdf").write_bytes(b"%PDF-1.4\nTest")
    beleg = Beleg(
        sha256="b-wv-1",
        dateiname="beleg1.pdf",
        art="beleg",
        quelle="meinkonto",
        betrag=Decimal("-49.90"),
        datum=date(2026, 10, 12),
        partner="Hetzner",
        text_auszug="",
        pruefung="",
        datei="beleg1.pdf",
        erstellt=date(2026, 10, 12),
    )
    session.add(beleg)
    session.flush()
    bew = Bewegung(
        quelle="meinkonto",
        datum=date(2026, 10, 12),
        betrag=Decimal("-49.90"),
        waehrung="EUR",
        gegenpartei="Hetzner Online GmbH",
        zweck="Rechnung 1234567890",
        fingerabdruck="fp-wv-1",
        beleg_id=beleg.beleg_id,
    )
    session.add(bew)
    session.flush()

    kategorie_aktualisieren(
        session,
        "meinkonto",
        "Mein Geschäftskonto",
        "konto@uploadmail.datev.de",
        weiterverarbeitung=True,
        iban="DE89370400440532013000",
        bic="COBADEFFXXX",
        neuer_schluessel="geschaeft",
    )
    assert konto.schluessel == "geschaeft"
    assert beleg.quelle == "geschaeft"
    assert bew.quelle == "geschaeft"

    # 3. Weiterverarbeitungsdatei (Dok.-Nr. 9226961) hat genau 34 Semikolon-getrennte Felder
    wv_name, wv_bytes = datev_weiterverarbeitung_csv([bew], konto)
    wv_text = wv_bytes.decode("cp1252").strip()
    spalten = wv_text.split(";")
    assert len(spalten) == 34
    assert spalten[0] == '"COBADEFFXXX"'
    assert spalten[1] == '"DE89370400440532013000"'
    assert spalten[5] == "12.10.2026"
    assert spalten[6] == "-49.90"
    assert spalten[7] == '"Hetzner Online GmbH"'
    assert spalten[11] == '"Rechnung 1234567890"'

    # 4. E-Mail-Export und Wiederholung eines Exportvorgangs
    gesendete_mails: list[tuple[str, str, str]] = []
    gesendete_sammel: list[tuple[str, str, list[str], str]] = []
    monkeypatch.setattr(
        "app.belege.senden_datei",
        lambda empfaenger, betreff_text, dateiname, inhalt, text="", html="": gesendete_mails.append((empfaenger, betreff_text, dateiname)),
    )
    monkeypatch.setattr(
        "app.belege.senden_dateien",
        lambda empfaenger, betreff_text, anhaenge, text="", html="": gesendete_sammel.append((empfaenger, betreff_text, [n for n, _ in anhaenge], text)),
    )
    versand_optionen_schreiben(session, "steuerberater@example.org", "ausgang@uploadmail.datev.de")
    erg = email_export_ausfuehren(session, konto="geschaeft", nur_ungeliefert=True)
    assert erg["emails_gesendet"] == 2  # 1 Beleg + 1 StB-Mail mit Weiterverarbeitungsdatei
    assert beleg.datev_gesendet is not None
    assert bew.datev_geliefert is not None
    assert len(gesendete_sammel) == 1
    assert "Im Anhang finden Sie die Datev Weiterverarbeitungsdatei." in gesendete_sammel[0][3]

    vorgaenge = export_vorgaenge_liste(session)
    assert len(vorgaenge) == 1
    # Erneut ausführen über vorgang_id sendet dieselben E-Mails nochmal
    erg_2 = email_export_ausfuehren(session, vorgang_id=erg["export_id"])
    assert erg_2["emails_gesendet"] == 2
    assert len(gesendete_mails) == 2
    assert len(gesendete_sammel) == 2
