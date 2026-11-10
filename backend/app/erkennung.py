"""Abrechnung und Geschäftspartner erkennen.

Die eigenen Kennungen (USt-Id, IBAN, Steuernummer aus den Stammdaten)
werden nie einem Partner zugeordnet. Startwerte unten sind bewusst
allgemein; jede Installation pflegt Konten, Kriterien und Partner
in den Einstellungen.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auszuege import _BETRAG_FLEX, erkenne, euro, parse_datum_flex
from app.erechnung import erechnung_aus_pdf
from app.models import AbrechnungsKriterium, Beleg, Bewegung, Geschaeftspartner, Kategorie
from app.seller import stammdaten_lesen

_DATUM = r"(?:Rechnungsdatum|Invoice Date|Datum|Date):?\s*(\d{1,2}[./\s-][A-Za-zäöüÄÖÜ0-9.]{2,10}[./,\s-]*20\d{2}|20\d{2}-\d{2}-\d{2})"
_NUMMER = r"(?:Rechnungsnummer|Rechnungs-?Nr\.?|Invoice\s*(?:Number|No\.?)):?\s*([A-Za-z0-9][A-Za-z0-9./-]{1,40})"
_BETRAG = (
    r"(?:Rechnungsbetrag|Zu zahlender(?:\s+Gesamtbetrag|\s+Betrag)|Gesamtsumme Brutto|Gesamt brutto|"
    r"Rechnungsendbetrag|Zahlbetrag|Rechnungssumme|INVOICE Total|PAYMENT Amount|Document Total|"
    r"Total EUR inkl\. MwSt\.|Total including VAT|Endsumme)\D{0,40}"
    r"(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})"
)

# Allgemeine Erkennungsmerkmale für Kontoauszüge. Eigene IBAN und
# Kartennummer trägt jede Installation in den Einstellungen ein.
ABRECHNUNGEN = (
    ("n26", "dateiname", "statement"),
    ("n26", "absender", "NTSBDEB1XXX"),
    ("amex", "dateiname", "-Abrechnung"),
    ("amex", "absender", "american express"),
    ("miles", "dateiname", "Umsatzabrechnung"),
    ("miles", "absender", "miles & more"),
    ("volksbank", "dateiname", "Kontoauszug_vom_"),
    ("volksbank", "absender", "volksbank"),
)

# Keine Lieferanten als Startwerte. Partner entstehen beim Korrigieren
# von Belegen automatisch und lassen sich in den Einstellungen pflegen.
PARTNER: tuple = ()


_UST = re.compile(
    r"(?:USt\.?-?Id(?:-?Nr)?\.?|Umsatzsteuer-?(?:ID|Identifikationsnummer)|MwSt-?Nummer|"
    r"VAT(?:\s*(?:Reg\.?\s*No\.?|ID(?:-?No\.?)?|number|#|-Id[^:\n]{0,30}))?)[:\s.-]*([A-Z]{2}\s?[A-Z0-9][A-Z0-9 ]{6,14})",
    re.I,
)
_STEUER = re.compile(r"(?:Steuernummer|Steuer-?Nr\.?|St\.?Nr\.?|Tax\s*No\.?)[:\s]*([0-9][0-9 /]{6,20})", re.I)
_IBAN = re.compile(r"IBAN(?:\s*\([A-Z]{3}\))?[:\s]*([A-Z]{2}\s?\d[\d ]{10,34})", re.I)
# Eigene Kennungen ohne Datenbank-Session. Mit Session kommen sie aus den
# Stammdaten und Konten (siehe _eigene_kennungen); hier steht nichts
# Installationsspezifisches.
_KEIN_PARTNER: set[str] = set()
_KEINE_IBAN: set[str] = set()
_KEINE_STEUER: set[str] = set()
_AUSZUG_HINWEIS = re.compile(
    r"(?:kontoauszug|ko\s*nto\s*aus\s*z\s*ug|umsatzabrechnung|monatsabrechnung|"
    r"wertstellung|verbuchungsdatum|alter\s+kontostand|neuer\s+kontostand|abrechnungszeitraum)",
    re.I,
)
_RECHNUNG_HINWEIS = re.compile(
    r"\b(?:rechnungsnummer|rechnungs-?nr\.?|rechnungnr\.?|invoice\s*(?:number|no\.?)|elektronische\s+rechnung)\b",
    re.I,
)


def iban_norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").upper()


def abrechnungen_sicherstellen(session: Session) -> None:
    if session.scalar(select(AbrechnungsKriterium.kriterium_id).limit(1)) is not None:
        return
    for schluessel, art, muster in ABRECHNUNGEN:
        session.add(AbrechnungsKriterium(schluessel=schluessel, art=art, muster=muster))
    session.flush()


def partner_sicherstellen(session: Session) -> None:
    if session.scalar(select(Geschaeftspartner.partner_id).limit(1)) is not None:
        return
    for name, ust, steuer, iban, datum, nummer, betrag in PARTNER:
        session.add(Geschaeftspartner(
            name=name, ust_id=ust, steuernummer=steuer, iban=iban,
            datum_muster=datum, nummer_muster=nummer, betrag_muster=betrag,
        ))
    session.flush()


def _trifft(art: str, muster: str, dateiname: str, text: str) -> bool:
    if art == "dateiname":
        return muster.casefold() in (dateiname or "").casefold()
    if art == "iban":
        return iban_norm(muster) in iban_norm(text)
    if art == "kartentext":
        norm_muster = re.sub(r"[\s-]", "", muster).casefold()
        norm_text = re.sub(r"[\s-]", "", text or "").casefold()
        return norm_muster in norm_text
    return muster.casefold() in (text or "").casefold()


def klassifiziere_text(session: Session, dateiname: str, text: str) -> tuple[str, str]:
    abrechnungen_sicherstellen(session)
    punkte: dict[str, int] = {}
    arten_je_konto: dict[str, set[str]] = {}
    for kriterium in session.scalars(select(AbrechnungsKriterium)):
        if _trifft(kriterium.art, kriterium.muster, dateiname, text):
            gewicht = 2 if kriterium.art == "dateiname" else 1
            punkte[kriterium.schluessel] = punkte.get(kriterium.schluessel, 0) + gewicht
            arten_je_konto.setdefault(kriterium.schluessel, set()).add(kriterium.art)
    if not punkte:
        return "beleg", ""
    ist_auszug_text = bool(_AUSZUG_HINWEIS.search(text or ""))
    for konto, getroffene_arten in arten_je_konto.items():
        if ist_auszug_text and ("kartentext" in getroffene_arten or "iban" in getroffene_arten):
            punkte[konto] += 1
    schluessel = max(punkte, key=lambda name: (punkte[name], len(name)))
    if punkte[schluessel] < 2:
        return "beleg", ""
    getroffen = arten_je_konto.get(schluessel, set())
    # Normale Rechnungen mit eigener Bankverbindung (IBAN + BIC) sind keine Kontoauszüge
    if (
        "dateiname" not in getroffen
        and "kartentext" not in getroffen
        and not ist_auszug_text
        and _RECHNUNG_HINWEIS.search((dateiname or "") + "\n" + (text or ""))
    ):
        return "beleg", ""
    return "abrechnung", schluessel


def _eigene_kennungen(session: Session | None = None) -> tuple[set[str], set[str], set[str]]:
    ust = set(_KEIN_PARTNER)
    ibans = set(_KEINE_IBAN)
    steuern = set(_KEINE_STEUER)
    if session is not None:
        stamm = stammdaten_lesen(session)
        if stamm.ust_id:
            ust.add(iban_norm(stamm.ust_id))
        if stamm.bank_iban:
            ibans.add(iban_norm(stamm.bank_iban))
        if stamm.steuernummer:
            roh = re.sub(r"\s+", " ", stamm.steuernummer).strip()
            steuern.update({roh, roh.replace("/", "-"), roh.replace("/", " "), roh.replace("-", "/")})
        for kat in session.scalars(select(Kategorie)):
            if kat.iban:
                ibans.add(iban_norm(kat.iban))
        for krit in session.scalars(select(AbrechnungsKriterium).where(AbrechnungsKriterium.art == "iban")):
            if krit.muster:
                ibans.add(iban_norm(krit.muster))
    return ust, ibans, steuern


def kennungen(text: str, session: Session | None = None) -> dict[str, str]:
    eigene_ust, eigene_ibans, eigene_steuern = _eigene_kennungen(session)
    ust = ""
    for treffer in _UST.finditer(text or ""):
        roh = treffer.group(1).strip().split()[0] if "\n" in treffer.group(1) else treffer.group(1)
        wert = iban_norm(roh)
        ziffern = sum(ch.isdigit() for ch in wert)
        if ziffern >= 6 and wert not in eigene_ust:
            ust = wert
            break
    steuer = ""
    for treffer in _STEUER.finditer(text or ""):
        kandidat = re.sub(r"\s+", " ", treffer.group(1)).strip()
        if kandidat not in eigene_steuern:
            steuer = kandidat
            break
    iban = ""
    for treffer in _IBAN.finditer(text or ""):
        nach = (text or "")[treffer.end():treffer.end() + 4]
        if nach.lstrip().upper().startswith("X"):
            continue
        kandidat = iban_norm(treffer.group(1))
        if kandidat in eigene_ibans:
            continue
        if kandidat.startswith("DE") and len(kandidat) != 22:
            continue
        if 15 <= len(kandidat) <= 34:
            iban = kandidat
            break
    return {"ust": ust, "steuer": steuer, "iban": iban}


def _feld(muster: str, text: str) -> str:
    if not muster or not text:
        return ""
    try:
        treffer = re.search(muster, text, re.I | re.S)
    except re.error:
        return ""
    if not treffer:
        return ""
    return treffer.group(1).strip()


def _datum(text: str) -> date | None:
    return parse_datum_flex(text)


def _kern_name(name: str) -> str:
    kern = re.sub(
        r"\b(?:GmbH|AG|KG|UG|Co\.|Ltd\.?|Limited|Inc\.?|SARL|S\.a\.?\s*r\.?l\.?|B\.V\.|e\.K\.|GbR|SE|eG|&\s*Co\.?)\b",
        "",
        name or "",
        flags=re.I,
    )
    kern = re.sub(r"[,•·|-].*$", "", kern).strip()
    return " ".join(kern.split())


def partner_finden(session: Session, text: str, dateiname: str = "") -> Geschaeftspartner | None:
    partner_sicherstellen(session)
    werte = kennungen(text, session)
    alle = list(session.scalars(select(Geschaeftspartner)))
    for partner in alle:
        if werte["ust"] and iban_norm(partner.ust_id) == werte["ust"]:
            return partner
        if werte["iban"] and iban_norm(partner.iban) == werte["iban"]:
            return partner
        if werte["steuer"] and partner.steuernummer and partner.steuernummer == werte["steuer"]:
            return partner
    # Wenn eine fremde USt-Id oder IBAN auf dem Beleg steht, die noch keinem Partner gehört,
    # nicht über Teilnamen auf einen falschen Partner fallen.
    if werte["ust"] or werte["iban"]:
        return None
    suchtext = f"{text or ''}\n{dateiname or ''}".casefold()
    kandidaten: list[tuple[int, Geschaeftspartner]] = []
    for partner in alle:
        voll = (partner.name or "").strip().casefold()
        if len(voll) >= 4 and voll in suchtext:
            kandidaten.append((len(voll), partner))
            continue
        kern = _kern_name(partner.name).casefold()
        if len(kern) >= 5 and re.search(rf"\b{re.escape(kern)}\b", suchtext):
            kandidaten.append((len(kern), partner))
    if kandidaten:
        kandidaten.sort(key=lambda eintrag: -eintrag[0])
        return kandidaten[0][1]
    return None


def _konto_hinweis(session: Session, text: str, partner: Geschaeftspartner | None, name: str) -> str:
    klein = (text or "").casefold()
    norm = iban_norm(text or "")
    for kriterium in session.scalars(select(AbrechnungsKriterium)):
        if kriterium.art == "kartentext" and _trifft(kriterium.art, kriterium.muster, "", text):
            return kriterium.schluessel
        if kriterium.art == "iban" and iban_norm(kriterium.muster) in norm:
            return kriterium.schluessel
    if "american express" in klein or "amex" in klein:
        return "amex"
    if "miles & more" in klein or "miles and more" in klein:
        return "miles"
    if "n26 bank" in klein or "ntsbdeb1" in klein:
        return "n26"
    if partner is not None:
        vorhanden = session.scalar(
            select(Beleg.quelle)
            .where(
                Beleg.geschaeftspartner_id == partner.partner_id,
                Beleg.quelle.not_in(("ausgang", "eingang", "scan", "datei")),
            )
            .order_by(Beleg.beleg_id.desc())
            .limit(1)
        )
        if vorhanden:
            return vorhanden
    if name:
        vorhanden_beleg = session.scalar(
            select(Beleg.quelle)
            .where(
                Beleg.partner == name,
                Beleg.quelle.not_in(("ausgang", "eingang", "scan", "datei")),
            )
            .order_by(Beleg.beleg_id.desc())
            .limit(1)
        )
        if vorhanden_beleg:
            return vorhanden_beleg
    return ""


# Rechtsformen zählen nicht als Eigennamen, sonst würde z. B. "GmbH"
# jeden GmbH-Partner aus der Erkennung ausschließen.
_RECHTSFORM_STOP = frozenset({
    "gmbh", "ag", "ug", "kg", "ohg", "gbr", "se", "eg", "ek",
    "ltd", "limited", "inc", "sarl", "bv", "co",
})


def eigene_namen(session: Session) -> tuple[str, ...]:
    """Eigener Name aus den Stammdaten, damit er nie als Partner erkannt wird."""
    stamm = stammdaten_lesen(session)
    teile = [stamm.name, *(stamm.name or "").split()]

    def _behalten(wort: str) -> bool:
        sauber = wort.strip()
        return len(sauber) >= 4 and sauber.strip(".").casefold() not in _RECHTSFORM_STOP

    return tuple(dict.fromkeys(w.strip() for w in teile if _behalten(w)))


def beleg_erkennen(session: Session, dateiname: str, text: str, inhalt: bytes | None = None) -> dict:
    basis = erkenne(text, dateiname, eigene_namen(session))
    art, quelle = klassifiziere_text(session, dateiname, text)
    partner = partner_finden(session, text, dateiname) if art != "abrechnung" else None
    nummer = basis["rechnungsnummer"]
    datum = basis["datum"]
    betrag = basis["betrag"]
    name = basis["partner"]
    betrag_herkunft = basis["betrag_herkunft"]
    datum_herkunft = basis["datum_herkunft"]
    partner_herkunft = basis["partner_herkunft"]

    # Stufe 0: Eingebettete E-Rechnung (ZUGFeRD / Factur-X / XRechnung)
    ist_ausgang = False
    if art != "abrechnung" and inhalt and (dateiname or "").lower().endswith(".pdf"):
        try:
            er = erechnung_aus_pdf(inhalt)
        except Exception:
            er = None
        if er:
            eigene = {w.casefold() for w in eigene_namen(session)}
            verkaeufer = " ".join((er.get("verkaeufer") or "").split())
            kaeufer = " ".join((er.get("kaeufer") or "").split())
            if verkaeufer and any(en in verkaeufer.casefold() for en in eigene) and kaeufer:
                name = kaeufer
                partner_herkunft = "sicher"
                ist_ausgang = True
            elif verkaeufer:
                name = verkaeufer
                partner_herkunft = "sicher"
            if er.get("nummer"):
                nummer = er["nummer"].strip()
            if er.get("datum") and _datum(er["datum"]):
                datum = _datum(er["datum"])
                datum_herkunft = "sicher"
            if er.get("brutto"):
                try:
                    betrag = euro(er["brutto"])
                    betrag_herkunft = "sicher"
                except (InvalidOperation, ValueError):
                    pass

    if partner is not None:
        name = partner.name
        partner_herkunft = "sicher"
        eigene_nummer = _feld(partner.nummer_muster, text)
        eigene_datum = _feld(partner.datum_muster, text)
        eigener_betrag = _feld(partner.betrag_muster, text)
        if eigene_nummer:
            nummer = eigene_nummer
        if eigene_datum and _datum(eigene_datum):
            datum = _datum(eigene_datum)
            datum_herkunft = "sicher"
        if eigener_betrag:
            try:
                betrag = euro(eigener_betrag)
                betrag_herkunft = "sicher"
            except (InvalidOperation, ValueError):
                pass

    if art != "abrechnung" and not quelle:
        quelle = _konto_hinweis(session, text, partner, name)

    return {
        "art": art,
        "quelle": quelle,
        "partner": name,
        "betrag": f"{betrag:.2f}" if betrag is not None else "",
        "datum": datum.isoformat() if datum else "",
        "rechnungsnummer": nummer,
        "partner_id": partner.partner_id if partner is not None else None,
        "betrag_herkunft": betrag_herkunft,
        "datum_herkunft": datum_herkunft,
        "partner_herkunft": partner_herkunft,
        "ist_ausgang": ist_ausgang,
    }


def _baue_vorlauf_regex(text: str, pos: int) -> str:
    vor = text[max(0, pos - 60):pos]
    zeilen = [z.strip() for z in vor.splitlines() if z.strip()]
    if not zeilen:
        return ""
    letzte = zeilen[-1]
    worte = letzte.split()[-3:]
    if not worte:
        return ""
    anker = r"\s+".join(re.escape(w) for w in worte)
    return rf"{anker}\s*"


def _lerne_nummer_muster(text: str, nummer: str) -> str:
    if not text or not nummer:
        return ""
    treffer = re.search(re.escape(nummer), text)
    if not treffer:
        return ""
    vorlauf = _baue_vorlauf_regex(text, treffer.start())
    if not vorlauf:
        return ""
    gruppe = r"(\d[\d ]{5,20}\d)" if " " in nummer else r"([A-Za-z0-9][A-Za-z0-9./-]{1,40})"
    kandidat = vorlauf + gruppe
    if _feld(kandidat, text) == nummer:
        return kandidat
    return ""


def _lerne_datum_muster(text: str, ziel_datum: date) -> str:
    if not text or not ziel_datum:
        return ""
    kandidaten_formen = [
        (ziel_datum.strftime("%d.%m.%Y"), r"(\d{2}\.\d{2}\.\d{4})"),
        (ziel_datum.strftime("%d.%m.%y"), r"(\d{2}\.\d{2}\.\d{2})"),
        (ziel_datum.strftime("%d/%m/%Y"), r"(\d{2}/\d{2}/\d{4})"),
        (ziel_datum.isoformat(), r"(\d{4}-\d{2}-\d{2})"),
    ]
    for literal, gruppe in kandidaten_formen:
        treffer = re.search(re.escape(literal), text)
        if not treffer:
            continue
        vorlauf = _baue_vorlauf_regex(text, treffer.start())
        if not vorlauf:
            continue
        kandidat = vorlauf + gruppe
        if _datum(_feld(kandidat, text)) == ziel_datum:
            return kandidat
    return ""


def _lerne_betrag_muster(text: str, ziel_betrag: Decimal) -> str:
    if not text or ziel_betrag is None:
        return ""
    wert = abs(Decimal(ziel_betrag)).quantize(Decimal("0.01"))
    de_komma = f"{wert:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    de_einfach = f"{wert:.2f}".replace(".", ",")
    en_punkt = f"{wert:,.2f}"
    en_einfach = f"{wert:.2f}"
    such_strings = []
    for s in (de_komma, de_einfach, en_punkt, en_einfach):
        if s not in such_strings:
            such_strings.append(s)
    for literal in such_strings:
        treffer_liste = list(re.finditer(re.escape(literal), text))
        for treffer in reversed(treffer_liste):
            vorlauf = _baue_vorlauf_regex(text, treffer.start())
            if not vorlauf:
                continue
            kandidat = vorlauf + r"\D{0,20}(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})"
            gefunden = _feld(kandidat, text)
            if gefunden:
                try:
                    if euro(gefunden) == wert:
                        return kandidat
                except (InvalidOperation, ValueError):
                    pass
    return ""


def partner_pflegen(
    session: Session,
    name: str,
    text: str,
    datum: date | None = None,
    betrag: Decimal | None = None,
    nummer: str | None = None,
) -> Geschaeftspartner | None:
    name = (name or "").strip()
    if not name:
        return None
    partner_sicherstellen(session)
    partner = None
    for vorhanden in session.scalars(select(Geschaeftspartner)):
        if vorhanden.name.casefold() == name.casefold():
            partner = vorhanden
            break
    werte = kennungen(text, session)
    if partner is None:
        partner = Geschaeftspartner(
            name=name,
            ust_id=werte["ust"],
            steuernummer=werte["steuer"],
            iban=werte["iban"],
            datum_muster=_DATUM,
            nummer_muster=_NUMMER,
            betrag_muster=_BETRAG,
        )
        session.add(partner)
        session.flush()
    else:
        if werte["ust"] and not partner.ust_id:
            partner.ust_id = werte["ust"]
        if werte["steuer"] and not partner.steuernummer:
            partner.steuernummer = werte["steuer"]
        if werte["iban"] and not partner.iban:
            partner.iban = werte["iban"]

    # Selbstlernende Muster-Synthese aus bestätigten/korrigierten Werten
    saubere_nummer = (nummer or "").strip()
    if saubere_nummer and text and _feld(partner.nummer_muster, text) != saubere_nummer:
        gelernt = _lerne_nummer_muster(text, saubere_nummer)
        if gelernt:
            partner.nummer_muster = gelernt
    if datum is not None and text and _datum(_feld(partner.datum_muster, text)) != datum:
        gelernt = _lerne_datum_muster(text, datum)
        if gelernt:
            partner.datum_muster = gelernt
    if betrag is not None and text:
        aktuell_ok = False
        bisher = _feld(partner.betrag_muster, text)
        if bisher:
            try:
                aktuell_ok = euro(bisher) == abs(Decimal(betrag)).quantize(Decimal("0.01"))
            except (InvalidOperation, ValueError):
                aktuell_ok = False
        if not aktuell_ok:
            gelernt = _lerne_betrag_muster(text, betrag)
            if gelernt:
                partner.betrag_muster = gelernt
    return partner


def abrechnung_pflegen(session: Session, quelle: str, dateiname: str, text: str) -> None:
    if not quelle or quelle in {"ausgang", "eingang", "scan", "datei"}:
        return
    art_erkannt, quelle_erkannt = klassifiziere_text(session, dateiname, text)
    if art_erkannt == "abrechnung" and quelle_erkannt == quelle:
        return
    vorhanden = {
        (k.schluessel, k.art, k.muster.casefold())
        for k in session.scalars(select(AbrechnungsKriterium))
    }
    stamm = re.sub(r"[\d_.-]+", " ", Path(dateiname or "").stem).strip()
    worte = [w for w in stamm.split() if len(w) >= 5]
    if worte:
        muster = worte[0]
        if (quelle, "dateiname", muster.casefold()) not in vorhanden:
            session.add(AbrechnungsKriterium(schluessel=quelle, art="dateiname", muster=muster))
            session.flush()
