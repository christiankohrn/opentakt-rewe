"""Liest die eingebettete Factur-X-/ZUGFeRD- oder XRechnung-XML eines Belegs."""

import xml.etree.ElementTree as ET
from io import BytesIO

import fitz


def xml_aus_pdf(inhalt: bytes) -> bytes | None:
    try:
        dokument = fitz.open(stream=inhalt, filetype="pdf")
    except Exception:
        return None
    try:
        namen = list(dokument.embfile_names())
        funde: list[tuple[int, str, bytes]] = []
        for index, name in enumerate(namen):
            daten = dokument.embfile_get(index)
            if daten:
                funde.append((index, name.casefold(), daten))
    finally:
        dokument.close()
    if not funde:
        return None
    def rang(eintrag: tuple[int, str, bytes]) -> tuple[int, int]:
        name = eintrag[1]
        if "factur" in name or "zugferd" in name or "xrechnung" in name:
            return (0, eintrag[0])
        if name.endswith(".xml"):
            return (1, eintrag[0])
        return (2, eintrag[0])
    funde.sort(key=rang)
    for _, name, daten in funde:
        text = daten.lstrip()
        if text.startswith(b"<?xml") or text.startswith(b"<"):
            if b"CrossIndustryInvoice" in daten or b"Invoice" in daten or "factur" in name or "zugferd" in name:
                return daten
    return None


def _lokal(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _direkt(element: ET.Element, name: str) -> ET.Element | None:
    for kind in element:
        if _lokal(kind) == name:
            return kind
    return None


def _such(element: ET.Element, name: str) -> ET.Element | None:
    for kind in element.iter():
        if _lokal(kind) == name:
            return kind
    return None


def _wert(element: ET.Element | None, name: str) -> str:
    if element is None:
        return ""
    ziel = _such(element, name)
    if ziel is None or ziel.text is None:
        return ""
    return ziel.text.strip()


def _name(partei: ET.Element | None) -> str:
    if partei is None:
        return ""
    for kandidat in ("Name", "RegistrationName"):
        text = _wert(partei, kandidat)
        if text:
            return text
    return ""


def _oder(erstes: ET.Element | None, zweites: ET.Element | None) -> ET.Element | None:
    return erstes if erstes is not None else zweites


def _zeile(element: ET.Element) -> dict:
    produkt = _oder(_such(element, "SpecifiedTradeProduct"), _such(element, "Item"))
    menge = _oder(_such(element, "BilledQuantity"), _such(element, "InvoicedQuantity"))
    preis = _oder(_such(element, "ChargeAmount"), _such(element, "PriceAmount"))
    gesamt = _oder(_such(element, "LineTotalAmount"), _such(element, "LineExtensionAmount"))
    return {
        "bezeichnung": _name(produkt) or _wert(element, "Name"),
        "menge": (menge.text or "").strip() if menge is not None and menge.text else "",
        "einheit": menge.attrib.get("unitCode", "") if menge is not None else "",
        "preis": (preis.text or "").strip() if preis is not None and preis.text else "",
        "gesamt": (gesamt.text or "").strip() if gesamt is not None and gesamt.text else "",
    }


def parse_erechnung(xml: bytes) -> dict | None:
    try:
        wurzel = ET.fromstring(xml)
    except ET.ParseError:
        return None
    if _lokal(wurzel) not in {"CrossIndustryInvoice", "Invoice"} and _such(wurzel, "ExchangedDocument") is None:
        return None
    dokument = _oder(_such(wurzel, "ExchangedDocument"), wurzel)
    verkauf = _oder(_such(wurzel, "SellerTradeParty"), _such(wurzel, "AccountingSupplierParty"))
    kauf = _oder(_such(wurzel, "BuyerTradeParty"), _such(wurzel, "AccountingCustomerParty"))
    summen = _oder(_such(wurzel, "SpecifiedTradeSettlementHeaderMonetarySummation"), _such(wurzel, "LegalMonetaryTotal"))
    zeilen = [
        _zeile(element)
        for element in wurzel.iter()
        if _lokal(element) in {"IncludedSupplyChainTradeLineItem", "InvoiceLine"}
    ]
    return {
        "nummer": _wert(dokument, "ID"),
        "datum": _wert(dokument, "DateTimeString") or _wert(dokument, "IssueDate"),
        "verkaeufer": _name(verkauf),
        "kaeufer": _name(kauf),
        "netto": _wert(summen, "TaxBasisTotalAmount") or _wert(summen, "TaxExclusiveAmount"),
        "steuer": _wert(summen, "TaxTotalAmount"),
        "brutto": _wert(summen, "GrandTotalAmount") or _wert(summen, "PayableAmount"),
        "positionen": [zeile for zeile in zeilen if zeile["bezeichnung"] or zeile["gesamt"]],
    }


def erechnung_aus_pdf(inhalt: bytes) -> dict | None:
    xml = xml_aus_pdf(inhalt)
    if not xml:
        return None
    return parse_erechnung(xml)
