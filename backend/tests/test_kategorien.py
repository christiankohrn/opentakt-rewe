import os
from decimal import Decimal

from app.auszuege import erkenne
from app.config import get_settings
from app.datev_adressen import ADRESSEN
from app.kategorien import SEED, email_fuer


def test_seed_nur_vorhandene_adressen():
    namen = [name for _, name, *_ in SEED]
    assert namen == ["Amex", "Lufthansa", "Volksbank", "N26"]
    assert email_fuer("amex") == ADRESSEN["amex"][0]
    assert email_fuer("lufthansakk") == ADRESSEN["lufthansakk"][0]
    assert email_fuer("") == ""
    leer = [schluessel for schluessel, _, adresse, *_ in SEED if not adresse]
    assert leer == ["volksbank", "n26"]


def test_erkenne_rechnungsfelder():
    text = "Beispiel GmbH\nRechnungsnummer: R-100\nRechnungsdatum: 01.11.2026\nRechnungsbetrag 19,00 EUR\n"
    daten = erkenne(text, "beleg.txt")
    assert daten["partner"] == "Beispiel GmbH"
    assert daten["rechnungsnummer"] == "R-100"
    assert daten["betrag"] == Decimal("19.00")
    assert daten["datum"].isoformat() == "2026-11-01"


def test_session_secret_bleibt_in_der_datei(tmp_path, monkeypatch):
    datei = tmp_path / "buchhaltung.env"
    datei.write_text("BUCHHALTUNG_PASSWORD=x\n", encoding="utf-8")
    monkeypatch.setenv("BUCHHALTUNG_ENV_DATEI", str(datei))
    monkeypatch.delenv("BUCHHALTUNG_SESSION_SECRET", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        erster = get_settings().session_secret
        get_settings.cache_clear()
        zweiter = get_settings().session_secret
        assert erster and erster != "CHANGE_ME"
        assert zweiter == erster
        assert f"BUCHHALTUNG_SESSION_SECRET={erster}\n" in datei.read_text(encoding="utf-8")
    finally:
        os.environ.pop("BUCHHALTUNG_SESSION_SECRET", None)
        get_settings.cache_clear()
