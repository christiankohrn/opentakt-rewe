import pymupdf

from app.erechnung import erechnung_aus_pdf, parse_erechnung

CII = b"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100" xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocument>
    <ram:ID>26.3431</ram:ID>
    <ram:IssueDateTime><udt:DateTimeString>20261108</udt:DateTimeString></ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:SpecifiedTradeProduct><ram:Name>Hosting</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement>
        <ram:NetPriceProductTradePrice><ram:ChargeAmount>10.00</ram:ChargeAmount></ram:NetPriceProductTradePrice>
      </ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="HUR">2</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement>
        <ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>20.00</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation>
      </ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty><ram:Name>Musterfirma</ram:Name></ram:SellerTradeParty>
      <ram:BuyerTradeParty><ram:Name>Kunde</ram:Name></ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:TaxBasisTotalAmount>20.00</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount>3.80</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>23.80</ram:GrandTotalAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""


def test_kopf_vor_positionen():
    daten = parse_erechnung(CII)
    assert daten["nummer"] == "26.3431"
    assert daten["verkaeufer"] == "Musterfirma"
    assert daten["kaeufer"] == "Kunde"
    assert daten["brutto"] == "23.80"
    assert daten["positionen"][0]["bezeichnung"] == "Hosting"
    assert daten["positionen"][0]["menge"] == "2"
    assert daten["positionen"][0]["gesamt"] == "20.00"


def test_xml_aus_pdf():
    dokument = pymupdf.open()
    dokument.new_page()
    dokument.embfile_add("factur-x.xml", CII)
    pdf = dokument.tobytes()
    dokument.close()
    daten = erechnung_aus_pdf(pdf)
    assert daten["nummer"] == "26.3431"
    assert daten["positionen"][0]["bezeichnung"] == "Hosting"


def test_pdf_ohne_xml():
    dokument = pymupdf.open()
    dokument.new_page()
    pdf = dokument.tobytes()
    dokument.close()
    assert erechnung_aus_pdf(pdf) is None
