from decimal import Decimal

from app.models import Kunde, Position, Rechnung


def geld(wert) -> str | None:
    if wert is None:
        return None
    text = format(Decimal(wert), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("", "-0"):
        return "0"
    return text


def iso(wert) -> str | None:
    return wert.isoformat() if wert else None


def position_dict(position: Position) -> dict:
    return {
        "positionen_id": position.positionen_id,
        "rechnung_id": position.rechnung_id,
        "menge": geld(position.menge),
        "preis": geld(position.preis),
        "naechster_preis": geld(position.naechster_preis),
        "naechste_menge": geld(position.naechste_menge),
        "einmalig": bool(position.einmalig),
        "bezeichnung": position.bezeichnung or "",
        "freitext": position.freitext or "",
        "mengeneinheit": position.mengeneinheit or "",
        "pos_nr": position.pos_nr,
    }


def kunde_dict(kunde: Kunde) -> dict:
    return {
        "kunden_id": kunde.kunden_id,
        "name1": kunde.name1 or "",
        "name2": kunde.name2 or "",
        "name3": kunde.name3 or "",
        "email": kunde.email,
        "tel1": kunde.tel1,
        "tel2": kunde.tel2,
        "tel3": kunde.tel3,
        "fax": kunde.fax,
        "strasse": kunde.strasse or "",
        "plz": kunde.plz or "",
        "ort": kunde.ort or "",
        "stundensatz": geld(kunde.stundensatz),
        "umsatzsteuer_id": kunde.umsatzsteuer_id or "",
        "keine_mehrwertsteuer": bool(kunde.keine_mehrwertsteuer),
    }


def rechnung_dict(rechnung: Rechnung, mit_positionen: bool = False, storno_zu_nr: str | None = None) -> dict:
    daten = {
        "rechnungs_id": rechnung.rechnungs_id,
        "datum": iso(rechnung.datum),
        "kunde_id": rechnung.kunde_id,
        "name1": rechnung.name1 or "",
        "name2": rechnung.name2 or "",
        "name3": rechnung.name3 or "",
        "strasse": rechnung.strasse or "",
        "plz": rechnung.plz or "",
        "ort": rechnung.ort or "",
        "rechnungs_nr": rechnung.rechnungs_nr,
        "leistungszeitraum": rechnung.leistungszeitraum or "",
        "umsatzsteuer_id": rechnung.umsatzsteuer_id or "",
        "keine_mehrwertsteuer": bool(rechnung.keine_mehrwertsteuer),
        "storno_zu_rechnung_id": rechnung.storno_zu_rechnung_id,
        "storno_zu_nr": storno_zu_nr,
        "archiv": bool(rechnung.archiv),
        "wiedervorlage_termin": iso(rechnung.wiedervorlage_termin),
        "wiederholung_monate": rechnung.wiederholung_monate,
        "notizen_intern": rechnung.notizen_intern,
        "brutto": geld(rechnung.brutto),
        "netto": geld(rechnung.netto),
        "bezahlt": geld(rechnung.bezahlt),
        "bezahlt_am": iso(rechnung.bezahlt_am),
        "gedruckt_buchhaltung": bool(rechnung.gedruckt_buchhaltung),
        "datev_gesendet": iso(rechnung.datev_gesendet),
        "email": rechnung.kunde.email if rechnung.kunde is not None else None,
    }
    if mit_positionen:
        daten["positionen"] = [position_dict(position) for position in sorted(
            rechnung.positionen,
            key=lambda position: (position.pos_nr if position.pos_nr is not None else 0, position.positionen_id or 0),
        )]
    return daten
