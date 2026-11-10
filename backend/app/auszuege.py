"""Liest Konto- und Kartenabrechnungen. Keine Kontierung."""

import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree

_BETRAG = re.compile(r"[+-]?\d{1,3}(?:\.\d{3})*,\d{2}")
_BETRAG_FLEX = re.compile(r"[+-]?(?:\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2}|\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2})")
_N26 = re.compile(
    r"Wertstellung\s+(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})\s+([+-]?\d{1,3}(?:\.\d{3})*,\d{2})"
)
_AMEX = re.compile(
    r"^(\d{2})\.(\d{2})\s+(\d{2})\.(\d{2})\s+(.+?)\s+([+-]?\d{1,3}(?:\.\d{3})*,\d{2})$"
)
_MILES = re.compile(
    r"^(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})\s+(.+?)\s+([+-]\d{1,3}(?:\.\d{3})*,\d{2})$"
)
_VOBA_PDF = re.compile(
    r"^(\d{2})\.(\d{2})\.\s+(\d{2})\.(\d{2})\.\s+(.+?)\s+(\d{1,3}(?:\.\d{3})*,\d{2})\s+([SH])$"
)
_N26_RAUS = (
    "beschreibung",
    "verbuchungsdatum",
    "betrag",
    "kontoauszug",
    "erstellt am",
    "kirchhöfnerstr",
)
_MONATE = {
    "jan": 1, "januar": 1, "january": 1,
    "feb": 2, "februar": 2, "february": 2,
    "mär": 3, "maerz": 3, "märz": 3, "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "mai": 5, "may": 5,
    "jun": 6, "juni": 6, "june": 6,
    "jul": 7, "juli": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "okt": 10, "oktober": 10, "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dez": 12, "dezember": 12, "dec": 12, "december": 12,
}


def euro(text: str) -> Decimal:
    sauber = re.sub(r"[€$£\s]|EUR|USD", "", text or "", flags=re.I).strip()
    if sauber.startswith("+"):
        sauber = sauber[1:]
    if "," in sauber and "." in sauber:
        if sauber.rfind(",") > sauber.rfind("."):
            sauber = sauber.replace(".", "").replace(",", ".")
        else:
            sauber = sauber.replace(",", "")
    elif "," in sauber:
        sauber = sauber.replace(".", "").replace(",", ".")
    return Decimal(sauber).quantize(Decimal("0.01"))


def datum_de(text: str) -> date:
    tag, monat, jahr = text.strip().split(".")
    jahr_i = int(jahr)
    if jahr_i < 100:
        jahr_i += 2000
    return date(jahr_i, int(monat), int(tag))


def parse_datum_flex(text: str) -> date | None:
    if not text:
        return None
    roh = text.strip()
    treffer = re.search(r"(?<!\d)(\d{2})[./](\d{2})[./](20\d{2}|\d{2})(?!\d)", roh)
    if treffer:
        try:
            jahr = int(treffer.group(3))
            if jahr < 100:
                jahr += 2000
            return date(jahr, int(treffer.group(2)), int(treffer.group(1)))
        except ValueError:
            pass
    treffer = re.search(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)", roh)
    if treffer:
        try:
            return date(int(treffer.group(1)), int(treffer.group(2)), int(treffer.group(3)))
        except ValueError:
            pass
    treffer = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", roh)
    if treffer:
        try:
            return date(int(treffer.group(1)), int(treffer.group(2)), int(treffer.group(3)))
        except ValueError:
            pass
    treffer = re.search(
        r"\b(\d{1,2})\.?(?:\s+|-)\s*([A-Za-zäöüÄÖÜ]{3,10})\.?,?(?:\s+|-)\s*(20\d{2})\b",
        roh,
    )
    if treffer:
        monat = _MONATE.get(treffer.group(2).casefold().rstrip("."))
        if monat:
            try:
                return date(int(treffer.group(3)), monat, int(treffer.group(1)))
            except ValueError:
                pass
    treffer = re.search(
        r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(20\d{2})\b",
        roh,
    )
    if treffer:
        monat = _MONATE.get(treffer.group(1).casefold().rstrip("."))
        if monat:
            try:
                return date(int(treffer.group(3)), monat, int(treffer.group(2)))
            except ValueError:
                pass
    return None


def pdf_text(inhalt: bytes) -> str:
    import pymupdf

    doc = pymupdf.open(stream=inhalt, filetype="pdf")
    teile = [seite.get_text("text") for seite in doc]
    return "\n".join(teile)


def pdf_zeilen(inhalt: bytes) -> list[str]:
    import pymupdf

    doc = pymupdf.open(stream=inhalt, filetype="pdf")
    zeilen: list[str] = []
    for seite in doc:
        woerter = sorted(seite.get_text("words"), key=lambda wort: (wort[1], wort[0]))
        gruppen: list[list] = []
        anker = None
        for wort in woerter:
            if anker is None or abs(wort[1] - anker) > 2:
                gruppen.append([wort])
                anker = wort[1]
            else:
                gruppen[-1].append(wort)
        for gruppe in gruppen:
            zeilen.append(" ".join(wort[4] for wort in sorted(gruppe, key=lambda wort: wort[0])))
    return zeilen


def parse_n26(text: str, kontoinhaber: str = "") -> list[dict]:
    text = text.replace("\u00a0", " ").replace("€", "")
    inhaber = (kontoinhaber or "").strip().casefold()
    treffer = list(_N26.finditer(text))
    bewegungen = []
    anfang = 0
    for treffer_eintrag in treffer:
        block = text[anfang:treffer_eintrag.start()]
        anfang = treffer_eintrag.end()
        zeilen = []
        for roh in block.splitlines():
            zeile = " ".join(roh.split())
            if not zeile:
                continue
            klein = zeile.casefold()
            if klein.startswith(_N26_RAUS) or (inhaber and klein.startswith(inhaber)):
                continue
            if klein.startswith("iban:") or klein.startswith("nr. "):
                continue
            if re.fullmatch(r"\d+ / \d+", zeile):
                continue
            if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}(?:\s+bis\s+\d{2}\.\d{2}\.\d{4})?", zeile, re.I):
                continue
            if "seite " in klein and " / " in klein:
                continue
            zeilen.append(zeile)
        if not zeilen:
            continue
        bewegungen.append(
            {
                "datum": datum_de(treffer_eintrag.group(2)),
                "betrag": euro(treffer_eintrag.group(3)),
                "waehrung": "EUR",
                "gegenpartei": zeilen[0][:200],
                "zweck": " ".join(zeilen[1:])[:500],
            }
        )
    return bewegungen


def parse_amex(inhalt: bytes) -> list[dict]:
    zeilen = pdf_zeilen(inhalt)
    text = "\n".join(zeilen)
    ende = re.search(r"bis\s+(\d{2})\.(\d{2})\.(\d{2})", text)
    end_monat = int(ende.group(2)) if ende else 12
    end_jahr = 2000 + int(ende.group(3)) if ende else date.today().year
    bewegungen: list[dict] = []
    offen = False
    for roh in zeilen:
        zeile = " ".join(roh.split())
        treffer = _AMEX.match(zeile)
        if treffer:
            if "saldo" in zeile.casefold():
                offen = False
                continue
            buchung_tag = int(treffer.group(3))
            buchung_monat = int(treffer.group(4))
            jahr = end_jahr if buchung_monat <= end_monat else end_jahr - 1
            betrag = euro(treffer.group(6))
            text_zeile = treffer.group(5)
            if not re.search(r"zahlung|gutschrift|erhalten", text_zeile, re.I):
                betrag = -abs(betrag)
            else:
                betrag = abs(betrag)
            bewegungen.append(
                {
                    "datum": date(jahr, buchung_monat, buchung_tag),
                    "betrag": betrag,
                    "waehrung": "EUR",
                    "gegenpartei": text_zeile[:200],
                    "zweck": "",
                }
            )
            offen = True
        elif offen and bewegungen:
            if re.fullmatch(r"[\d.,\s+-]{3,40}", zeile) or re.search(
                r"\b(?:US Dollars|USD|GBP|CHF|Referenzwechselkurs)\b", zeile, re.I
            ):
                bisher = bewegungen[-1]["zweck"]
                bewegungen[-1]["zweck"] = f"{bisher} {zeile}".strip()[:500]
            else:
                offen = False
    return bewegungen


def parse_miles(inhalt: bytes) -> list[dict]:
    bewegungen = []
    for zeile in pdf_zeilen(inhalt):
        zeile = " ".join(zeile.split())
        if zeile.casefold().startswith("saldo") or zeile.casefold().startswith("meilen"):
            continue
        treffer = _MILES.match(zeile)
        if not treffer:
            continue
        bewegungen.append(
            {
                "datum": datum_de(treffer.group(2)),
                "betrag": euro(treffer.group(4)),
                "waehrung": "EUR",
                "gegenpartei": treffer.group(3)[:200],
                "zweck": "",
            }
        )
    return bewegungen


def parse_volksbank_pdf(inhalt: bytes) -> list[dict]:
    zeilen = pdf_zeilen(inhalt)
    text = "\n".join(zeilen)
    jahr_treffer = (
        re.search(r"neuer Kontostand vom\s+\d{2}\.(\d{2})\.(\d{4})", text, re.I)
        or re.search(r"erstellt am\s+\d{2}\.(\d{2})\.(\d{4})", text, re.I)
    )
    end_monat = int(jahr_treffer.group(1)) if jahr_treffer else 12
    end_jahr = int(jahr_treffer.group(2)) if jahr_treffer else date.today().year
    bewegungen: list[dict] = []
    aktuell: dict | None = None
    details: list[str] = []

    def abschliessen() -> None:
        nonlocal aktuell, details
        if aktuell is None:
            return
        vorgang = aktuell.pop("vorgang")
        if details:
            aktuell["gegenpartei"] = details[0][:200]
            aktuell["zweck"] = " ".join([vorgang] + details[1:])[:500]
        else:
            aktuell["gegenpartei"] = "Volksbank"
            aktuell["zweck"] = vorgang[:500]
        bewegungen.append(aktuell)
        aktuell = None
        details = []

    aktiv = False
    for roh in zeilen:
        zeile = " ".join(roh.split())
        klein = zeile.casefold()
        if "alter kontostand" in klein:
            aktiv = True
            continue
        if not aktiv:
            continue
        if "neuer kontostand" in klein or klein.startswith("anlage ") or "───" in zeile or "──" in zeile:
            abschliessen()
            if "neuer kontostand" in klein or klein.startswith("anlage "):
                break
            continue
        treffer = _VOBA_PDF.match(zeile)
        if treffer:
            abschliessen()
            tag = int(treffer.group(1))
            monat = int(treffer.group(2))
            jahr = end_jahr if monat <= end_monat else end_jahr - 1
            betrag = euro(treffer.group(6))
            if treffer.group(7).upper() == "S":
                betrag = -abs(betrag)
            else:
                betrag = abs(betrag)
            aktuell = {
                "datum": date(jahr, monat, tag),
                "betrag": betrag,
                "waehrung": "EUR",
                "gegenpartei": "",
                "zweck": "",
                "vorgang": treffer.group(5).strip(),
            }
        elif aktuell is not None and zeile:
            details.append(zeile)
    abschliessen()
    return bewegungen


def _spalte(zeile: dict, *namen: str) -> str:
    gesucht = {name.casefold() for name in namen}
    for key, wert in zeile.items():
        if key and key.strip().casefold() in gesucht:
            return (wert or "").strip()
    for key, wert in zeile.items():
        if key and any(name in key.strip().casefold() for name in gesucht):
            return (wert or "").strip()
    return ""


def parse_volksbank_csv(inhalt: bytes) -> list[dict]:
    text = _text_csv(inhalt)
    zeilen = text.splitlines()
    kopf = None
    for index, zeile in enumerate(zeilen):
        klein = zeile.casefold()
        if "betrag" in klein and ("buchung" in klein or "valuta" in klein):
            kopf = index
            break
    if kopf is None:
        raise ValueError("Volksbank-CSV ohne Spalten Buchung und Betrag.")
    trenner = ";" if zeilen[kopf].count(";") >= zeilen[kopf].count(",") else ","
    leser = csv.DictReader(zeilen[kopf:], delimiter=trenner)
    bewegungen = []
    for zeile in leser:
        betrag_text = _spalte(zeile, "betrag")
        datum_text = _spalte(zeile, "buchungstag", "buchung")
        if not betrag_text or not datum_text or not _BETRAG.search(betrag_text):
            continue
        betrag = euro(_BETRAG.search(betrag_text).group(0))
        richtung = _spalte(zeile, "soll/haben", "s/h").casefold()
        if richtung.startswith("s") and betrag > 0:
            betrag = -betrag
        if richtung.startswith("h") and betrag < 0:
            betrag = -betrag
        bewegungen.append(
            {
                "datum": datum_de(re.search(r"\d{2}\.\d{2}\.\d{2,4}", datum_text).group(0)),
                "betrag": betrag,
                "waehrung": (_spalte(zeile, "währung", "waehrung") or "EUR")[:3],
                "gegenpartei": _spalte(zeile, "auftraggeber/zahlungsempfänger", "auftraggeber", "empfaenger", "name")[:200],
                "zweck": _spalte(zeile, "verwendungszweck", "buchungstext")[:500],
            }
        )
    return bewegungen


def parse_camt(inhalt: bytes) -> list[dict]:
    wurzel = ElementTree.fromstring(inhalt)
    bewegungen = []
    for knoten in wurzel.iter():
        if _lokal(knoten) != "Ntry":
            continue
        betrag_knoten = _kind(knoten, "Amt")
        if betrag_knoten is None or not betrag_knoten.text:
            continue
        betrag = Decimal(betrag_knoten.text).quantize(Decimal("0.01"))
        richtung = _kind(knoten, "CdtDbtInd")
        if richtung is not None and (richtung.text or "").upper() == "DBIT":
            betrag = -betrag
        datum_text = ""
        buchung = _kind(knoten, "BookgDt")
        if buchung is not None:
            tag = _kind(buchung, "Dt")
            if tag is not None and tag.text:
                datum_text = tag.text[:10]
        if not datum_text:
            continue
        name = ""
        zweck = ""
        for unter in knoten.iter():
            if _lokal(unter) == "Nm" and unter.text and not name:
                name = unter.text
            if _lokal(unter) == "Ustrd" and unter.text:
                zweck = unter.text
        bewegungen.append(
            {
                "datum": date.fromisoformat(datum_text),
                "betrag": betrag,
                "waehrung": (betrag_knoten.attrib.get("Ccy") or "EUR")[:3],
                "gegenpartei": name[:200],
                "zweck": zweck[:500],
            }
        )
    return bewegungen


def parse_kontoauszug(quelle: str, name: str, inhalt: bytes, kontoinhaber: str = "") -> list[dict]:
    if quelle == "n26":
        return parse_n26(pdf_text(inhalt), kontoinhaber)
    if quelle == "amex":
        return parse_amex(inhalt)
    if quelle == "miles":
        return parse_miles(inhalt)
    if quelle == "volksbank":
        if inhalt.lstrip().startswith(b"%PDF") or (name or "").lower().endswith(".pdf"):
            return parse_volksbank_pdf(inhalt)
        if inhalt.lstrip().startswith(b"<"):
            return parse_camt(inhalt)
        return parse_volksbank_csv(inhalt)
    raise ValueError(f"Unbekannte Quelle {quelle}.")


def _erkenne_betrag(text: str) -> tuple[Decimal | None, str]:
    sicher_muster = (
        r"(?:zu zahlender\s+gesamtbetrag|zu zahlender\s+betrag|rechnungsbetrag|"
        r"gesamtbetrag(?:\s*\(inkl\.\s*mwst\.?\))?|bruttorechnungsbetrag|"
        r"gesamtsumme\s+brutto|gesamt\s+brutto|rechnungsendbetrag|rechnungssumme|"
        r"zahlbetrag|gesamtpreis(?!\s*(?:inkl|leistungszeitraum))|endsumme|endbetrag|bruttobetrag|"
        r"total\s+eur\s+inkl\.?\s*mwst\.?|total\s+including\s+vat|"
        r"document\s+total|invoice\s+total|payment\s+amount|amount\s+due|"
        r"gesamtsumme\s+in\s+eur|rechnung\s*•\s*betrag|zu\s+zahlen)"
    )
    kandidaten: list[Decimal] = []
    for treffer in re.finditer(sicher_muster, text, re.I):
        vor = text[max(0, treffer.start() - 20):treffer.start()].casefold()
        if "netto" in vor or "ohne" in vor:
            continue
        fenster = text[treffer.end():treffer.end() + 80]
        if re.match(r"\s+ist\s+sofort", fenster, re.I):
            continue
        # Prüfe auf Netto + Steuer = Brutto direkt nach dem Schlüsselwort (z. B. Google Cloud)
        drei = [euro(z.group(0)) for z in _BETRAG.finditer(fenster)]
        if len(drei) >= 3 and drei[0] > 0 and abs((drei[0] + drei[1]) - drei[2]) <= Decimal("0.02"):
            kandidaten.append(drei[2])
            continue
        zahl = _BETRAG.search(fenster) or _BETRAG_FLEX.search(fenster)
        if zahl is None:
            vor_fenster = text[max(0, treffer.start() - 40):treffer.start()]
            vor_zahlen = list(_BETRAG.finditer(vor_fenster))
            zahl = vor_zahlen[-1] if vor_zahlen else None
        if zahl is not None:
            try:
                wert = euro(zahl.group(0))
                if wert > 0:
                    kandidaten.append(wert)
            except (InvalidOperation, ValueError):
                pass
    if kandidaten:
        return kandidaten[-1], "sicher"

    # Tabellen-Summenblock: Netto + Steuer = Brutto (z. B. Hetzner, Ausgangsrechnungen, Vodafone)
    for treffer in re.finditer(r"\b(?:summe|brutto|gesamt)\b", text, re.I):
        fenster = text[treffer.end():treffer.end() + 120]
        zahlen = [euro(z.group(0)) for z in _BETRAG.finditer(fenster)]
        if len(zahlen) >= 3:
            a, b, c = zahlen[0], zahlen[1], zahlen[2]
            if a > 0 and b >= 0 and c >= a and abs((a + b) - c) <= Decimal("0.02"):
                return c, "sicher"

    geraten_kandidaten: list[Decimal] = []
    for treffer in re.finditer(r"\b(?:gesamt|total|summe)\b", text, re.I):
        zeilen_start = text.rfind("\n", 0, treffer.start()) + 1
        zeilen_ende = text.find("\n", treffer.end())
        if zeilen_ende < 0:
            zeilen_ende = len(text)
        zeilen_kontext = text[zeilen_start:zeilen_ende].casefold()
        if any(w in zeilen_kontext for w in ("ust", "netto", "net ", "tax ", "ohne", "positionen", "zwischen", "subtotal", "summe betrag", "wäh.")):
            continue
        fenster = text[treffer.end():treffer.end() + 50]
        zahl = _BETRAG.search(fenster) or _BETRAG_FLEX.search(fenster)
        if zahl is None:
            zahl = _BETRAG.search(text[max(0, treffer.start() - 30):treffer.start()])
        if zahl is not None:
            try:
                wert = euro(zahl.group(0))
                if wert > 0:
                    geraten_kandidaten.append(wert)
            except (InvalidOperation, ValueError):
                pass
    if geraten_kandidaten:
        return geraten_kandidaten[-1], "geraten"
    return None, ""


def _erkenne_datum(text: str, dateiname: str = "") -> tuple[date | None, str]:
    for muster in (
        r"(?:rechnungsdatum(?:\s*/\s*lieferdatum)?|rechnungs-\s*\+\s*leistungsdatum|belegdatum|invoice\s*date|rechnung\s*•\s*datum|[A-Za-zäöüÄÖÜß-]{3,},\s*(?:den\s+)?)\s*[:\s]*([^\n]{6,40})",
        r"(?:^|\n)\s*(?:datum|date)\s*[:\s]*([^\n]{6,30})",
    ):
        for treffer in re.finditer(muster, text, re.I):
            fenster = text[treffer.start(1):treffer.start(1) + 120]
            erkannt = parse_datum_flex(fenster)
            if erkannt and 2000 <= erkannt.year <= 2035:
                return erkannt, "sicher"
    erkannt = parse_datum_flex(text)
    if erkannt and 2000 <= erkannt.year <= 2035:
        return erkannt, "geraten"
    if dateiname:
        sauber = re.sub(r"^\d{14,16}-", "", Path(dateiname).stem)
        aus_name = parse_datum_flex(sauber)
        if aus_name and 2000 <= aus_name.year <= 2035:
            return aus_name, "geraten"
    return None, ""


def _sauber_partner_zeile(zeile: str) -> str:
    zeile = re.sub(r"^(?:Kontoinhaber|Verkauft von|Vertragspartner)\s*:?\s*", "", zeile, flags=re.I).strip()
    teile = re.split(r"\s*[•·|]\s*|\s+-\s+", zeile)
    if teile and len(teile[0].strip()) >= 4:
        zeile = teile[0].strip()
    zeile = re.sub(r",\s*(?:\d{5}\b|[A-Za-zäöüÄÖÜß-]+(?:str\.|straße|allee|platz|weg)\b).*$", "", zeile, flags=re.I).strip()
    zeile = re.sub(r"\s+KundenBetreuung\s+\d{5}.*$", "", zeile, flags=re.I).strip()
    return zeile[:200]


def _erkenne_partner(text: str, dateiname: str = "", eigene_namen: tuple[str, ...] = ()) -> tuple[str, str]:
    zeilen = [" ".join(z.split()) for z in (text or "").splitlines() if " ".join(z.split())]
    eigen = {n.strip().casefold() for n in eigene_namen if len(n.strip()) >= 4}
    # Ausgangsrechnungen: Empfänger steht direkt unter der einzeiligen Absenderzeile (Name • Straße • PLZ Ort)
    for idx, zeile in enumerate(zeilen[:5]):
        if re.match(r"^[^•·|\n]{3,60}\s*[•·|]\s*[^•·|\n]{3,60}\s*[•·|]\s*\d{4,5}\s+\S+", zeile) and idx + 1 < len(zeilen):
            absender_teil = re.split(r"\s*[•·|]\s*", zeile)[0].strip().casefold()
            empfaenger = _sauber_partner_zeile(zeilen[idx + 1])
            klein_empf = empfaenger.casefold()
            if empfaenger and absender_teil not in klein_empf and not any(e in klein_empf for e in eigen):
                return empfaenger, "sicher"

    for muster in (
        r"Informationen zum Rechnungsersteller:\s*\n\s*([^\n]+)",
        r"Verkauft von\s+([^\n]+)",
        r"powered by\s*\n?\s*([A-Za-z0-9 .&-]+(?:B\.V\.|GmbH|Ltd\.?|Inc\.?|AG))",
    ):
        treffer = re.search(muster, text or "", re.I)
        if treffer:
            kandidat = _sauber_partner_zeile(" ".join(treffer.group(1).split())).rstrip(")")
            if len(kandidat) >= 4 and not any(e in kandidat.casefold() for e in eigen):
                return kandidat, "sicher"

    rechtsform = re.compile(
        r"\b(GmbH|AG|KG|UG|Ltd\.?|Limited|Inc\.?|SARL|S\.a\.?\s*r\.?l\.?|B\.V\.|e\.K\.|GbR|SE|eG|Steuerberater)\b"
    )
    for zeile in zeilen:
        if len(zeile) < 4 or len(zeile) > 140:
            continue
        klein = zeile.casefold()
        if any(e in klein for e in eigen):
            continue
        if re.match(r"^ag\s+[a-zäöüß]", klein):
            continue
        if any(w in klein for w in (
            "endkunde", "net total for", "tax total for", "billed to",
            "rechnungsempfänger", "pers. haftende", "registergericht",
            "amtsgericht", "handelsregister", "vertragspartner",
            "bauverein", "wohnungsgenossenschaft", "wohnungsbaugenossenschaft",
        )):
            continue
        if rechtsform.search(zeile):
            return _sauber_partner_zeile(zeile), "sicher"

    if dateiname:
        return Path(dateiname).stem[:120], "geraten"
    return "", ""


_KEINE_NUMMER = {
    "kunden-nr", "kunden-nr.", "ust-id", "ust-idnr", "datum", "seite",
}


def _ist_rechnungsnummer(wert: str) -> bool:
    sauber = (wert or "").strip().rstrip(".,;:")
    if len(sauber) < 3 or len(sauber) > 40:
        return False
    if sauber.casefold() in _KEINE_NUMMER:
        return False
    if not any(ch.isdigit() for ch in sauber):
        return False
    if re.fullmatch(r"\d{2}[./]\d{2}[./]\d{2,4}", sauber):
        return False
    return True


def _erkenne_nummer(text: str, dateiname: str = "") -> str:
    # Telekom-Format mit Leerzeichen (z. B. 736 308 1275)
    telekom = re.search(r"Rechnungsnummer\s*\n\s*(\d{3}\s+\d{3}\s+\d{4})\b", text or "", re.I)
    if telekom:
        return telekom.group(1).strip()

    for muster in (
        r"(?:rechnungsnummer|rechnungs-?nr\.?|rechnungnr\.?|re-nummer|rechnung\s+nr\.?|invoice\s*(?:number|no\.?|#)|vat\s*invoice\s*#|belegnummer|beleg-?nr\.?)\s*[:\s]*([A-Za-z0-9][A-Za-z0-9./-]{1,40})",
        r"\b(?:RECHNUNG\s*-\s*|Rechnung:\s*|INVOICE\s+)([A-Z0-9][A-Z0-9./-]{3,35})",
    ):
        for treffer in re.finditer(muster, text or "", re.I):
            kandidat = treffer.group(1).strip()
            if _ist_rechnungsnummer(kandidat):
                return kandidat
            # Mehrspaltiger Kopf: suche in den nächsten Zeilen nach der ersten gültigen Nummer
            folge = (text or "")[treffer.end():treffer.end() + 160]
            for zeile in folge.splitlines():
                wort = zeile.strip()
                if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./-]{4,35}", wort) and _ist_rechnungsnummer(wort):
                    return wort

    if dateiname:
        for muster in (
            r"RGNR_([A-Za-z0-9_-]+)",
            r"Rechnung[_-](\d{2}\.\d{4}|[A-Za-z0-9]{5,25})",
            r"invoice[_-]([A-Za-z0-9-]+)",
        ):
            treffer = re.search(muster, dateiname, re.I)
            if treffer and _ist_rechnungsnummer(treffer.group(1)):
                return treffer.group(1)
    return ""


def erkenne(text: str, dateiname: str = "", eigene_namen: tuple[str, ...] = ()) -> dict:
    betrag, betrag_herkunft = _erkenne_betrag(text or "")
    datum, datum_herkunft = _erkenne_datum(text or "", dateiname)
    partner, partner_herkunft = _erkenne_partner(text or "", dateiname, eigene_namen)
    nummer = _erkenne_nummer(text or "", dateiname)
    return {
        "betrag": betrag,
        "datum": datum,
        "partner": partner,
        "rechnungsnummer": nummer,
        "betrag_herkunft": betrag_herkunft,
        "datum_herkunft": datum_herkunft,
        "partner_herkunft": partner_herkunft,
    }


def _text_csv(inhalt: bytes) -> str:
    for kodierung in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return inhalt.decode(kodierung)
        except UnicodeDecodeError:
            continue
    return inhalt.decode("latin-1", errors="replace")


def _lokal(knoten: ElementTree.Element) -> str:
    return knoten.tag.rsplit("}", 1)[-1]


def _kind(knoten: ElementTree.Element, name: str) -> ElementTree.Element | None:
    for kind in list(knoten):
        if _lokal(kind) == name:
            return kind
    return None
