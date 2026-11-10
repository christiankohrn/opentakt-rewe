"""ZUGFeRD-/XRechnung-2.3-XML, angelehnt an zugferd/Zugferd.cs und frmPrint.save_document."""

import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal

from app.domain import pdf_betraege, sortierte_positionen
from app.models import Rechnung
from app.seller import STANDARD_STAMMDATEN, Stammdaten, iban_kompakt

RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"
QDT = "urn:un:unece:uncefact:data:standard:QualifiedDataType:100"
GUIDELINE = "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_2.3"

ET.register_namespace("rsm", RSM)
ET.register_namespace("ram", RAM)
ET.register_namespace("udt", UDT)
ET.register_namespace("qdt", QDT)


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _add(parent: ET.Element, ns: str, tag: str, text: str | None = None) -> ET.Element:
    element = ET.SubElement(parent, _q(ns, tag))
    if text is not None:
        element.text = text
    return element


def _money(betrag: Decimal) -> str:
    quantized = Decimal(betrag).quantize(Decimal("0.000001"))
    text = f"{quantized:.6f}".rstrip("0").rstrip(".")
    if "." not in text:
        return text + ".00"
    frac = text.split(".", 1)[1]
    if len(frac) < 2:
        return f"{Decimal(betrag):.2f}"
    return text


def _datum(parent: ET.Element, tag: str, wert: date, qualified: bool = False) -> None:
    container = _add(parent, RAM, tag)
    element = _add(container, QDT if qualified else UDT, "DateTimeString", f"{wert:%Y%m%d}")
    element.set("format", "102")


def xrechnung_xml(
    rechnung: Rechnung,
    original: Rechnung | None = None,
    stammdaten: Stammdaten | None = None,
) -> bytes:
    stamm = stammdaten or STANDARD_STAMMDATEN
    positionen = sortierte_positionen(rechnung)
    netto, mwst, brutto = pdf_betraege(rechnung.netto, rechnung.datum, rechnung.keine_mehrwertsteuer)
    if rechnung.keine_mehrwertsteuer:
        satz = Decimal("0")
        kategorie = "AE" if (rechnung.umsatzsteuer_id or "").strip() else "Z"
    else:
        from app.domain import mwst_satz

        satz = mwst_satz(rechnung.datum)
        kategorie = "S"
    bank = stamm.bank
    storno = original is not None
    root = ET.Element(_q(RSM, "CrossIndustryInvoice"))
    context = _add(root, RSM, "ExchangedDocumentContext")
    process = _add(context, RAM, "BusinessProcessSpecifiedDocumentContextParameter")
    _add(process, RAM, "ID", "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0")
    guideline = _add(context, RAM, "GuidelineSpecifiedDocumentContextParameter")
    _add(guideline, RAM, "ID", GUIDELINE)

    document = _add(root, RSM, "ExchangedDocument")
    _add(document, RAM, "ID", rechnung.rechnungs_nr or "")
    _add(document, RAM, "TypeCode", "381" if storno else "380")
    _datum(document, "IssueDateTime", rechnung.datum)
    hinweis = None
    if rechnung.keine_mehrwertsteuer and "FR" in (rechnung.umsatzsteuer_id or ""):
        hinweis = "Autoliquidation"
    if hinweis:
        note = _add(document, RAM, "IncludedNote")
        _add(note, RAM, "Content", hinweis)

    trade = _add(root, RSM, "SupplyChainTradeTransaction")
    for index, position in enumerate(positionen, start=1):
        line_total = Decimal(position.menge) * Decimal(position.preis)
        line = _add(trade, RAM, "IncludedSupplyChainTradeLineItem")
        doc_line = _add(line, RAM, "AssociatedDocumentLineDocument")
        _add(doc_line, RAM, "LineID", str(index))
        product = _add(line, RAM, "SpecifiedTradeProduct")
        _add(product, RAM, "Name", position.bezeichnung or "Leistung")
        if (position.freitext or "").strip():
            _add(product, RAM, "Description", position.freitext)
        agreement = _add(line, RAM, "SpecifiedLineTradeAgreement")
        price = _add(agreement, RAM, "NetPriceProductTradePrice")
        _add(price, RAM, "ChargeAmount", _money(Decimal(position.preis)))
        delivery = _add(line, RAM, "SpecifiedLineTradeDelivery")
        quantity = _add(delivery, RAM, "BilledQuantity", _money(Decimal(position.menge)))
        quantity.set("unitCode", "H87")
        settlement = _add(line, RAM, "SpecifiedLineTradeSettlement")
        tax = _add(settlement, RAM, "ApplicableTradeTax")
        _add(tax, RAM, "TypeCode", "VAT")
        _add(tax, RAM, "CategoryCode", kategorie)
        _add(tax, RAM, "RateApplicablePercent", f"{(satz * 100):.2f}")
        monetary = _add(settlement, RAM, "SpecifiedTradeSettlementLineMonetarySummation")
        _add(monetary, RAM, "LineTotalAmount", _money(line_total))

    header_agreement = _add(trade, RAM, "ApplicableHeaderTradeAgreement")
    _add(header_agreement, RAM, "BuyerReference", stamm.auftrag_referenz or "Ihr Auftrag")
    seller = _add(header_agreement, RAM, "SellerTradeParty")
    _add(seller, RAM, "Name", stamm.name)
    contact = _add(seller, RAM, "DefinedTradeContact")
    _add(contact, RAM, "PersonName", stamm.name)
    phone = _add(contact, RAM, "TelephoneUniversalCommunication")
    _add(phone, RAM, "CompleteNumber", stamm.telefon)
    mail = _add(contact, RAM, "EmailURIUniversalCommunication")
    _add(mail, RAM, "URIID", stamm.email)
    seller_address = _add(seller, RAM, "PostalTradeAddress")
    _add(seller_address, RAM, "PostcodeCode", stamm.plz)
    _add(seller_address, RAM, "LineOne", stamm.strasse_xml or stamm.strasse_brief)
    _add(seller_address, RAM, "CityName", stamm.ort)
    _add(seller_address, RAM, "CountryID", stamm.land or "DE")
    seller_electronic = _add(seller, RAM, "URIUniversalCommunication")
    seller_uri = _add(seller_electronic, RAM, "URIID", stamm.email)
    seller_uri.set("schemeID", "EM")
    if stamm.steuernummer:
        tax_no = _add(seller, RAM, "SpecifiedTaxRegistration")
        tax_no_id = _add(tax_no, RAM, "ID", stamm.steuernummer)
        tax_no_id.set("schemeID", "FC")
    if stamm.ust_id:
        vat = _add(seller, RAM, "SpecifiedTaxRegistration")
        vat_id = _add(vat, RAM, "ID", stamm.ust_id)
        vat_id.set("schemeID", "VA")

    buyer = _add(header_agreement, RAM, "BuyerTradeParty")
    _add(buyer, RAM, "Name", rechnung.name1 or "Kunde")
    buyer_address = _add(buyer, RAM, "PostalTradeAddress")
    _add(buyer_address, RAM, "PostcodeCode", rechnung.plz or "")
    _add(buyer_address, RAM, "LineOne", rechnung.strasse or "")
    _add(buyer_address, RAM, "CityName", rechnung.ort or "")
    _add(buyer_address, RAM, "CountryID", "DE")
    buyer_mail = None
    if rechnung.kunde is not None and (rechnung.kunde.email or "").strip():
        buyer_mail = rechnung.kunde.email.strip()
    ust = (rechnung.umsatzsteuer_id or "").strip()
    if buyer_mail or ust:
        electronic = _add(buyer, RAM, "URIUniversalCommunication")
        uri = _add(electronic, RAM, "URIID", buyer_mail or ust)
        uri.set("schemeID", "EM" if buyer_mail else "9930")
    if ust:
        buyer_tax = _add(buyer, RAM, "SpecifiedTaxRegistration")
        buyer_vat = _add(buyer_tax, RAM, "ID", ust)
        buyer_vat.set("schemeID", "VA")
    order = _add(header_agreement, RAM, "SellerOrderReferencedDocument")
    _add(order, RAM, "IssuerAssignedID", stamm.auftrag_referenz or "Ihr Auftrag")

    delivery = _add(trade, RAM, "ApplicableHeaderTradeDelivery")
    event = _add(delivery, RAM, "ActualDeliverySupplyChainEvent")
    _datum(event, "OccurrenceDateTime", rechnung.datum)

    settlement = _add(trade, RAM, "ApplicableHeaderTradeSettlement")
    _add(settlement, RAM, "InvoiceCurrencyCode", "EUR")
    if original is not None and original.rechnungs_nr:
        reference = _add(settlement, RAM, "InvoiceReferencedDocument")
        _add(reference, RAM, "IssuerAssignedID", original.rechnungs_nr)
        _datum(reference, "FormattedIssueDateTime", original.datum, qualified=True)
    means = _add(settlement, RAM, "SpecifiedTradeSettlementPaymentMeans")
    _add(means, RAM, "TypeCode", "58")
    _add(means, RAM, "Information", "SEPA Überweisung")
    account = _add(means, RAM, "PayeePartyCreditorFinancialAccount")
    _add(account, RAM, "IBANID", iban_kompakt(bank.iban))
    _add(account, RAM, "AccountName", stamm.name)
    institution = _add(means, RAM, "PayeeSpecifiedCreditorFinancialInstitution")
    _add(institution, RAM, "BICID", bank.bic)
    header_tax = _add(settlement, RAM, "ApplicableTradeTax")
    _add(header_tax, RAM, "CalculatedAmount", _money(mwst))
    _add(header_tax, RAM, "TypeCode", "VAT")
    if kategorie == "AE":
        _add(
            header_tax,
            RAM,
            "ExemptionReason",
            "steuerschuldnerschaft des leistungsempfängers (reverse charge)",
        )
    _add(header_tax, RAM, "BasisAmount", _money(netto))
    _add(header_tax, RAM, "CategoryCode", kategorie)
    _add(header_tax, RAM, "RateApplicablePercent", f"{(satz * 100):.2f}")
    terms = _add(settlement, RAM, "SpecifiedTradePaymentTerms")
    _add(terms, RAM, "Description", stamm.zahlungstext)
    _datum(terms, "DueDateDateTime", rechnung.datum + timedelta(days=max(0, int(stamm.zahlungsziel_tage or 10))))
    summation = _add(settlement, RAM, "SpecifiedTradeSettlementHeaderMonetarySummation")
    _add(summation, RAM, "LineTotalAmount", _money(netto))
    _add(summation, RAM, "TaxBasisTotalAmount", _money(netto))
    tax_total = _add(summation, RAM, "TaxTotalAmount", _money(mwst))
    tax_total.set("currencyID", "EUR")
    _add(summation, RAM, "GrandTotalAmount", _money(brutto))
    _add(summation, RAM, "DuePayableAmount", _money(brutto))

    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml
