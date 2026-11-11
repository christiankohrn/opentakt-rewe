"""Beleg-Postfach (IMAP) und lokale OCR: Erkennung, Fallbacks, Duplikate."""

from datetime import date
from decimal import Decimal
from email.message import EmailMessage

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app import mailimport as postfach
from app import ocr as ocr_modul
from app.belege import importiere, ocr_nachholen
from app.config import get_settings
from app.db import Base
from app.models import Beleg, MailImport

OCR_TEXT = (
    "Muster GmbH\n"
    "Musterstraße 1, 50667 Köln\n"
    "Rechnungsnummer 4711\n"
    "Rechnungsdatum 01.10.2026\n"
    "Gesamtbetrag 12,99 EUR\n"
)


@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("BELEG_ORDNER", str(tmp_path))
    monkeypatch.setenv("MUSTANG_JAR", "")
    monkeypatch.setenv("MUSTANG_JAVA", "")
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


def _pdf_mit_text() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    try:
        seite = doc.new_page()
        seite.insert_text((72, 72), "Rechnung 4711\nGesamtbetrag 12,99 EUR\n" * 4)
        return doc.tobytes()
    finally:
        doc.close()


def _pdf_ohne_text() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    try:
        doc.new_page()
        return doc.tobytes()
    finally:
        doc.close()


def _bild() -> bytes:
    import io

    from PIL import Image, ImageDraw

    bild = Image.new("RGB", (400, 200), "white")
    ImageDraw.Draw(bild).rectangle([20, 20, 380, 180], outline="black", width=3)
    puffer = io.BytesIO()
    bild.save(puffer, format="PNG")
    return puffer.getvalue()


def _ohne_tesseract(monkeypatch):
    monkeypatch.setattr(ocr_modul, "tesseract_pfad", lambda: None)


def _mit_ocr(monkeypatch, text: str = OCR_TEXT):
    def fake_tesseract(args, eingabe=None):
        assert eingabe is None or isinstance(eingabe, bytes)
        if "--list-langs" in args:
            return b"List of available languages (2):\neng\ndeu\n"
        assert eingabe, "OCR ohne Bilddaten aufgerufen"
        return text.encode("utf-8")

    monkeypatch.setattr(ocr_modul, "tesseract_pfad", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr_modul, "_tesseract", fake_tesseract)


def _mail_mit_anhang() -> bytes:
    nachricht = EmailMessage()
    nachricht["Subject"] = "Ihre Rechnung 4711"
    nachricht["From"] = "rechnungen@beispiel.de"
    nachricht["To"] = "belege@firma.de"
    nachricht["Message-ID"] = "<4711@beispiel.de>"
    nachricht.set_content("Anbei Ihre Rechnung als PDF.")
    nachricht.add_attachment(
        _pdf_mit_text(),
        maintype="application",
        subtype="pdf",
        filename="Rechnung-4711.pdf",
    )
    return nachricht.as_bytes()


def test_pdf_mit_text_braucht_kein_ocr():
    inhalt = _pdf_mit_text()
    assert postfach is not None
    assert ocr_modul.braucht_ocr("rechnung.pdf", inhalt) is False
    text, status, _hinweis = ocr_modul.text_ermitteln("rechnung.pdf", inhalt)
    assert status == "text"
    assert "4711" in text


def test_pdf_ohne_text_braucht_ocr():
    assert ocr_modul.braucht_ocr("scan.pdf", _pdf_ohne_text()) is True
    assert ocr_modul.braucht_ocr("bon.jpg", _bild()) is True
    assert ocr_modul.braucht_ocr("notiz.txt", "hallo".encode()) is False


def test_import_bild_ohne_tesseract(session, monkeypatch):
    _ohne_tesseract(monkeypatch)
    ergebnis = importiere(session, "bon.jpg", _bild(), "beleg", "scan")
    beleg = session.get(Beleg, ergebnis["beleg_id"])
    assert beleg is not None
    assert beleg.text_auszug == ""
    assert beleg.ocr_status == "ohne"
    assert "OCR" in (beleg.pruefung or "")


def test_import_bild_mit_ocr(session, monkeypatch):
    _mit_ocr(monkeypatch)
    ergebnis = importiere(session, "bon.jpg", _bild(), "beleg", "scan")
    beleg = session.get(Beleg, ergebnis["beleg_id"])
    assert beleg is not None
    assert beleg.ocr_status == "ocr"
    assert "Gesamtbetrag" in (beleg.text_auszug or "")
    assert beleg.betrag == Decimal("12.99")
    assert beleg.datum == date(2026, 10, 1)
    assert beleg.rechnungsnummer == "4711"


def test_import_defektes_pdf_stuerzt_nicht_ab(session, monkeypatch):
    _ohne_tesseract(monkeypatch)
    ergebnis = importiere(session, "kaputt.pdf", b"kein-pdf-inhalt", "beleg", "scan")
    beleg = session.get(Beleg, ergebnis["beleg_id"])
    assert beleg is not None
    assert beleg.ocr_status in {"ohne", "text"}


def test_ocr_nachholen(session, monkeypatch):
    _ohne_tesseract(monkeypatch)
    ergebnis = importiere(session, "bon.jpg", _bild(), "beleg", "scan")
    beleg_id = ergebnis["beleg_id"]
    assert session.get(Beleg, beleg_id).ocr_status == "ohne"
    _mit_ocr(monkeypatch)
    beleg = ocr_nachholen(session, beleg_id)
    assert beleg.ocr_status == "ocr"
    assert "Gesamtbetrag" in (beleg.text_auszug or "")
    assert beleg.betrag == Decimal("12.99")


def test_mail_anhaenge_werden_erkannt():
    from email import message_from_bytes

    anhaenge = postfach.anhaenge_aus_mail(message_from_bytes(_mail_mit_anhang()))
    assert len(anhaenge) == 1
    assert anhaenge[0][0] == "Rechnung-4711.pdf"
    assert anhaenge[0][1].lstrip().startswith(b"%PDF")


class _FakeImap:
    def __init__(self, mails: list[bytes]):
        self.mails = mails
        self.gesehen: set[str] = set()
        self.verschoben: list[tuple[str, str]] = []

    def login(self, _benutzer, _passwort):
        return ("OK", [b"ok"])

    def select(self, _ordner, readonly=False):
        return ("OK", [str(len(self.mails)).encode()])

    def search(self, _zeichensatz, *kriterien):
        if "UNSEEN" in kriterien:
            nummern = [str(i + 1) for i in range(len(self.mails)) if str(i + 1) not in self.gesehen]
        else:
            nummern = [str(i + 1) for i in range(len(self.mails))]
        return ("OK", [" ".join(nummern).encode()])

    def fetch(self, nummer, _teile):
        roh = self.mails[int(nummer) - 1]
        return ("OK", [(f'{nummer} (RFC822 {{{len(roh)}}}'.encode(), roh), b")"])

    def store(self, nummer, _befehl, _flags):
        self.gesehen.add(str(nummer))
        return ("OK", [b"ok"])

    def copy(self, nummer, ziel):
        self.verschoben.append((str(nummer), ziel))
        return ("OK", [b"ok"])

    def create(self, _ziel):
        return ("OK", [b"ok"])

    def expunge(self):
        for nummer, _ziel in self.verschoben:
            self.gesehen.add(nummer)
        return ("OK", [b"ok"])

    def close(self):
        return ("OK", [b"ok"])

    def logout(self):
        return ("OK", [b"ok"])


def _leere_mail() -> bytes:
    nachricht = EmailMessage()
    nachricht["Subject"] = "Hallo"
    nachricht["From"] = "kollege@firma.de"
    nachricht["Message-ID"] = "<hallo@firma.de>"
    nachricht.set_content("Nur Text, kein Anhang.")
    return nachricht.as_bytes()


def test_abrufen_importiert_neu_und_ignoriert_duplikat(session, monkeypatch):
    fake = _FakeImap([_mail_mit_anhang(), _leere_mail()])
    monkeypatch.setattr(postfach, "_verbindung", lambda einstellungen: fake)
    einstellungen = {
        "host": "mail.beispiel.de",
        "port": 993,
        "benutzer": "belege",
        "passwort": "geheim",
        "tls": True,
        "ordner": "INBOX",
        "erledigt": "Erledigt",
        "quelle": "eingang",
    }
    erstes = postfach.abrufen(session, einstellungen)
    assert erstes["mails"] == 2
    assert erstes["dateien"] == 1
    assert erstes["neu"] == 1
    assert len(fake.verschoben) == 2
    assert session.scalar(select(MailImport).where(MailImport.betreff.like("%4711%"))) is not None
    zweites = postfach.abrufen(session, einstellungen)
    assert zweites["mails"] == 0
    assert zweites["neu"] == 0
    assert len(session.scalars(select(Beleg)).all()) == 1


def test_abrufen_ohne_verbindung_meldet_fehler(session, monkeypatch):
    def kaputt(_einstellungen):
        raise ConnectionError("mail.beispiel.de: Verbindungsaufbau abgelehnt")

    monkeypatch.setattr(postfach, "_verbindung", kaputt)
    with pytest.raises(RuntimeError, match="nicht erreichbar"):
        postfach.abrufen(session, {"host": "mail.beispiel.de", "ordner": "INBOX", "quelle": "eingang"})


def test_fehlermeldung_ohne_passwort():
    text = postfach._fehler_saeubern("Anmeldung mit geheim-123 fehlgeschlagen", "geheim-123")
    assert "geheim-123" not in text


def test_postfach_speichern_ohne_passwort_rueckgabe(tmp_path, monkeypatch):
    datei = tmp_path / "buchhaltung.env"
    datei.write_text("SMTP_HOST=bleibt\nIMAP_HOST=alt\nIMAP_PASSWORD=alt-geheim\n", encoding="utf-8")
    monkeypatch.setenv("BUCHHALTUNG_ENV_DATEI", str(datei))
    settings = get_settings()
    vorher = (settings.imap_host, settings.imap_password, settings.imap_ordner)
    try:
        antwort = postfach.postfach_speichern("mail.beispiel.de", 993, "belege", "INBOX", "Erledigt", "eingang", True, "")
        text = datei.read_text(encoding="utf-8")
        assert "SMTP_HOST=bleibt\n" in text
        assert "IMAP_PASSWORD=alt-geheim\n" in text
        assert "IMAP_HOST=mail.beispiel.de\n" in text
        assert "passwort" not in antwort or antwort.get("passwort_gesetzt") is True
        assert "alt-geheim" not in str(antwort)
        mit = postfach.postfach_speichern("mail.beispiel.de", 993, "belege", "INBOX", "", "eingang", True, "neu-geheim")
        assert mit["passwort_gesetzt"] is True
        assert "IMAP_PASSWORD=neu-geheim\n" in datei.read_text(encoding="utf-8")
    finally:
        settings.imap_host, settings.imap_password, settings.imap_ordner = vorher
