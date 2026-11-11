from datetime import date
from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader

from app.domain import berechne
from app.models import Position, Rechnung
from app.pdf import rechnung_pdf


def _rechnung() -> Rechnung:
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
    rechnung.positionen.append(
        Position(menge=Decimal("1"), preis=Decimal("650"), bezeichnung="Ein Tag", mengeneinheit="Tag", pos_nr=0)
    )
    rechnung.positionen.append(
        Position(menge=Decimal("3"), preis=Decimal("650"), bezeichnung="Drei Tage", mengeneinheit="Tage", pos_nr=1)
    )
    berechne(rechnung)
    return rechnung


def test_layout_folgt_dem_briefpapier():
    reader = PdfReader(BytesIO(rechnung_pdf(_rechnung())))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    for phrase in (
        "Rechnung Nr. 26.3432",
        "Leistungszeitraum: Oktober 2026",
        "Hiermit stellen wir Ihnen folgende Leistungen in Rechnung:",
        "Anzahl",
        "Bezeichnung",
        "Elektronische Rechnung im Format ZUGFeRD (Profil XRechnung)",
        "Zahlcode:",
        "Zahlung: 10 Tage netto",
        "1.950,00 €",
        "Seite 1 von 1",
    ):
        assert phrase in text
    # Menge 1 blendet den Einzelpreis aus, Menge 3 zeigt ihn.
    assert text.count("650,00 €") == 2
    assert "factur-x.xml" in [item.name for item in reader.attachment_list]
    # QR-Code ist vorhanden, aber kein vollflächiges Briefpapier-Hintergrundbild
    assert len(reader.pages[0].images) == 1


def test_dynamische_stammdaten_im_pdf_und_xml():
    from app.erechnung import erechnung_aus_pdf
    from app.seller import Stammdaten

    eigene = Stammdaten(
        name="Musterfirma GmbH",
        strasse_brief="Hauptstraße 99",
        strasse_xml="Hauptstrasse 99",
        plz="10115",
        ort="Berlin",
        telefon="+49 30 123456",
        email="info@musterfirma.de",
        steuernummer="11/222/33333",
        ust_id="DE999888777",
        bank_name="Musterbank",
        bank_iban="DE89 3704 0044 0532 0130 00",
        bank_bic="COBADEFFXXX",
        fusszeile="Individuelle Fußzeile für Kunden",
        zahlungstext="Zahlbar innerhalb von 14 Tagen",
        zahlungsziel_tage=14,
    )
    pdf_bytes = rechnung_pdf(_rechnung(), stammdaten=eigene)
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Musterfirma GmbH • Hauptstraße 99 • 10115 Berlin" in text
    assert "Berlin, 02.11.2026" in text
    assert "Musterbank" in text
    assert "DE999888777" in text
    assert "Zahlbar innerhalb von 14 Tagen" in text
    er = erechnung_aus_pdf(pdf_bytes)
    assert er is not None
    assert "Musterfirma GmbH" in er["verkaeufer"]


def test_serverseitige_pdf_und_text_vorschau():
    from app.vorschau import lokale_datei_vorschau, pdf_seite_png, pdf_seiten_anzahl, text_vorschau

    pdf_bytes = rechnung_pdf(_rechnung())
    assert pdf_seiten_anzahl(pdf_bytes) == 1
    png = pdf_seite_png(pdf_bytes, 1, max_kante=1200)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"

    lokal = lokale_datei_vorschau("test.pdf", pdf_bytes)
    assert lokal["art"] == "pdf"
    assert lokal["gesamt"] == 1
    assert lokal["seiten"][0].startswith("data:image/png;base64,")

    csv_auszug = text_vorschau("auszug.csv", "Datum;Betrag\n01.11.2026;-12,34\n".encode("utf-8"))
    assert csv_auszug is not None and "01.11.2026" in csv_auszug
