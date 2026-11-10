import json
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.azure_ki import azure_lesen, azure_speichern, azure_testen, responses_url, verfeinern
from app.belege import (
    abrechnungen_uebersicht,
    beleg_gruppen,
    bewegung_entfernen,
    datev_zip,
    entfernen,
    importiere,
    korrigiere,
    setze_belege,
    zuordnen,
)
from app.config import get_settings
from app.db import Base
from app.erkennung import beleg_erkennen, klassifiziere_text
from app.models import Beleg, Bewegung, BewegungBeleg, Geschaeftspartner

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
        yield db


def test_volksbank_schlaegt_amex_text(session):
    text = "IBAN: DE75 5121 0800 1245 1261 99\nVolksbank Beispiel eG\nAMERICAN EXPRESS"
    art, quelle = klassifiziere_text(session, "Kontoauszug_vom_31.10.2026.pdf", text)
    assert art == "abrechnung"
    assert quelle == "volksbank"


def test_einzelne_iban_bleibt_beleg(session):
    art, quelle = klassifiziere_text(session, "Rechnung.pdf", "IBAN DE75512108001245126199\nBeispiel GmbH")
    assert art == "beleg"
    assert quelle == ""


def test_partner_aus_ust_eigene_ust_wird_ignoriert(session):
    from app.seller import stammdaten_dict, stammdaten_lesen, stammdaten_schreiben

    session.add(Geschaeftspartner(name="Hetzner Online GmbH", ust_id="DE812871812"))
    session.flush()
    # Eigene USt-Id aus den Stammdaten steht auf dem Beleg und darf nicht matchen.
    daten_stamm = stammdaten_dict(stammdaten_lesen(session))
    daten_stamm["ust_id"] = "DE000000001"
    stammdaten_schreiben(session, daten_stamm)
    text = "\n".join([
        "Hetzner Online GmbH",
        "USt-IdNr.: DE000000001",
        "USt-IdNr. DE812871812",
        "Rechnungsnummer: 081001269536",
        "Rechnungsdatum: 20.10.2026",
        "IBAN DE75 5121 0800 1245 1261 99",
    ])
    daten = beleg_erkennen(session, "hetzner.pdf", text)
    assert daten["art"] == "beleg"
    assert daten["partner"] == "Hetzner Online GmbH"
    assert daten["rechnungsnummer"] == "081001269536"
    assert daten["datum"] == "2026-10-20"


def test_partner_wird_angelegt_und_ergaenzt(session):
    beleg = Beleg(
        sha256="p", dateiname="neu.pdf", art="beleg", quelle="datei", betrag=None,
        datum=None, partner="", text_auszug="USt-IdNr. DE111111111\nIBAN DE75512108001245126199",
        pruefung="", datei="p.pdf", erstellt=date(2026, 11, 8),
    )
    session.add(beleg)
    session.flush()

    class Daten:
        datum = None
        betrag = None
        partner = "Neue Firma GmbH"
        rechnungsnummer = None

    korrigiere(session, beleg.beleg_id, Daten())
    neu = session.scalar(select(Geschaeftspartner).where(Geschaeftspartner.name == "Neue Firma GmbH"))
    assert neu is not None
    assert neu.ust_id == "DE111111111"
    assert neu.iban == "DE75512108001245126199"
    hetzner = Geschaeftspartner(name="Hetzner Online GmbH", ust_id="DE812871812", iban="")
    session.add(hetzner)
    session.flush()
    beleg.text_auszug = "IBAN DE75512108001245126199"
    Daten.partner = "Hetzner Online GmbH"
    korrigiere(session, beleg.beleg_id, Daten())
    assert hetzner.iban == "DE75512108001245126199"


def test_mehrere_belege_an_einer_bewegung(session):
    bewegung = Bewegung(
        quelle="volksbank", datum=date(2026, 11, 2), betrag=Decimal("-19.00"), waehrung="EUR",
        gegenpartei="Hetzner Online GmbH", zweck="Rechnung", fingerabdruck="m", zuordnung="",
    )
    erster = Beleg(
        sha256="a", dateiname="a.pdf", art="beleg", quelle="datei", betrag=Decimal("19.00"),
        datum=date(2026, 11, 2), partner="Hetzner Online GmbH", text_auszug="Hetzner",
        pruefung="", datei="a.pdf", erstellt=date(2026, 11, 8),
    )
    zweiter = Beleg(
        sha256="b", dateiname="b.pdf", art="beleg", quelle="datei", betrag=Decimal("8.00"),
        datum=date(2026, 11, 2), partner="Andere GmbH", text_auszug="Andere",
        pruefung="", datei="b.pdf", erstellt=date(2026, 11, 8),
    )
    session.add(bewegung)
    session.add(erster)
    session.add(zweiter)
    session.flush()
    setze_belege(session, bewegung.bewegung_id, [erster.beleg_id, zweiter.beleg_id])
    links = list(session.scalars(select(BewegungBeleg)))
    assert len(links) == 2
    assert {link.beleg_id for link in links} == {erster.beleg_id, zweiter.beleg_id}
    gruppen = beleg_gruppen(session, bewegung)
    assert set(gruppen["beleg_ids"]) == {erster.beleg_id, zweiter.beleg_id}
    assert {eintrag["beleg_id"] for eintrag in gruppen["vorschlaege"] if eintrag["zugeordnet"]} == {erster.beleg_id, zweiter.beleg_id}
    assert all(eintrag["beleg_id"] not in gruppen["beleg_ids"] for eintrag in gruppen["uebrige"])


def test_azure_schluessel_bleibt_verborgen(tmp_path, monkeypatch):
    datei = tmp_path / "buchhaltung.env"
    datei.write_text("AZURE_ENDPOINT=\nAZURE_API_KEY=geheim\nAZURE_DEPLOYMENT=\n", encoding="utf-8")
    monkeypatch.setenv("BUCHHALTUNG_ENV_DATEI", str(datei))
    settings = get_settings()
    vorher = (settings.azure_endpoint, settings.azure_api_key, settings.azure_deployment)
    settings.azure_endpoint = ""
    settings.azure_api_key = "geheim"
    settings.azure_deployment = ""
    try:
        daten = azure_speichern("https://example.invalid", "", "")
        text = datei.read_text(encoding="utf-8")
        assert "AZURE_API_KEY=geheim\n" in text
        assert "AZURE_ENDPOINT=https://example.invalid\n" in text
        assert daten == azure_lesen()
        assert "geheim" not in str(daten)
        assert set(daten) == {"endpoint", "deployment", "schluessel_gesetzt"}
        assert daten["schluessel_gesetzt"] is True
    finally:
        settings.azure_endpoint, settings.azure_api_key, settings.azure_deployment = vorher
        monkeypatch.delenv("AZURE_ENDPOINT", raising=False)
        monkeypatch.delenv("AZURE_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_DEPLOYMENT", raising=False)


def test_responses_url_haengt_den_pfad_nur_einmal_an():
    host = "https://beispiel-openai.openai.azure.com"
    erwartet = host + "/openai/responses?api-version=2025-04-01-preview"
    assert responses_url(host) == erwartet
    assert responses_url(host + "/openai/responses") == erwartet
    assert responses_url(host + "/openai/responses/openai/responses") == erwartet
    assert responses_url(host + "/openai/responses?api-version=2025-04-01-preview") == erwartet


def test_responses_nutzt_deployment_aus_den_einstellungen(monkeypatch):
    settings = get_settings()
    vorher = (settings.azure_endpoint, settings.azure_api_key, settings.azure_deployment)
    erfasst: dict[str, str] = {}

    class Antwort:
        status = 200

        def read(self):
            return b'{"output_text":"ok"}'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def oeffnen(request, timeout=30):
        erfasst["url"] = request.full_url
        erfasst["body"] = request.data.decode("utf-8")
        return Antwort()

    monkeypatch.setattr("urllib.request.urlopen", oeffnen)
    settings.azure_endpoint = "https://beispiel-openai.openai.azure.com/openai/responses"
    settings.azure_api_key = "geheim"
    settings.azure_deployment = "test-deployment"
    try:
        daten = azure_testen()
        assert erfasst["url"] == "https://beispiel-openai.openai.azure.com/openai/responses?api-version=2025-04-01-preview"
        assert "/openai/responses/openai/responses" not in erfasst["url"]
        assert json.loads(erfasst["body"])["model"] == "test-deployment"
        assert daten["status"] == 200
        assert "geheim" not in str(daten)
    finally:
        settings.azure_endpoint, settings.azure_api_key, settings.azure_deployment = vorher


def test_beleg_loeschen_laesst_bewegung(session, tmp_path):
    settings = get_settings()
    bisher = settings.beleg_ordner
    settings.beleg_ordner = str(tmp_path)
    bewegung = Bewegung(
        quelle="n26", datum=date(2026, 11, 2), betrag=Decimal("-8.00"), waehrung="EUR",
        gegenpartei="Andere GmbH", zweck="", fingerabdruck="del", zuordnung="manuell",
    )
    beleg = Beleg(
        sha256="del", dateiname="weg.txt", art="beleg", quelle="datei", betrag=Decimal("8.00"),
        datum=date(2026, 11, 2), partner="Andere GmbH", text_auszug="",
        pruefung="", datei="weg.txt", erstellt=date(2026, 11, 8),
    )
    session.add(bewegung)
    session.add(beleg)
    session.flush()
    setze_belege(session, bewegung.bewegung_id, [beleg.beleg_id])
    (tmp_path / "weg.txt").write_text("beleg", encoding="utf-8")
    entfernen(session, beleg.beleg_id)
    assert session.get(Beleg, beleg.beleg_id) is None
    assert session.get(Bewegung, bewegung.bewegung_id) is not None
    assert bewegung.beleg_id is None
    assert list(session.scalars(select(BewegungBeleg))) == []
    assert not (tmp_path / "weg.txt").exists()
    settings.beleg_ordner = bisher


def test_ki_ergaenzt_nur_gefuellte_felder(monkeypatch):
    monkeypatch.setattr(
        "app.azure_ki._aufruf",
        lambda messages: '{"partner":"","betrag":"19.00","datum":"","rechnungsnummer":"R-1"}',
    )
    basis = {"partner": "Hetzner Online GmbH", "betrag": "", "datum": "2026-10-20", "rechnungsnummer": ""}
    ergebnis = verfeinern("Beleg", basis)
    assert ergebnis["partner"] == "Hetzner Online GmbH"
    assert ergebnis["betrag"] == "19.00"
    assert ergebnis["datum"] == "2026-10-20"
    assert ergebnis["rechnungsnummer"] == "R-1"


def test_partner_lernt_muster_und_konto_zuordnung(session):
    text_1 = (
        "Sonderlieferant GmbH\n"
        "USt-IdNr.: DE999888777\n"
        "Beleg-Kodierung: SL-2026-001\n"
        "Ausgestellt am 12.10.2026\n"
        "Endpreis inkl. Steuer 42,50 EUR\n"
    )
    beleg_1 = Beleg(
        sha256="s1", dateiname="s1.pdf", art="beleg", quelle="amex", betrag=None,
        datum=None, partner="", text_auszug=text_1,
        pruefung="", datei="s1.pdf", erstellt=date(2026, 11, 8),
    )
    session.add(beleg_1)
    session.flush()

    class Korrektur:
        datum = date(2026, 10, 12)
        betrag = Decimal("42.50")
        partner = "Sonderlieferant GmbH"
        rechnungsnummer = "SL-2026-001"

    korrigiere(session, beleg_1.beleg_id, Korrektur())

    # Zweiter Beleg desselben Lieferanten wird automatisch über die gelernten Muster erkannt
    text_2 = (
        "Sonderlieferant GmbH\n"
        "USt-IdNr.: DE999888777\n"
        "Beleg-Kodierung: SL-2026-002\n"
        "Ausgestellt am 19.10.2026\n"
        "Endpreis inkl. Steuer 89,90 EUR\n"
    )
    erkannt = beleg_erkennen(session, "unbekannt.pdf", text_2)
    assert erkannt["partner"] == "Sonderlieferant GmbH"
    assert erkannt["rechnungsnummer"] == "SL-2026-002"
    assert erkannt["datum"] == "2026-10-19"
    assert erkannt["betrag"] == "89.90"
    assert erkannt["quelle"] == "amex"

    # Manuelle Zuordnung merkt sich abweichenden Händlernamen auf dem Kontoauszug
    bew_1 = Bewegung(
        quelle="amex", datum=date(2026, 10, 13), betrag=Decimal("-42.50"), waehrung="EUR",
        gegenpartei="SP*SONDER PAY", zweck="", fingerabdruck="sp1", zuordnung="",
    )
    bew_2 = Bewegung(
        quelle="amex", datum=date(2026, 10, 20), betrag=Decimal("-89.90"), waehrung="EUR",
        gegenpartei="SP*SONDER PAY", zweck="", fingerabdruck="sp2", zuordnung="",
    )
    beleg_2 = Beleg(
        sha256="s2", dateiname="s2.pdf", art="beleg", quelle="amex", betrag=Decimal("89.90"),
        datum=date(2026, 10, 19), partner="Sonderlieferant GmbH", text_auszug=text_2,
        pruefung="", datei="s2.pdf", erstellt=date(2026, 11, 8),
    )
    session.add_all([bew_1, bew_2, beleg_2])
    session.flush()
    setze_belege(session, bew_1.bewegung_id, [beleg_1.beleg_id])
    assert zuordnen(session) == 1
    assert bew_2.beleg_id == beleg_2.beleg_id
    assert bew_2.zuordnung == "automatisch"


def test_abrechnung_loeschen_und_stb_lieferstatus(session, tmp_path):
    import io
    import zipfile

    settings = get_settings()
    vorher = settings.beleg_ordner
    settings.beleg_ordner = str(tmp_path)
    try:
        csv_inhalt = (
            "Umsatzanzeige\n"
            "Buchungstag;Valuta;Auftraggeber/Zahlungsempfänger;Verwendungszweck;Betrag;Währung\n"
            "02.11.2026;02.11.2026;Bäcker Müller;Rechnung 12;-18,50;EUR\n"
            "03.11.2026;03.11.2026;Hetzner Online GmbH;Rechnung 99;-29,00;EUR\n"
        ).encode("utf-8")
        abr = importiere(session, "Kontoauszug_Volksbank.csv", csv_inhalt, "abrechnung", "volksbank")
        beleg = importiere(session, "hetzner.txt", b"Hetzner Online GmbH\nRechnungsbetrag 29,00 EUR\n03.11.2026\n", "beleg", "volksbank")
        zuordnen(session)

        uebersicht = abrechnungen_uebersicht(session, "volksbank")
        assert len(uebersicht) == 1
        assert uebersicht[0]["umsaetze"] == 2
        assert uebersicht[0]["zugeordnet"] == 1
        assert uebersicht[0]["geliefert"] == 0
        assert uebersicht[0]["datei_vorhanden"] is True

        # StB-Export markiert Umsätze, Abrechnungsdatei und Belege als geliefert und legt Abrechnung unter abrechnungen/ ab
        paket = datev_zip(session, konto="volksbank", nur_ungeliefert=True, als_geliefert_markieren=True)
        with zipfile.ZipFile(io.BytesIO(paket)) as archiv:
            namen = archiv.namelist()
            assert any(n.startswith("abrechnungen/") and n.endswith("Kontoauszug_Volksbank.csv") for n in namen)
            assert any(n.startswith("belege/") and n.endswith("hetzner.txt") for n in namen)
            csv_text = archiv.read("bewegungen.csv").decode("utf-8-sig")
            assert "Abrechnungsdatei" in csv_text
            assert "abrechnungen/" in csv_text

        uebersicht_nach = abrechnungen_uebersicht(session, "volksbank")
        assert uebersicht_nach[0]["geliefert"] == 2
        assert uebersicht_nach[0]["datev_gesendet"] is not None

        # Zweiter inkrementeller Export enthält keine bereits gelieferten Bewegungen mehr
        paket_2 = datev_zip(session, konto="volksbank", nur_ungeliefert=True, als_geliefert_markieren=True)
        with zipfile.ZipFile(io.BytesIO(paket_2)) as archiv_2:
            zeilen_2 = archiv_2.read("bewegungen.csv").decode("utf-8-sig").strip().splitlines()
            assert len(zeilen_2) == 1  # nur Kopfzeile

        # Einzelne Kontozeile löschen
        erste_bew = session.scalar(select(Bewegung).where(Bewegung.betrag == Decimal("-18.50")))
        assert erste_bew is not None
        bewegung_entfernen(session, erste_bew.bewegung_id)
        assert len(list(session.scalars(select(Bewegung)))) == 1

        # Ganze Abrechnung löschen entfernt auch die restlichen Umsätze dieser Abrechnung, lässt aber den Beleg bestehen
        entfernen(session, abr["beleg_id"])
        assert list(session.scalars(select(Bewegung))) == []
        assert session.get(Beleg, beleg["beleg_id"]) is not None
    finally:
        settings.beleg_ordner = vorher
