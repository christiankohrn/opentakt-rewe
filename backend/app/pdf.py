import io
import os
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.domain import (
    format_euro,
    format_menge,
    mahnung_daten,
    mwst_satz,
    pdf_betraege,
    reverse_charge_text,
    sortierte_positionen,
)
from app.epc import epc_payload
from app.models import Rechnung
from app.seller import STANDARD_STAMMDATEN, RechnungsLayout, Stammdaten
from app.zugferd import xrechnung_xml

# Rein schwarz-weißes Standardlayout ohne Briefpapier/Farben.
# Kunden-individuelle Layouts können später über RechnungsLayout abgebildet werden.
PAGE_W, PAGE_H = A4
SRGB = Path(__file__).with_name("srgb.icc")
BLACK = (0, 0, 0)

X_LEFT = 56.4
X_BEZ = 118.8
X_EP = 424.9
X_GESAMT = 495.8
X_RIGHT = 566.6
X_TEXT = 57.8
X_MENGE = 56.4
X_BEZ_TEXT = 118.8
X_FREITEXT = 134.0
X_RECHTS = 450.0
X_TELEFON = 480.1
X_LEISTUNG = 74.5

Y_ABSENDER = 155.9
Y_ANSCHRIFT = 170.1
Y_TITEL = 311.8
Y_LEISTUNG = 324.6
Y_TEL = 334.5
Y_MAIL = 345.8
Y_KOPF = 382.7
Y_EINLEITUNG = 398.3
Y_ERSTE_ZEILE = 420.9
Y_SUMME = 697.2
Y_ZAHLUNG = 734.2
Y_ZUGFERD = 756.4
Y_ZAHLCODE = 773.5
Y_BANK = 773.5
Y_IBAN = 785.0
Y_STEUER = 796.5
Y_SEITE = 802.1

KOPF_HOEHE = 14.1
SUMME_HOEHE = 32.5
ZEILE = 16.8
FREITEXT_ERSTE = 12.8
FREITEXT_WEITER = 11.5
NACH_FREITEXT = 17.0
ZEILEN_ENDE = 684.0

_FONTS: tuple[str, str] | None = None


def _fonts() -> tuple[str, str]:
    global _FONTS
    if _FONTS is not None:
        return _FONTS
    candidates = [
        (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf", "BuchArial", "BuchArial-Bold"),
        (
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "BuchLiberation",
            "BuchLiberation-Bold",
        ),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "BuchDejaVu",
            "BuchDejaVu-Bold",
        ),
    ]
    registered = set(pdfmetrics.getRegisteredFontNames())
    for regular, bold, name, bold_name in candidates:
        if os.path.exists(regular) and os.path.exists(bold):
            if name not in registered:
                pdfmetrics.registerFont(TTFont(name, regular))
                pdfmetrics.registerFont(TTFont(bold_name, bold))
                registerFontFamily(name, normal=name, bold=bold_name, italic=name, boldItalic=bold_name)
            _FONTS = (name, bold_name)
            return _FONTS
    _FONTS = ("Helvetica", "Helvetica-Bold")
    return _FONTS


def _ascent(font: str, size: float) -> float:
    return pdfmetrics.getAscent(font) / 1000 * size


def _text(c: canvas.Canvas, font: str, size: float, x: float, top: float, text: str, align: str = "left", right: float | None = None) -> None:
    if not text:
        return
    c.setFillColorRGB(*BLACK)
    c.setFont(font, size)
    baseline = PAGE_H - (top + _ascent(font, size) + 0.5)
    if align == "right":
        c.drawRightString(right if right is not None else x, baseline, text)
    elif align == "center":
        c.drawCentredString(x, baseline, text)
    else:
        c.drawString(x, baseline, text)


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    lines: list[str] = []
    for absatz in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        words = absatz.split()
        if not words:
            continue
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if pdfmetrics.stringWidth(trial, font, size) <= width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _anschrift(c: canvas.Canvas, font: str, rechnung: Rechnung, stamm: Stammdaten, layout: RechnungsLayout) -> None:
    if layout.zeige_absenderzeile and stamm.absenderzeile:
        _text(
            c,
            font,
            6,
            X_TEXT,
            Y_ABSENDER,
            stamm.absenderzeile,
        )
    top = Y_ANSCHRIFT
    for zeile in (rechnung.name1, rechnung.name2, rechnung.name3, rechnung.strasse):
        if (zeile or "").strip():
            _text(c, font, 10, X_TEXT, top, zeile.strip())
            top += 12.7
    ort = f"{rechnung.plz or ''} {rechnung.ort or ''}".strip()
    if ort:
        if (rechnung.strasse or "").strip():
            top += 4.4
        _text(c, font, 10, X_TEXT, top, ort)


def _spaltenkopf(c: canvas.Canvas, font: str, top: float) -> None:
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.75)
    c.rect(X_LEFT, PAGE_H - top - KOPF_HOEHE, X_RIGHT - X_LEFT, KOPF_HOEHE, stroke=1, fill=0)
    for x in (X_BEZ, X_EP, X_GESAMT):
        c.line(x, PAGE_H - top, x, PAGE_H - top - KOPF_HOEHE)
    text_top = top + 0.7
    _text(c, font, 10, 58.6, text_top, "Anzahl")
    _text(c, font, 10, 120.2, text_top, "Bezeichnung")
    _text(c, font, 10, X_EP, text_top, "EP", align="right", right=X_GESAMT - 0.8)
    _text(c, font, 10, X_GESAMT, text_top, "Gesamt", align="right", right=X_RIGHT - 0.6)


def _summenblock(c: canvas.Canvas, font: str, bold: str, netto: Decimal, mwst: Decimal, brutto: Decimal, prozent: str) -> None:
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.75)
    bottom = PAGE_H - Y_SUMME - SUMME_HOEHE
    c.rect(X_LEFT, bottom, X_RIGHT - X_LEFT, SUMME_HOEHE, stroke=1, fill=0)
    c.line(X_BEZ, bottom, X_BEZ, bottom + SUMME_HOEHE)
    c.line(X_GESAMT, bottom, X_GESAMT, bottom + SUMME_HOEHE)
    mitte = PAGE_H - (Y_SUMME + 16.2)
    c.line(X_LEFT, mitte, X_RIGHT, mitte)
    _text(c, font, 10, 58.6, Y_SUMME + 2.1, "Netto")
    _text(c, font, 10, 120.2, Y_SUMME + 2.9, prozent)
    _text(c, bold, 10, X_GESAMT, Y_SUMME + 2.9, "Summe", align="right", right=X_RIGHT - 2)
    _text(c, font, 10, 58.6, Y_SUMME + 17.6, format_euro(netto))
    _text(c, font, 10, 120.2, Y_SUMME + 17.6, format_euro(mwst))
    _text(c, bold, 10, X_GESAMT, Y_SUMME + 17.6, format_euro(brutto), align="right", right=X_RIGHT - 2)


def _bankblock(
    c: canvas.Canvas,
    font: str,
    bold: str,
    stamm: Stammdaten,
    layout: RechnungsLayout,
    seite: int,
    seiten: int,
    zugferd: bool,
) -> None:
    if zugferd:
        _text(c, bold, 10, X_TEXT, Y_ZUGFERD, "Elektronische Rechnung im Format ZUGFeRD (Profil XRechnung)")
    elif layout.zeige_fusszeile and stamm.fusszeile:
        _text(c, bold, 9.75, PAGE_W / 2, Y_ZUGFERD, stamm.fusszeile, align="center")
    if layout.zeige_fusszeile:
        bank = stamm.bank
        mitte = (155.6 + 467.4) / 2
        if bank.name:
            _text(c, font, 10, mitte, Y_BANK, bank.name, align="center")
        iban_bic = "   ".join(
            t for t in (f"IBAN {bank.iban}" if bank.iban else "", f"BIC {bank.bic}" if bank.bic else "") if t
        )
        if iban_bic:
            _text(c, font, 10, mitte, Y_IBAN, iban_bic, align="center")
        steuer_ust = "   ".join(
            t
            for t in (
                f"Steuer-Nr. {stamm.steuernummer}" if stamm.steuernummer else "",
                f"USt-ID: {stamm.ust_id}" if stamm.ust_id else "",
            )
            if t
        )
        if steuer_ust:
            _text(c, font, 10, mitte, Y_STEUER, steuer_ust, align="center")
    _text(c, bold, 10, X_RIGHT - 1.4, Y_SEITE, f"Seite {seite} von {seiten}", align="right", right=X_RIGHT - 1.4)


def _qr(c: canvas.Canvas, payload: str) -> None:
    import segno
    from reportlab.lib.utils import ImageReader

    buffer = io.BytesIO()
    segno.make(payload, error="m").save(buffer, kind="png", scale=6, border=0)
    buffer.seek(0)
    c.drawImage(ImageReader(buffer), 108, PAGE_H - Y_ZAHLCODE - 36, width=36, height=36, mask="auto")


class _Zeile:
    def __init__(self, menge: str, bezeichnung: list[str], freitext: list[str], ep: str | None, gesamt: str | None, wert: Decimal):
        self.menge = menge
        self.bezeichnung = bezeichnung or [""]
        self.freitext = freitext
        self.ep = ep
        self.gesamt = gesamt
        self.wert = wert

    @property
    def vorschub(self) -> float:
        extra = max(0, len(self.bezeichnung) - 1) * FREITEXT_WEITER
        if not self.freitext:
            return ZEILE + extra
        return FREITEXT_ERSTE + extra + FREITEXT_WEITER * (len(self.freitext) - 1) + NACH_FREITEXT


def _zeilen(rechnung: Rechnung, font: str) -> list[_Zeile]:
    breite_bez = X_EP - X_BEZ_TEXT - 8
    breite_frei = X_EP - X_FREITEXT - 8
    zeilen = []
    for position in sortierte_positionen(rechnung):
        menge = Decimal(position.menge)
        sichtbar = menge != 0
        menge_text = ""
        if sichtbar:
            menge_text = format_menge(menge)
            if (position.mengeneinheit or "").strip():
                menge_text = f"{menge_text} {position.mengeneinheit.strip()}"
        wert = menge * Decimal(position.preis)
        ep = format_euro(Decimal(position.preis)) if sichtbar and menge != 1 else None
        gesamt = format_euro(wert) if sichtbar else None
        zeilen.append(
            _Zeile(
                menge_text,
                _wrap(position.bezeichnung or "", font, 10, breite_bez),
                _wrap(position.freitext or "", font, 10, breite_frei),
                ep,
                gesamt,
                wert if sichtbar else Decimal("0"),
            )
        )
    return zeilen


def _packen(zeilen: list[_Zeile]) -> list[list[_Zeile]]:
    if not zeilen:
        return [[]]
    seiten: list[list[_Zeile]] = [[]]
    y = Y_ERSTE_ZEILE
    for zeile in zeilen:
        if seiten[-1] and y + zeile.vorschub > ZEILEN_ENDE:
            seiten.append([])
            y = Y_ERSTE_ZEILE
        seiten[-1].append(zeile)
        y += zeile.vorschub
    return seiten


def _zeichne_zeilen(c: canvas.Canvas, font: str, zeilen: list[_Zeile], start: float) -> Decimal:
    y = start
    summe = Decimal("0")
    for zeile in zeilen:
        _text(c, font, 10, X_MENGE, y, zeile.menge)
        by = y
        for line in zeile.bezeichnung:
            _text(c, font, 10, X_BEZ_TEXT, by, line)
            by += FREITEXT_WEITER
        if zeile.ep:
            _text(c, font, 10, X_EP, y, zeile.ep, align="right", right=X_GESAMT)
        if zeile.gesamt:
            _text(c, font, 10, X_GESAMT, y, zeile.gesamt, align="right", right=X_RIGHT)
            summe += zeile.wert
        fy = y + FREITEXT_ERSTE + max(0, len(zeile.bezeichnung) - 1) * FREITEXT_WEITER
        for line in zeile.freitext:
            _text(c, font, 10, X_FREITEXT, fy, line)
            fy += FREITEXT_WEITER
        y += zeile.vorschub
    return summe


def rechnung_pdf(
    rechnung: Rechnung,
    original: Rechnung | None = None,
    briefpapier: bool = True,
    stammdaten: Stammdaten | None = None,
    layout: RechnungsLayout | None = None,
) -> bytes:
    stamm = stammdaten or STANDARD_STAMMDATEN
    aktives_layout = layout or RechnungsLayout(
        vorlage=stamm.layout_vorlage or "standard",
        nutze_briefpapier=False,
        zeige_qr_code=briefpapier,
    )
    font, bold = _fonts()
    positionen = sortierte_positionen(rechnung)
    netto, mwst, brutto = pdf_betraege(
        sum((Decimal(p.menge) * Decimal(p.preis) for p in positionen), Decimal("0")),
        rechnung.datum,
        rechnung.keine_mehrwertsteuer,
    )
    bank = stamm.bank
    storno = original is not None or rechnung.storno_zu_rechnung_id is not None
    nummer = rechnung.rechnungs_nr or ""
    if storno:
        titel = f"Storno-Rechnung Nr. {nummer}"
        original_nr = original.rechnungs_nr if original is not None and original.rechnungs_nr else ""
        untertitel = f"Stornierte Rechnung: {original_nr}"
    else:
        titel = f"Rechnung Nr. {nummer}"
        untertitel = f"Leistungszeitraum: {rechnung.leistungszeitraum or ''}"
    if rechnung.keine_mehrwertsteuer:
        prozent = "MwSt."
    else:
        prozent = f"MwSt. {int((mwst_satz(rechnung.datum) * 100).to_integral_value())}%"
    zeilen = _zeilen(rechnung, font)
    seiten = _packen(zeilen)
    anzahl = len(seiten)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(f"Rechnung {nummer}")
    pdf.setAuthor(stamm.name)
    uebertrag = Decimal("0")
    ort_prefix = f"{stamm.ort}, " if (stamm.ort or "").strip() else ""
    for index, seite in enumerate(seiten, start=1):
        letzte = index == anzahl
        _anschrift(pdf, font, rechnung, stamm, aktives_layout)
        _text(pdf, bold, 9.75, X_TEXT, Y_TITEL, titel)
        _text(pdf, font, 10, X_RECHTS, Y_TITEL, f"{ort_prefix}{rechnung.datum:%d.%m.%Y}")
        _text(pdf, font, 10, X_LEISTUNG, Y_LEISTUNG, untertitel)
        if aktives_layout.zeige_kontaktdaten:
            if stamm.telefon:
                _text(pdf, font, 8.25, X_RECHTS, Y_TEL, "Tel:")
                _text(pdf, font, 8.25, X_TELEFON, Y_TEL, stamm.telefon)
            if stamm.email:
                _text(pdf, font, 8.25, X_RECHTS, Y_MAIL, f"e-Mail: {stamm.email}")
        _spaltenkopf(pdf, font, Y_KOPF)
        start = Y_ERSTE_ZEILE
        if index == 1 and not storno:
            _text(pdf, font, 10, 120.2, Y_EINLEITUNG, stamm.einleitungstext or "Hiermit stellen wir Ihnen folgende Leistungen in Rechnung:")
        elif index > 1:
            _text(pdf, bold, 9.75, X_GESAMT, Y_EINLEITUNG, f"Übertrag: {format_euro(uebertrag)}", align="right", right=X_RIGHT)
        uebertrag += _zeichne_zeilen(pdf, font, seite, start)
        if letzte:
            hinweis = reverse_charge_text(rechnung.keine_mehrwertsteuer, rechnung.umsatzsteuer_id)
            if hinweis:
                hy = Y_SUMME - 28
                for line in hinweis.split("\n"):
                    _text(pdf, font, 10, X_TEXT, hy, line)
                    hy += 12
            _summenblock(pdf, font, bold, netto, mwst, brutto, prozent)
            if not storno and stamm.zahlungstext:
                _text(pdf, font, 10, X_TEXT, Y_ZAHLUNG, stamm.zahlungstext)
            _bankblock(pdf, font, bold, stamm, aktives_layout, index, anzahl, zugferd=True)
            if aktives_layout.zeige_qr_code and brutto != 0 and nummer and bank.iban and bank.bic:
                try:
                    payload = epc_payload(stamm.name, bank.iban, bank.bic, runde_qr(brutto), nummer)
                    _text(pdf, font, 10, X_TEXT, Y_ZAHLCODE, "Zahlcode:")
                    _qr(pdf, payload)
                except ValueError:
                    pass
        else:
            _text(pdf, bold, 9.75, X_GESAMT, Y_SUMME, f"Übertrag: {format_euro(uebertrag)}", align="right", right=X_RIGHT)
            _bankblock(pdf, font, bold, stamm, aktives_layout, index, anzahl, zugferd=False)
        pdf.showPage()
    pdf.save()
    return _einbetten(buffer.getvalue(), xrechnung_xml(rechnung, original, stammdaten=stamm), kompakt=not briefpapier)


def runde_qr(betrag: Decimal) -> Decimal:
    return Decimal(betrag).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def mahnung_pdf(
    rechnung: Rechnung,
    heute: date,
    stammdaten: Stammdaten | None = None,
    layout: RechnungsLayout | None = None,
) -> bytes:
    stamm = stammdaten or STANDARD_STAMMDATEN
    aktives_layout = layout or RechnungsLayout(vorlage=stamm.layout_vorlage or "standard")
    font, bold = _fonts()
    daten = mahnung_daten(rechnung, heute)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(f"Mahnung {rechnung.rechnungs_nr or ''}")
    pdf.setAuthor(stamm.name)
    _anschrift(pdf, font, rechnung, stamm, aktives_layout)
    _text(pdf, bold, 9.75, X_TEXT, Y_TITEL, "Mahnung")
    ort_prefix = f"{stamm.ort}, " if (stamm.ort or "").strip() else ""
    _text(pdf, font, 10, X_RECHTS, Y_TITEL, f"{ort_prefix}{heute:%d.%m.%Y}")
    y = Y_KOPF
    _text(pdf, font, 10, X_TEXT, y, "Sehr geehrte Damen und Herren,")
    y += 28
    for absatz in daten["text"].split("\n"):
        if not absatz.strip():
            y += 12
            continue
        for line in _wrap(absatz, font, 10, 480):
            _text(pdf, font, 10, X_TEXT, y, line)
            y += 13
    y += 16
    _text(pdf, font, 10, X_TEXT, y, "Mit freundlichen Grüßen")
    _text(pdf, font, 10, X_TEXT, y + 16, stamm.name)
    _bankblock(pdf, font, bold, stamm, aktives_layout, 1, 1, zugferd=False)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _mit_output_intent(pdf: bytes, icc_bytes: bytes | None = None) -> bytes:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, create_string_object

    reader = PdfReader(io.BytesIO(pdf))
    writer = PdfWriter()
    writer.append(reader)
    profil = DecodedStreamObject()
    profil.set_data(icc_bytes if icc_bytes is not None else SRGB.read_bytes())
    profil.update({NameObject("/N"): NumberObject(3)})
    intent = DictionaryObject()
    intent.update({
        NameObject("/Type"): NameObject("/OutputIntent"),
        NameObject("/S"): NameObject("/GTS_PDFA1"),
        NameObject("/OutputConditionIdentifier"): create_string_object("sRGB IEC61966-2.1"),
        NameObject("/DestOutputProfile"): writer._add_object(profil),
    })
    writer._root_object[NameObject("/OutputIntents")] = ArrayObject([intent])
    if reader.metadata:
        writer.add_metadata({key: value for key, value in reader.metadata.items() if value})
    writer.generate_file_identifiers()
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _einbetten(pdf: bytes, xml: bytes, kompakt: bool = False) -> bytes:
    import tempfile

    from facturx import generate_from_file

    descriptor, name = tempfile.mkstemp(suffix=".pdf")
    os.close(descriptor)
    out = name + ".facturx.pdf"
    try:
        Path(name).write_bytes(_mit_output_intent(pdf))
        generate_from_file(
            name,
            xml,
            flavor="factur-x",
            level="en16931",
            check_xsd=False,
            output_pdf_file=out,
            lang="de-DE",
            xmp_compression=kompakt,
        )
        ergebnis = Path(out).read_bytes()
        if kompakt:
            try:
                import pymupdf

                doc = pymupdf.open(stream=ergebnis, filetype="pdf")
                try:
                    ergebnis = doc.tobytes(garbage=4, deflate=True, deflate_fonts=True)
                finally:
                    doc.close()
            except Exception:
                pass
        return ergebnis
    finally:
        for path in (name, out):
            try:
                os.remove(path)
            except OSError:
                pass
