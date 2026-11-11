"""Belege speichern, Umsätzen zuordnen, DATEV-Paket bauen.

Zuordnung nur, wenn Betrag und ein Name eindeutig zusammenpassen.
Sonst bleibt die Bewegung ohne Beleg. Keine Buchungssätze.
"""

import csv
import hashlib
import io
import json
import re
import shutil
import subprocess
import zipfile
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from uuid import uuid4

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, selectinload

from app.auszuege import erkenne, euro, parse_kontoauszug, pdf_text
from app.config import get_settings
from app.datev_adressen import ADRESSEN, adresse, vorschlag
from app.mailer import senden_datei, senden_dateien
from app.erkennung import abrechnung_pflegen, beleg_erkennen, eigene_namen, partner_pflegen
from app.kategorien import kategorien_lesen, kategorien_sicherstellen, versand_optionen_lesen
from app.models import Beleg, Bewegung, BewegungBeleg, ExportVorgang, Kategorie, Rechnung
from app.seller import stammdaten_lesen

_STOP = {
    "gmbh", "online", "paypal", "www", "com", "the", "und", "von", "fuer", "für",
    "herrn", "frau", "ag", "mbh", "sarl", "ltd", "inc", "billing", "bill", "mktp",
    "de", "germany", "karte", "karten", "lastschriften", "belastungen", "gutschriften",
}
_ALIAS_TOKEN = {
    "amzn": "amazon",
    "postshop": "post",
}
_ARTEN = {"abrechnung", "beleg", "eingang", "ausgang", "scan"}
_QUELLEN = {"ausgang", "eingang", "scan", "datei"}


def _quelle_gueltig(session: Session, quelle: str) -> bool:
    if quelle in _QUELLEN:
        return True
    kategorien_sicherstellen(session)
    return session.scalar(select(Kategorie.schluessel).where(Kategorie.schluessel == quelle)) is not None


def _alle_quellen(session: Session) -> list[str]:
    schluessel = [k.schluessel for k in kategorien_lesen(session)]
    return schluessel + [q for q in ("ausgang", "eingang", "scan", "datei") if q not in schluessel]


def ordner() -> Path:
    pfad = get_settings().beleg_ordner.strip()
    ziel = Path(pfad) if pfad else Path("/var/lib/buchhaltung/belege")
    if not ziel.is_absolute():
        ziel = Path.cwd() / ziel
    ziel.mkdir(parents=True, exist_ok=True)
    return ziel


def beleg_inhalt_laden(session: Session, beleg: Beleg) -> bytes | None:
    if (beleg.datei or "").startswith("rechnung:"):
        from app.domain import berechne
        from app.pdf import rechnung_pdf

        try:
            rechnungs_id = int(beleg.datei.split(":", 1)[1])
        except ValueError:
            return None
        rechnung = session.get(Rechnung, rechnungs_id, options=[selectinload(Rechnung.positionen)])
        if rechnung is None:
            return None
        berechne(rechnung)
        original = (
            session.get(Rechnung, rechnung.storno_zu_rechnung_id, options=[selectinload(Rechnung.positionen)])
            if rechnung.storno_zu_rechnung_id
            else None
        )
        return rechnung_pdf(rechnung, original, briefpapier=True, stammdaten=stammdaten_lesen(session))
    pfad = ordner() / beleg.datei
    if not pfad.is_file():
        return None
    return pfad.read_bytes()


def importiere(session: Session, dateiname: str, inhalt: bytes, art: str, quelle: str) -> dict:
    if art not in _ARTEN:
        raise ValueError(f"Unbekannte Art {art}.")
    if not _quelle_gueltig(session, quelle):
        raise ValueError(f"Unbekannte Quelle {quelle}.")
    digest = hashlib.sha256(inhalt).hexdigest()
    vorhanden = session.scalar(select(Beleg).where(Beleg.sha256 == digest))
    if vorhanden is not None:
        return {"beleg_id": vorhanden.beleg_id, "neu": False, "umsaetze": 0, "hinweis": "Datei war schon importiert."}
    datei = _speichern(digest, dateiname, inhalt)
    from app.ocr import text_ermitteln

    text, ocr_status, ocr_hinweis = text_ermitteln(dateiname, inhalt)
    if not text:
        text = _text(dateiname, inhalt)
    erkannt = beleg_erkennen(session, dateiname, text, inhalt)
    betrag = None
    datum = None
    partner_id = None
    pruefung = ""
    if art == "abrechnung":
        try:
            umsaetze = parse_kontoauszug(quelle, dateiname, inhalt, stammdaten_lesen(session).name)
        except Exception as exc:
            umsaetze = []
            pruefung = f"Keine Umsätze gelesen: {exc}. Die Datei wurde gespeichert."
        if not umsaetze and not pruefung:
            pruefung = "Keine Umsätze erkannt. Die Datei wurde gespeichert."
        if umsaetze:
            abrechnung_pflegen(session, quelle, dateiname, text)
    else:
        umsaetze = []
        betrag = Decimal(erkannt["betrag"]) if erkannt.get("betrag") else None
        datum = date.fromisoformat(erkannt["datum"]) if erkannt.get("datum") else None
        partner_id = erkannt.get("partner_id")
        if art == "eingang":
            pruefung = pruefe_pdf(ordner() / datei)
        if art == "beleg" and quelle != "ausgang":
            if erkannt.get("ist_ausgang") or re.match(r"^\d{2}\.\d{4}$", erkannt.get("rechnungsnummer") or ""):
                art = "ausgang"
    if ocr_hinweis and (ocr_status == "ohne" or not pruefung):
        pruefung = f"{pruefung}\n{ocr_hinweis}".strip() if pruefung else ocr_hinweis
    beleg = Beleg(
        sha256=digest,
        dateiname=_sicher(dateiname),
        art=art,
        quelle=quelle,
        betrag=betrag,
        datum=datum,
        partner="" if art == "abrechnung" else erkannt["partner"],
        rechnungsnummer="" if art == "abrechnung" else erkannt["rechnungsnummer"],
        betrag_herkunft="" if art == "abrechnung" else (erkannt.get("betrag_herkunft") or ""),
        datum_herkunft="" if art == "abrechnung" else (erkannt.get("datum_herkunft") or ""),
        partner_herkunft="" if art == "abrechnung" else (erkannt.get("partner_herkunft") or ""),
        text_auszug=text[:8000],
        pruefung=pruefung,
        ocr_status=ocr_status,
        datei=datei,
        erstellt=datetime.now(),
        geschaeftspartner_id=partner_id,
    )
    session.add(beleg)
    session.flush()
    neu = 0
    for umsatz in umsaetze:
        if _bewegung(session, quelle, umsatz, beleg.beleg_id):
            neu += 1
    session.flush()
    return {"beleg_id": beleg.beleg_id, "neu": True, "umsaetze": neu, "hinweis": pruefung}


def _belegt(session: Session) -> set[int]:
    ids = {bewegung.beleg_id for bewegung in session.scalars(select(Bewegung)) if bewegung.beleg_id}
    ids.update(link.beleg_id for link in session.scalars(select(BewegungBeleg)))
    return ids


def _haengen(session: Session, bewegung: Bewegung, beleg: Beleg, art: str) -> None:
    if bewegung.beleg_id is None:
        bewegung.beleg_id = beleg.beleg_id
    bewegung.zuordnung = art
    vorhanden = session.scalar(select(BewegungBeleg).where(BewegungBeleg.beleg_id == beleg.beleg_id))
    if vorhanden is None:
        session.add(BewegungBeleg(bewegung_id=bewegung.bewegung_id, beleg_id=beleg.beleg_id, zuordnung=art))
    if bewegung.betrag > 0:
        _markiere_rechnung_bezahlt_fuer_beleg(session, beleg, bewegung)


def _markiere_rechnung_bezahlt_fuer_beleg(session: Session, beleg: Beleg, bewegung: Bewegung) -> None:
    from app.domain import setze_zahlung

    nummer = (beleg.rechnungsnummer or "").strip()
    if not nummer:
        return
    rechnung = session.scalar(select(Rechnung).where(Rechnung.rechnungs_nr == nummer))
    if rechnung is None and "." not in nummer and len(nummer) == 6 and nummer.isdigit():
        rechnung = session.scalar(select(Rechnung).where(Rechnung.rechnungs_nr == f"{nummer[:2]}.{nummer[2:]}"))
    if rechnung is not None and (rechnung.bezahlt or Decimal("0")) < (rechnung.brutto or Decimal("0")):
        setze_zahlung(rechnung, rechnung.brutto, bewegung.datum)


def ausgangsrechnungen_abgleichen(session: Session) -> int:
    """Legt für erstellte Ausgangsrechnungen aus der Datenbank Beleg-Einträge an, damit Geldeingänge zugeordnet werden können."""
    rechnungen = list(session.scalars(
        select(Rechnung).where(Rechnung.rechnungs_nr.is_not(None), Rechnung.rechnungs_nr != "")
    ))
    if not rechnungen:
        return 0
    vorhanden_nr: set[str] = set()
    vorhanden_sha: set[str] = set()
    for nr, sha, art_beleg in session.execute(select(Beleg.rechnungsnummer, Beleg.sha256, Beleg.art)):
        if nr and art_beleg != "abrechnung":
            vorhanden_nr.add(nr.strip())
        if sha:
            vorhanden_sha.add(sha)
    angelegt = 0
    for rechnung in rechnungen:
        nr = (rechnung.rechnungs_nr or "").strip()
        if not nr or nr in vorhanden_nr:
            continue
        sha = hashlib.sha256(f"ausgangsrechnung:{rechnung.rechnungs_id}:{nr}".encode("utf-8")).hexdigest()
        if sha in vorhanden_sha:
            continue
        name = " ".join(p.strip() for p in (rechnung.name1, rechnung.name2) if (p or "").strip())
        brutto = Decimal(rechnung.brutto or 0).quantize(Decimal("0.01"))
        beleg = Beleg(
            sha256=sha,
            dateiname=f"Rechnung_{nr}.pdf",
            art="ausgang",
            quelle="ausgang",
            betrag=brutto,
            datum=rechnung.datum,
            partner=name,
            rechnungsnummer=nr,
            betrag_herkunft="sicher",
            datum_herkunft="sicher",
            partner_herkunft="sicher",
            text_auszug=f"Ausgangsrechnung {nr} {name} {rechnung.leistungszeitraum or ''}".strip(),
            pruefung="",
            datei=f"rechnung:{rechnung.rechnungs_id}",
            erstellt=datetime.now(),
        )
        session.add(beleg)
        vorhanden_nr.add(nr)
        vorhanden_sha.add(sha)
        angelegt += 1
    if angelegt:
        session.flush()
    return angelegt


def _markiere_zugeordnete_rechnungen_bezahlt(session: Session) -> int:
    from app.domain import setze_zahlung

    rechnungen_je_nr = {
        (r.rechnungs_nr or "").strip(): r
        for r in session.scalars(select(Rechnung).where(Rechnung.rechnungs_nr.is_not(None), Rechnung.rechnungs_nr != ""))
    }
    if not rechnungen_je_nr:
        return 0
    belege_map = {b.beleg_id: b for b in session.scalars(select(Beleg))}
    bewegungen_map = {m.bewegung_id: m for m in session.scalars(select(Bewegung))}
    markiert = 0
    paare: list[tuple[Bewegung, Beleg]] = []
    for link in session.scalars(select(BewegungBeleg)):
        bew = bewegungen_map.get(link.bewegung_id)
        bel = belege_map.get(link.beleg_id)
        if bew is not None and bel is not None:
            paare.append((bew, bel))
    for bew in bewegungen_map.values():
        if bew.beleg_id and bew.beleg_id in belege_map:
            paare.append((bew, belege_map[bew.beleg_id]))
    for bew, bel in paare:
        if bew.betrag <= 0:
            continue
        nr = (bel.rechnungsnummer or "").strip()
        rechnung = rechnungen_je_nr.get(nr)
        if rechnung is None and "." not in nr and len(nr) == 6 and nr.isdigit():
            rechnung = rechnungen_je_nr.get(f"{nr[:2]}.{nr[2:]}")
        if rechnung is not None and (rechnung.bezahlt or Decimal("0")) < (rechnung.brutto or Decimal("0")):
            setze_zahlung(rechnung, rechnung.brutto, bew.datum)
            markiert += 1
    if markiert:
        session.flush()
    return markiert


def _gelernte_gegenparteien(session: Session) -> dict[str, set[str]]:
    """Lernt aus bereits zugeordneten Bewegungen, welche Gegenpartei zu welchem Partner gehört."""
    gelernt: dict[str, set[str]] = defaultdict(set)
    belege_map = {b.beleg_id: b for b in session.scalars(select(Beleg))}
    bewegungen_map = {m.bewegung_id: m for m in session.scalars(select(Bewegung))}
    for link in session.scalars(select(BewegungBeleg)):
        beleg = belege_map.get(link.beleg_id)
        bewegung = bewegungen_map.get(link.bewegung_id)
        if beleg and bewegung and beleg.partner and bewegung.gegenpartei:
            gelernt[beleg.partner.strip().casefold()].add(bewegung.gegenpartei.strip().casefold())
    for bewegung in bewegungen_map.values():
        if bewegung.beleg_id and bewegung.gegenpartei:
            beleg = belege_map.get(bewegung.beleg_id)
            if beleg and beleg.partner:
                gelernt[beleg.partner.strip().casefold()].add(bewegung.gegenpartei.strip().casefold())
    return gelernt


def zuordnen(session: Session) -> int:
    ausgangsrechnungen_abgleichen(session)
    gelernte = _gelernte_gegenparteien(session)
    bewegungen = list(session.scalars(select(Bewegung).where(Bewegung.beleg_id.is_(None))))
    belegt = _belegt(session)
    belege = [
        beleg for beleg in session.scalars(select(Beleg).where(Beleg.art != "abrechnung"))
        if beleg.beleg_id not in belegt and beleg.betrag is not None
    ]
    paare: list[tuple[Beleg, Bewegung]] = []
    for beleg in belege:
        for bewegung in bewegungen:
            if _passt(beleg, bewegung, gelernte):
                paare.append((beleg, bewegung))
    von_beleg: dict[int, list[Bewegung]] = defaultdict(list)
    von_bewegung: dict[int, list[Beleg]] = defaultdict(list)
    for beleg, bewegung in paare:
        von_beleg[beleg.beleg_id].append(bewegung)
        von_bewegung[bewegung.bewegung_id].append(beleg)
    treffer = 0
    for beleg, bewegung in paare:
        if len(von_beleg[beleg.beleg_id]) == 1 and len(von_bewegung[bewegung.bewegung_id]) == 1:
            _haengen(session, bewegung, beleg, "automatisch")
            treffer += 1
    session.flush()
    sammel = _sammel_zuordnen(session, gelernte)
    geraten = _geraten(session)
    _markiere_zugeordnete_rechnungen_bezahlt(session)
    return treffer + sammel + geraten


def _sammel_zuordnen(session: Session, gelernte: dict[str, set[str]]) -> int:
    """Ordnet eindeutig mehrere Belege einer Sammelbewegung zu, wenn Summe und Name/Rechnungsnummer passen."""
    bewegungen = list(session.scalars(select(Bewegung).where(Bewegung.beleg_id.is_(None))))
    belegt = _belegt(session)
    belege = [
        beleg for beleg in session.scalars(select(Beleg).where(Beleg.art != "abrechnung"))
        if beleg.beleg_id not in belegt and beleg.betrag is not None and abs(beleg.betrag) > 0
    ]
    treffer = 0
    verwendet: set[int] = set()
    for bewegung in bewegungen:
        ziel = abs(bewegung.betrag)
        kandidaten = [
            beleg for beleg in belege
            if beleg.beleg_id not in verwendet
            and abs(beleg.betrag) < ziel
            and _rahmen_passt(beleg, bewegung)
            and _namen_oder_nummer_passt(beleg, bewegung, gelernte)
        ]
        if len(kandidaten) < 2 or len(kandidaten) > 8:
            continue
        passende_gruppen: list[tuple[Beleg, ...]] = []
        for anzahl in range(2, min(5, len(kandidaten) + 1)):
            for gruppe in combinations(kandidaten, anzahl):
                if sum(abs(b.betrag) for b in gruppe) == ziel:
                    passende_gruppen.append(gruppe)
        if len(passende_gruppen) == 1:
            for beleg in passende_gruppen[0]:
                _haengen(session, bewegung, beleg, "automatisch")
                verwendet.add(beleg.beleg_id)
            treffer += 1
    if treffer:
        session.flush()
    return treffer


def _geraten(session: Session) -> int:
    bewegungen = list(session.scalars(select(Bewegung).where(Bewegung.beleg_id.is_(None))))
    belegt = _belegt(session)
    belege = [
        beleg for beleg in session.scalars(select(Beleg).where(Beleg.art != "abrechnung"))
        if beleg.beleg_id not in belegt and beleg.betrag is not None
    ]
    paare = [(beleg, bewegung) for beleg in belege for bewegung in bewegungen if _betrag_passt(beleg, bewegung)]
    von_beleg: dict[int, list[Bewegung]] = defaultdict(list)
    von_bewegung: dict[int, list[Beleg]] = defaultdict(list)
    for beleg, bewegung in paare:
        von_beleg[beleg.beleg_id].append(bewegung)
        von_bewegung[bewegung.bewegung_id].append(beleg)
    treffer = 0
    for beleg, bewegung in paare:
        if len(von_beleg[beleg.beleg_id]) == 1 and len(von_bewegung[bewegung.bewegung_id]) == 1:
            _haengen(session, bewegung, beleg, "geraten")
            treffer += 1
    return treffer


def _rahmen_passt(beleg: Beleg, bewegung: Bewegung) -> bool:
    if beleg.betrag is None:
        return False
    ist_ausgang = beleg.art == "ausgang" or beleg.quelle == "ausgang"
    if ist_ausgang:
        if bewegung.betrag <= 0:
            return False
    elif bewegung.betrag >= 0:
        return False
    if beleg.datum is not None:
        fenster = 60 if ist_ausgang else 14
        if abs((bewegung.datum - beleg.datum).days) > fenster:
            return False
    return True


def _fremdwaehrung_passt(beleg_betrag: Decimal, zweck: str) -> bool:
    if not zweck or not re.search(r"\b(?:US Dollars|USD|GBP|CHF|Referenzwechselkurs)\b", zweck, re.I):
        return False
    wert = abs(beleg_betrag).quantize(Decimal("0.01"))
    en = f"{wert:.2f}"
    de = en.replace(".", ",")
    return bool(re.search(rf"(?<!\d)(?:{re.escape(en)}|{re.escape(de)})(?!\d)", zweck))


def _betrag_passt(beleg: Beleg, bewegung: Bewegung) -> bool:
    if not _rahmen_passt(beleg, bewegung):
        return False
    if abs(bewegung.betrag) == abs(beleg.betrag):
        return True
    return _fremdwaehrung_passt(beleg.betrag, bewegung.zweck or "")


def _nummer_norm(text: str) -> str:
    return re.sub(r"[\s./-]+", "", (text or "")).casefold()


def _namen_oder_nummer_passt(
    beleg: Beleg,
    bewegung: Bewegung,
    gelernte: dict[str, set[str]] | None = None,
) -> bool:
    if beleg.rechnungsnummer:
        nr = _nummer_norm(beleg.rechnungsnummer)
        zweck_norm = _nummer_norm(f"{bewegung.gegenpartei or ''} {bewegung.zweck or ''}")
        if len(nr) >= 5 and nr in zweck_norm:
            return True
        if "/" in beleg.rechnungsnummer:
            kurz = _nummer_norm(beleg.rechnungsnummer.split("/")[-1])
            if len(kurz) >= 5 and kurz in zweck_norm:
                return True
    if gelernte and beleg.partner and bewegung.gegenpartei:
        bekannte = gelernte.get(beleg.partner.strip().casefold(), set())
        if bewegung.gegenpartei.strip().casefold() in bekannte:
            return True
    namen = _token(bewegung.gegenpartei) | _token(bewegung.zweck)
    beleg_worte = _token(beleg.text_auszug) | _token(beleg.dateiname) | _token(beleg.partner)
    if namen & beleg_worte:
        return True
    partner_worte = _token(beleg.partner) | _token(beleg.dateiname)
    for b_wort in partner_worte:
        if len(b_wort) >= 5 and any(b_wort in m_wort or (len(m_wort) >= 5 and m_wort in b_wort) for m_wort in namen):
            return True
    return False


def _passt(
    beleg: Beleg,
    bewegung: Bewegung,
    gelernte: dict[str, set[str]] | None = None,
) -> bool:
    if not _betrag_passt(beleg, bewegung):
        return False
    return _namen_oder_nummer_passt(beleg, bewegung, gelernte)


def setze_belege(session: Session, bewegung_id: int, beleg_ids: list[int]) -> Bewegung:
    bewegung = session.get(Bewegung, bewegung_id)
    if bewegung is None:
        raise ValueError("Bewegung nicht gefunden.")
    for link in list(session.scalars(select(BewegungBeleg).where(BewegungBeleg.bewegung_id == bewegung_id))):
        session.delete(link)
    bewegung.beleg_id = None
    session.flush()
    gesehen: list[int] = []
    for beleg_id in beleg_ids:
        if beleg_id in gesehen:
            continue
        beleg = session.get(Beleg, beleg_id)
        if beleg is None or beleg.art == "abrechnung":
            raise ValueError("Beleg nicht gefunden.")
        andere = session.scalar(select(BewegungBeleg).where(BewegungBeleg.beleg_id == beleg_id))
        spalte = session.scalar(select(Bewegung).where(Bewegung.beleg_id == beleg_id, Bewegung.bewegung_id != bewegung_id))
        if andere is not None or spalte is not None:
            raise ValueError("Dieser Beleg hängt schon an einer anderen Bewegung.")
        session.add(BewegungBeleg(bewegung_id=bewegung_id, beleg_id=beleg_id, zuordnung="manuell"))
        gesehen.append(beleg_id)
        if bewegung.betrag > 0:
            _markiere_rechnung_bezahlt_fuer_beleg(session, beleg, bewegung)
    bewegung.beleg_id = gesehen[0] if gesehen else None
    bewegung.zuordnung = "manuell" if gesehen else ""
    if len(gesehen) == 1:
        einzel = session.get(Beleg, gesehen[0])
        if einzel is not None and einzel.partner and einzel.partner_herkunft in {"sicher", "korrigiert"}:
            partner_zeile = partner_pflegen(
                session,
                einzel.partner,
                einzel.text_auszug or "",
                datum=einzel.datum,
                betrag=einzel.betrag,
                nummer=einzel.rechnungsnummer,
            )
            if partner_zeile is not None:
                einzel.geschaeftspartner_id = partner_zeile.partner_id
    return bewegung


def manuell(session: Session, bewegung_id: int, beleg_id: int | None) -> Bewegung:
    return setze_belege(session, bewegung_id, [] if beleg_id is None else [beleg_id])


def entfernen(session: Session, beleg_id: int) -> None:
    beleg = session.get(Beleg, beleg_id)
    if beleg is None:
        raise ValueError("Beleg nicht gefunden.")
    if beleg.art == "abrechnung":
        erzeugte = list(session.scalars(select(Bewegung).where(Bewegung.import_beleg_id == beleg_id)))
        for bewegung in erzeugte:
            for link in list(session.scalars(select(BewegungBeleg).where(BewegungBeleg.bewegung_id == bewegung.bewegung_id))):
                session.delete(link)
        session.flush()
        for bewegung in erzeugte:
            session.delete(bewegung)
        session.flush()
    for link in list(session.scalars(select(BewegungBeleg).where(BewegungBeleg.beleg_id == beleg_id))):
        session.delete(link)
    for bewegung in session.scalars(select(Bewegung).where(Bewegung.beleg_id == beleg_id)):
        bewegung.beleg_id = None
        bewegung.zuordnung = ""
    for bewegung in session.scalars(select(Bewegung).where(Bewegung.import_beleg_id == beleg_id)):
        bewegung.import_beleg_id = None
    session.flush()
    datei = ordner() / beleg.datei
    session.delete(beleg)
    session.flush()
    if datei.is_file():
        datei.unlink()


def bewegung_entfernen(session: Session, bewegung_id: int) -> None:
    bewegung = session.get(Bewegung, bewegung_id)
    if bewegung is None:
        raise ValueError("Bewegung nicht gefunden.")
    for link in list(session.scalars(select(BewegungBeleg).where(BewegungBeleg.bewegung_id == bewegung_id))):
        session.delete(link)
    session.flush()
    session.delete(bewegung)
    session.flush()


def datev_zip(
    session: Session,
    konto: str = "",
    nur_ungeliefert: bool = False,
    als_geliefert_markieren: bool = False,
) -> bytes:
    abfrage_bew = select(Bewegung).order_by(Bewegung.datum, Bewegung.bewegung_id)
    if konto:
        abfrage_bew = abfrage_bew.where(Bewegung.quelle == konto)
    if nur_ungeliefert:
        abfrage_bew = abfrage_bew.where(Bewegung.datev_geliefert.is_(None))
    bewegungen = list(session.scalars(abfrage_bew))

    alle_belege = {
        beleg.beleg_id: beleg
        for beleg in session.scalars(select(Beleg).order_by(Beleg.beleg_id))
        if not (beleg.datei or "").startswith("rechnung:")
    }
    if not konto and not nur_ungeliefert:
        belege = list(alle_belege.values())
    else:
        benoetigt_ids: set[int] = set()
        for bewegung in bewegungen:
            if bewegung.import_beleg_id and bewegung.import_beleg_id in alle_belege:
                benoetigt_ids.add(bewegung.import_beleg_id)
            if bewegung.beleg_id and bewegung.beleg_id in alle_belege:
                benoetigt_ids.add(bewegung.beleg_id)
            for link in session.scalars(select(BewegungBeleg).where(BewegungBeleg.bewegung_id == bewegung.bewegung_id)):
                if link.beleg_id in alle_belege:
                    benoetigt_ids.add(link.beleg_id)
        for beleg in alle_belege.values():
            if konto and beleg.quelle != konto:
                continue
            if nur_ungeliefert and beleg.datev_gesendet is not None and beleg.beleg_id not in benoetigt_ids:
                continue
            if beleg.art == "abrechnung" or not nur_ungeliefert or beleg.datev_gesendet is None:
                benoetigt_ids.add(beleg.beleg_id)
        belege = [alle_belege[bid] for bid in sorted(benoetigt_ids)]

    namen = {
        beleg.beleg_id: (
            f"abrechnungen/{beleg.beleg_id}-{beleg.dateiname}"
            if beleg.art == "abrechnung"
            else f"belege/{beleg.beleg_id}-{beleg.dateiname}"
        )
        for beleg in belege
    }
    csv_puffer = io.StringIO()
    schreiber = csv.writer(csv_puffer, delimiter=";", lineterminator="\n")
    schreiber.writerow(["Datum", "Betrag", "Waehrung", "Quelle", "Gegenpartei", "Verwendungszweck", "Abrechnungsdatei", "Belegdatei"])
    for bewegung in bewegungen:
        abrechnungs_name = namen.get(bewegung.import_beleg_id, "") if bewegung.import_beleg_id else ""
        schreiber.writerow([
            bewegung.datum.strftime("%d.%m.%Y"),
            f"{bewegung.betrag:.2f}".replace(".", ","),
            bewegung.waehrung,
            bewegung.quelle,
            bewegung.gegenpartei,
            bewegung.zweck,
            abrechnungs_name,
            ", ".join(_dateien(session, bewegung, namen)),
        ])
    ausgang = stb_ausgangsrechnungen(session, nur_ungeliefert=nur_ungeliefert)
    dokumente = [("bewegungen.csv", None), *[(name, None) for name, _inhalt in ausgang]]
    for beleg in belege:
        pfad = ordner() / beleg.datei
        if pfad.is_file():
            dokumente.append((namen[beleg.beleg_id], beleg.beleg_id))
    xml = _document_xml(dokumente)
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as paket:
        paket.writestr("document.xml", xml)
        paket.writestr("bewegungen.csv", csv_puffer.getvalue().encode("utf-8-sig"))
        for beleg in belege:
            pfad = ordner() / beleg.datei
            if pfad.is_file():
                paket.write(pfad, namen[beleg.beleg_id])
        for name, inhalt in ausgang:
            paket.writestr(name, inhalt)
    if als_geliefert_markieren:
        jetzt = datetime.now()
        for bewegung in bewegungen:
            if bewegung.datev_geliefert is None:
                bewegung.datev_geliefert = jetzt
        for beleg in belege:
            if beleg.datev_gesendet is None:
                beleg.datev_gesendet = jetzt
        markierte_r = stb_markiere_ausgangsrechnungen(session, jetzt) if not konto else 0
        session.add(ExportVorgang(
            zeitpunkt=jetzt,
            art="zip",
            konto=konto,
            zusammenfassung=f"ZIP-Export: {len(belege)} Belege, {len(bewegungen)} Umsätze, {markierte_r} Ausgangsrechnungen",
            daten_json=json.dumps({
                "konto": konto,
                "beleg_ids": [b.beleg_id for b in belege],
                "bewegung_ids": [b.bewegung_id for b in bewegungen],
                "rechnung_ids": [],
                "emails_gesendet": 0,
            }),
        ))
        session.flush()
    return puffer.getvalue()


def _dateien(session: Session, bewegung: Bewegung, namen: dict[int, str]) -> list[str]:
    dateien = [namen[link.beleg_id] for link in session.scalars(select(BewegungBeleg).where(BewegungBeleg.bewegung_id == bewegung.bewegung_id)) if link.beleg_id in namen]
    if not dateien and bewegung.beleg_id in namen:
        dateien = [namen[bewegung.beleg_id]]
    return dateien


def ocr_nachholen(session: Session, beleg_id: int) -> Beleg:
    """Liest den Text eines vorhandenen Belegs (erneut) aus, per OCR falls nötig."""
    from app.ocr import text_ermitteln

    beleg = session.get(Beleg, beleg_id)
    if beleg is None:
        raise ValueError("Beleg nicht gefunden.")
    inhalt = beleg_inhalt_laden(session, beleg)
    if not inhalt:
        raise ValueError("Datei nicht gefunden.")
    text, status, hinweis = text_ermitteln(beleg.dateiname, inhalt)
    if text and len(text) > len(beleg.text_auszug or ""):
        beleg.text_auszug = text[:8000]
    if status:
        beleg.ocr_status = status
    if hinweis and "OCR" not in (beleg.pruefung or ""):
        beleg.pruefung = f"{beleg.pruefung}\n{hinweis}".strip() if beleg.pruefung else hinweis
    if beleg.art != "abrechnung" and (beleg.text_auszug or "").strip():
        erkannt = beleg_erkennen(session, beleg.dateiname, beleg.text_auszug, inhalt)
        if beleg.betrag is None and erkannt.get("betrag"):
            beleg.betrag = Decimal(erkannt["betrag"])
            beleg.betrag_herkunft = erkannt.get("betrag_herkunft") or ""
        if beleg.datum is None and erkannt.get("datum"):
            beleg.datum = date.fromisoformat(erkannt["datum"])
            beleg.datum_herkunft = erkannt.get("datum_herkunft") or ""
        if not (beleg.partner or "").strip() and erkannt.get("partner"):
            beleg.partner = erkannt["partner"]
            beleg.partner_herkunft = erkannt.get("partner_herkunft") or ""
        if not (beleg.rechnungsnummer or "").strip() and erkannt.get("rechnungsnummer"):
            beleg.rechnungsnummer = erkannt["rechnungsnummer"]
        if beleg.geschaeftspartner_id is None and erkannt.get("partner_id"):
            beleg.geschaeftspartner_id = erkannt["partner_id"]
    session.flush()
    return beleg


def vorschau_erkennen(session: Session, dateiname: str, inhalt: bytes) -> dict:
    daten = beleg_erkennen(session, dateiname, _text(dateiname, inhalt), inhalt)
    if daten.get("art") != "abrechnung" and (dateiname or "").lower().endswith((".csv", ".xml", ".sta", ".mt940")):
        try:
            if parse_kontoauszug("volksbank", dateiname, inhalt):
                daten["art"] = "abrechnung"
                daten["quelle"] = "volksbank"
        except Exception:
            pass
    return daten


def senden(session: Session, beleg_id: int, schluessel: str | None) -> str:
    from app.models import Kategorie

    beleg = session.get(Beleg, beleg_id)
    if beleg is None:
        raise ValueError("Beleg nicht gefunden.")
    kategorie = session.scalar(select(Kategorie).where(Kategorie.schluessel == (schluessel or beleg.quelle)))
    if kategorie is not None:
        postfach = (kategorie.datev_email or "").strip()
        if not postfach:
            raise ValueError(f"Für {kategorie.name} ist keine DATEV-Adresse hinterlegt.")
        name = kategorie.name
    elif (schluessel or beleg.quelle) == "ausgang":
        postfach = versand_optionen_lesen(session)["ausgang_email"]
        if not postfach:
            raise ValueError("Für Ausgangsrechnungen ist keine DATEV-Adresse hinterlegt.")
        name = "Ausgangsrechnungen"
    else:
        ziel = schluessel or vorschlag(beleg.quelle)
        if not ziel:
            namen = ", ".join(eintrag for _, eintrag in ADRESSEN.values())
            raise ValueError(
                "Für Kontoauszüge gibt es keine DATEV-Adresse namens Konto. "
                f"Vorhanden: {namen}."
            )
        postfach, name = adresse(ziel)
    inhalt = beleg_inhalt_laden(session, beleg)
    if not inhalt:
        raise ValueError("Datei nicht gefunden.")
    jetzt = datetime.now()
    betreff_text = f"Abrechnung {name}: {beleg.dateiname}" if beleg.art == "abrechnung" else f"Beleg {name}: {beleg.dateiname}"
    senden_datei(postfach, betreff_text, beleg.dateiname, inhalt)
    beleg.datev_gesendet = jetzt
    if beleg.art == "abrechnung":
        for bewegung in session.scalars(select(Bewegung).where(Bewegung.import_beleg_id == beleg.beleg_id)):
            if bewegung.datev_geliefert is None:
                bewegung.datev_geliefert = jetzt
    else:
        for bewegung in session.scalars(select(Bewegung).where(Bewegung.beleg_id == beleg.beleg_id)):
            if bewegung.datev_geliefert is None:
                bewegung.datev_geliefert = jetzt
        for link in session.scalars(select(BewegungBeleg).where(BewegungBeleg.beleg_id == beleg.beleg_id)):
            ziel_bew = session.get(Bewegung, link.bewegung_id)
            if ziel_bew is not None and ziel_bew.datev_geliefert is None:
                ziel_bew.datev_geliefert = jetzt
    return name


def rechnung_an_datev_senden(session: Session, rechnungs_id: int) -> str:
    from app.domain import berechne
    from app.pdf import rechnung_pdf

    rechnung = session.get(Rechnung, rechnungs_id, options=[selectinload(Rechnung.positionen)])
    if rechnung is None:
        raise ValueError("Rechnung nicht gefunden.")
    if not (rechnung.rechnungs_nr or "").strip():
        raise ValueError("Entwürfe ohne Rechnungsnummer können nicht an DATEV gesendet werden.")
    ausgang_email = versand_optionen_lesen(session)["ausgang_email"]
    if not ausgang_email:
        raise ValueError("Keine DATEV-Upload-E-Mail für Ausgangsrechnungen hinterlegt.")
    berechne(rechnung)
    original = (
        session.get(Rechnung, rechnung.storno_zu_rechnung_id, options=[selectinload(Rechnung.positionen)])
        if rechnung.storno_zu_rechnung_id
        else None
    )
    pdf = rechnung_pdf(rechnung, original, briefpapier=False, stammdaten=stammdaten_lesen(session))
    sicher = "".join(z if z.isalnum() or z in ".-_" else "_" for z in rechnung.rechnungs_nr)
    dateiname = f"Ausgangsrechnung-{sicher}.pdf"
    senden_datei(ausgang_email, f"Ausgangsrechnung {rechnung.rechnungs_nr}", dateiname, pdf)
    jetzt = datetime.now()
    rechnung.datev_gesendet = jetzt
    rechnung.gedruckt_buchhaltung = True
    session.flush()
    return ausgang_email


def pruefe_pdf(pfad: Path) -> str:
    if pfad.suffix.lower() != ".pdf":
        return "Keine PDF. Die Datei wurde ohne ZUGFeRD-Prüfung gespeichert."
    settings = get_settings()
    java = settings.mustang_java or shutil.which("java") or ""
    jar = settings.mustang_jar
    if not java or not jar or not Path(jar).is_file():
        return "Validator nicht verfügbar (MUSTANG_JAR oder Java fehlt). Die Datei wurde trotzdem gespeichert."
    try:
        lauf = subprocess.run(
            [java, "-Xmx1G", "-Dfile.encoding=UTF-8", "-jar", jar, "--action", "validate", "--source", str(pfad), "--no-notices"],
            capture_output=True,
            timeout=180,
            check=False,
        )
    except Exception as exc:
        return f"Prüfung fehlgeschlagen: {exc}. Die Datei wurde gespeichert."
    text = (lauf.stdout + lauf.stderr).decode("utf-8", "replace").strip()
    zeilen = [zeile for zeile in text.splitlines() if zeile.strip()]
    kurz = "\n".join(zeilen[-40:]) if zeilen else "Validator lieferte keine Ausgabe."
    return f"Exit {lauf.returncode}\n{kurz}"


def klassifiziere(pfad: Path, session: Session | None = None) -> tuple[str, str]:
    teile = {teil.casefold() for teil in pfad.parts}
    name = pfad.name.casefold()
    endung = pfad.suffix.casefold()
    if session is not None:
        for kategorie in kategorien_lesen(session):
            schluessel = kategorie.schluessel.casefold()
            if schluessel in teile:
                if "statement" in name or "kontoauszug" in name or "abrechnung" in name or "umsatz" in name:
                    return "abrechnung", kategorie.schluessel
                return "beleg", kategorie.schluessel
    if "n26" in teile:
        if "statement" in name or "kontoauszug" in name:
            return "abrechnung", "n26"
        return "beleg", "n26"
    if "americanexpress" in teile or "amex" in teile:
        if "abrechnung" in name:
            return "abrechnung", "amex"
        return "beleg", "amex"
    if any("miles" in teil for teil in teile):
        if "umsatz" in name or "abrechnung" in name:
            return "abrechnung", "miles"
        return "beleg", "miles"
    if "volksbank" in teile:
        if "kontoauszug" in name or "abrechnung" in name or endung in {".csv", ".xml", ".txt", ".sta", ".mt940"}:
            return "abrechnung", "volksbank"
        return "beleg", "volksbank"
    if "ausgangsrechnungen" in teile:
        return "ausgang", "ausgang"
    if endung in {".csv", ".xml", ".txt", ".sta", ".mt940"}:
        return "abrechnung", "volksbank"
    return "beleg", "scan"


def importiere_ordner(session: Session, wurzel: Path) -> dict:
    dateien = [pfad for pfad in wurzel.rglob("*") if pfad.is_file()]
    for pfad in dateien:
        art, quelle = klassifiziere(pfad, session)
        if art != "abrechnung":
            continue
        importiere(session, pfad.name, pfad.read_bytes(), art, quelle)
    for pfad in dateien:
        art, quelle = klassifiziere(pfad, session)
        if art == "abrechnung":
            continue
        importiere(session, pfad.name, pfad.read_bytes(), art, quelle)
    zugeordnet = zuordnen(session)
    volksbank = sum(1 for pfad in dateien if klassifiziere(pfad, session)[1] == "volksbank")
    return stand(session) | {"neu_zugeordnet": zugeordnet, "volksbank_dateien": volksbank}


def stand(session: Session) -> dict:
    bewegungen = list(session.scalars(select(Bewegung)))
    belege = [beleg for beleg in session.scalars(select(Beleg)) if not (beleg.datei or "").startswith("rechnung:")]
    belegt = _belegt(session)
    ohne = [bewegung for bewegung in bewegungen if bewegung.beleg_id is None]
    ungeliefert_bew = [bewegung for bewegung in bewegungen if bewegung.datev_geliefert is None]
    ungeliefert_bel = [beleg for beleg in belege if beleg.datev_gesendet is None]
    abrechnungen = [beleg for beleg in belege if beleg.art == "abrechnung"]
    quellen = _alle_quellen(session)
    return {
        "bewegungen": len(bewegungen),
        "bewegungen_ohne_beleg": len(ohne),
        "bewegungen_ungeliefert": len(ungeliefert_bew),
        "belege": len(belege),
        "abrechnungen": len(abrechnungen),
        "belege_ungeliefert": len(ungeliefert_bel),
        "belege_ohne_bewegung": sum(1 for beleg in belege if beleg.art != "abrechnung" and beleg.beleg_id not in belegt),
        "quellen": {
            quelle: sum(1 for bewegung in bewegungen if bewegung.quelle == quelle)
            for quelle in quellen
        },
    }


def _rechnungsdatei(nummer: str, rechnungs_id: int) -> str:
    sicher = "".join(zeichen if zeichen.isalnum() or zeichen in ".-_" else "_" for zeichen in nummer) or str(rechnungs_id)
    return f"ausgangsrechnungen/Ausgangsrechnung-{sicher}.pdf"


def stb_ausgangsrechnungen(session: Session, nur_ungeliefert: bool = True) -> list[tuple[str, bytes]]:
    from app.domain import berechne
    from app.pdf import rechnung_pdf

    abfrage = select(Rechnung).where(Rechnung.rechnungs_nr.is_not(None), Rechnung.rechnungs_nr != "").options(selectinload(Rechnung.positionen))
    if nur_ungeliefert:
        abfrage = abfrage.where(Rechnung.datev_gesendet.is_(None))
    ergebnis: list[tuple[str, bytes]] = []
    stamm = stammdaten_lesen(session)
    for rechnung in session.scalars(abfrage.order_by(Rechnung.rechnungs_nr, Rechnung.rechnungs_id)):
        berechne(rechnung)
        original = (
            session.get(Rechnung, rechnung.storno_zu_rechnung_id, options=[selectinload(Rechnung.positionen)])
            if rechnung.storno_zu_rechnung_id
            else None
        )
        pdf = rechnung_pdf(rechnung, original, briefpapier=False, stammdaten=stamm)
        ergebnis.append((_rechnungsdatei(rechnung.rechnungs_nr or "", rechnung.rechnungs_id), pdf))
    return ergebnis


def stb_markiere_ausgangsrechnungen(session: Session, jetzt: datetime | None = None) -> int:
    rechnungen = list(session.scalars(
        select(Rechnung).where(
            Rechnung.rechnungs_nr.is_not(None),
            Rechnung.rechnungs_nr != "",
            Rechnung.datev_gesendet.is_(None),
        )
    ))
    stempel = jetzt or datetime.now()
    for rechnung in rechnungen:
        rechnung.datev_gesendet = stempel
        rechnung.gedruckt_buchhaltung = True
    session.flush()
    return len(rechnungen)


def abrechnungen_uebersicht(session: Session, konto: str = "") -> list[dict]:
    abfrage = select(Beleg).where(Beleg.art == "abrechnung").order_by(Beleg.beleg_id.desc())
    if konto:
        abfrage = abfrage.where(Beleg.quelle == konto)
    abrechnungen = list(session.scalars(abfrage))
    bewegungen = list(session.scalars(select(Bewegung)))
    je_import: dict[int, list[Bewegung]] = defaultdict(list)
    for bewegung in bewegungen:
        if bewegung.import_beleg_id:
            je_import[bewegung.import_beleg_id].append(bewegung)
    ergebnis = []
    for beleg in abrechnungen:
        zeilen = je_import.get(beleg.beleg_id, [])
        daten = [b.datum for b in zeilen]
        ergebnis.append({
            "beleg_id": beleg.beleg_id,
            "dateiname": beleg.dateiname,
            "quelle": beleg.quelle,
            "eingang": beleg.erstellt.date().isoformat() if isinstance(beleg.erstellt, datetime) else (beleg.erstellt.isoformat() if beleg.erstellt else None),
            "von": min(daten).isoformat() if daten else None,
            "bis": max(daten).isoformat() if daten else None,
            "umsaetze": len(zeilen),
            "geprueft": sum(1 for b in zeilen if b.geprueft),
            "zugeordnet": sum(1 for b in zeilen if b.beleg_id is not None),
            "geliefert": sum(1 for b in zeilen if b.datev_geliefert is not None),
            "datev_gesendet": beleg.datev_gesendet.isoformat(timespec="minutes") if beleg.datev_gesendet else None,
            "datei_vorhanden": (ordner() / beleg.datei).is_file(),
        })
    return ergebnis


def _bewegung(session: Session, quelle: str, umsatz: dict, import_beleg_id: int) -> bool:
    roh = "|".join([
        quelle,
        umsatz["datum"].isoformat(),
        f"{umsatz['betrag']:.2f}",
        umsatz.get("gegenpartei", ""),
        umsatz.get("zweck", ""),
    ])
    finger = hashlib.sha256(roh.encode("utf-8")).hexdigest()
    if session.scalar(select(Bewegung).where(Bewegung.fingerabdruck == finger)):
        return False
    session.add(Bewegung(
        quelle=quelle,
        datum=umsatz["datum"],
        betrag=umsatz["betrag"],
        waehrung=umsatz.get("waehrung") or "EUR",
        gegenpartei=umsatz.get("gegenpartei") or "",
        zweck=umsatz.get("zweck") or "",
        fingerabdruck=finger,
        import_beleg_id=import_beleg_id,
        zuordnung="",
    ))
    return True


def _speichern(digest: str, dateiname: str, inhalt: bytes) -> str:
    endung = Path(dateiname).suffix.lower()
    if endung not in {".pdf", ".xml", ".csv", ".txt", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff"}:
        endung = ".bin"
    name = digest + endung
    ziel = ordner() / name
    if not ziel.exists():
        ziel.write_bytes(inhalt)
    return name


def _text(dateiname: str, inhalt: bytes) -> str:
    if dateiname.lower().endswith(".pdf"):
        try:
            return pdf_text(inhalt)
        except Exception:
            return ""
    if dateiname.lower().endswith((".txt", ".csv", ".xml")):
        return inhalt.decode("utf-8", "replace")
    return ""


def _token(text: str) -> set[str]:
    woerter = re.findall(r"[A-Za-zÄÖÜäöüß0-9]{4,}", text or "")
    ergebnis: set[str] = set()
    for wort in woerter:
        klein = wort.casefold()
        if klein in _STOP or wort.isdigit():
            continue
        ergebnis.add(klein)
        if klein in _ALIAS_TOKEN:
            ergebnis.add(_ALIAS_TOKEN[klein])
    return ergebnis


def _sicher(name: str) -> str:
    sauber = Path(name).name.replace("\\", "_").replace("/", "_")
    return sauber or "beleg.pdf"


def _document_xml(dateien: list[tuple[str, int | None]]) -> str:
    jetzt = datetime.now().replace(microsecond=0).isoformat()
    teile = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<archive",
        '  xmlns="http://xml.datev.de/bedi/tps/document/v05.0"',
        '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
        '  xsi:schemaLocation="http://xml.datev.de/bedi/tps/document/v05.0 Document_v050.xsd"',
        '  version="5.0"',
        '  generatingSystem="Buchhaltung">',
        "  <header>",
        f"    <date>{jetzt}</date>",
        "    <description>Bewegungen und Originalbelege. Buchungssätze folgen später als weiteres extension-Element.</description>",
        "  </header>",
        "  <content>",
    ]
    for name, _beleg_id in dateien:
        teile.append(f'    <document guid="{uuid4()}">')
        teile.append(f'      <extension xsi:type="File" name="{_xml(name)}"/>')
        teile.append("    </document>")
    teile.append("  </content>")
    teile.append("</archive>")
    return "\n".join(teile) + "\n"


# 34 Felder der DATEV ASCII-Weiterverarbeitungsdatei für Bankkontoumsätze (Dok.-Nr. 9226961)
_DATEV_9226961_TYPEN = (
    "A", "A", "A", "D", "D", "D", "N", "A", "A", "A", "A",
    "A", "A", "A", "A", "A", "A", "A",
    "A", "A", "A", "A", "A", "A",
    "N", "A", "N", "A", "N", "A",
    "A", "A", "A", "A",
)


def datev_weiterverarbeitung_csv(bewegungen: list[Bewegung], kategorie: Kategorie) -> tuple[str, bytes]:
    """Erzeugt die DATEV ASCII-Weiterverarbeitungsdatei (Dok.-Nr. 9226961, 34 Felder, Windows-1252)."""
    bic = (kategorie.bic or "").strip().upper()
    iban = (kategorie.iban or "").strip().replace(" ", "").upper() or kategorie.schluessel.upper()
    sortiert = sorted(bewegungen, key=lambda b: (b.datum, b.bewegung_id))
    zeilen: list[str] = []
    for bew in sortiert:
        datum_str = bew.datum.strftime("%d.%m.%Y")
        betrag_str = f"{Decimal(bew.betrag):.2f}"
        gegen = re.sub(r"[\r\n]+", " ", (bew.gegenpartei or "").strip())
        name1 = gegen[:27]
        name2 = gegen[27:54] if len(gegen) > 27 else ""
        zweck = re.sub(r"[\r\n]+", " ", (bew.zweck or "").strip())
        if not zweck:
            zweck = gegen
        vz = [zweck[i * 27:(i + 1) * 27] for i in range(14)]
        buchungstext = ("Gutschrift" if bew.betrag > 0 else "Belastung")[:27]
        waehrung = (bew.waehrung or "EUR").strip()[:3] or "EUR"
        felder = [
            bic,            # 1: BLZ/BIC Kontoinhaber (M)
            iban,           # 2: Konto/IBAN Kontoinhaber (M)
            "",             # 3: Auszugsnummer
            datum_str,      # 4: Auszugsdatum
            datum_str,      # 5: Valuta
            datum_str,      # 6: Buchungsdatum (M)
            betrag_str,     # 7: Umsatz (M, N)
            name1,          # 8: Auftraggebername 1
            name2,          # 9: Auftraggebername 2
            "",             # 10: BLZ/BIC Auftraggeber
            "",             # 11: Konto/IBAN Auftraggeber
            vz[0],          # 12: Verwendungszweck 1
            vz[1],          # 13: Verwendungszweck 2
            vz[2],          # 14: Verwendungszweck 3
            vz[3],          # 15: Verwendungszweck 4
            "",             # 16: Geschäftsvorgangscode
            waehrung,       # 17: Währung
            buchungstext,   # 18: Buchungstext
            vz[4],          # 19: Verwendungszweck 5
            vz[5],          # 20: Verwendungszweck 6
            vz[6],          # 21: Verwendungszweck 7
            vz[7],          # 22: Verwendungszweck 8
            vz[8],          # 23: Verwendungszweck 9
            vz[9],          # 24: Verwendungszweck 10
            "",             # 25: Ursprungsbetrag (N)
            "",             # 26: Währung Ursprungsbetrag
            "",             # 27: Äquivalenzbetrag (N)
            "",             # 28: Währung Äquivalenzbetrag
            "",             # 29: Gebühr (N)
            "",             # 30: Währung Gebühr
            vz[10],         # 31: Verwendungszweck 11
            vz[11],         # 32: Verwendungszweck 12
            vz[12],         # 33: Verwendungszweck 13
            vz[13],         # 34: Verwendungszweck 14
        ]
        formatiert = []
        for wert, typ in zip(felder, _DATEV_9226961_TYPEN):
            if typ == "A":
                formatiert.append('"' + (wert or "").replace('"', '""') + '"')
            else:
                formatiert.append(wert or "")
        zeilen.append(";".join(formatiert))
    text_inhalt = "\r\n".join(zeilen) + ("\r\n" if zeilen else "")
    von = sortiert[0].datum.strftime("%Y%m%d") if sortiert else datetime.now().strftime("%Y%m%d")
    bis = sortiert[-1].datum.strftime("%Y%m%d") if sortiert else von
    dateiname = f"DATEV_Weiterverarbeitung_{kategorie.schluessel}_{von}-{bis}.csv"
    return dateiname, text_inhalt.encode("cp1252", errors="replace")


def _stb_mail_text(anzahl_dateien: int) -> str:
    basis = "Sehr geehrte Damen und Herren,\n\ndie aktuellen Belege wurden an Datev übertragen."
    if anzahl_dateien == 1:
        return basis + " Im Anhang finden Sie die Datev Weiterverarbeitungsdatei.\n"
    if anzahl_dateien > 1:
        return basis + " Im Anhang finden Sie die Datev Weiterverarbeitungsdateien.\n"
    return basis + "\n"


def export_vorgaenge_liste(session: Session) -> list[dict]:
    vorgaenge = list(session.scalars(select(ExportVorgang).order_by(ExportVorgang.export_id.desc()).limit(50)))
    ergebnis = []
    for vorgang in vorgaenge:
        try:
            daten = json.loads(vorgang.daten_json or "{}")
        except Exception:
            daten = {}
        konten_set: set[str] = set()
        for eintrag in daten.get("belege") or []:
            if eintrag.get("konto"):
                konten_set.add(eintrag["konto"])
        for bid in daten.get("bewegung_ids") or []:
            bew = session.get(Bewegung, bid)
            if bew is not None and bew.quelle:
                konten_set.add(bew.quelle)
        if daten.get("rechnung_ids"):
            konten_set.add("ausgang")
        ergebnis.append({
            "export_id": vorgang.export_id,
            "zeitpunkt": vorgang.zeitpunkt.isoformat(timespec="minutes"),
            "art": vorgang.art,
            "konto": vorgang.konto or "",
            "konten": sorted(konten_set),
            "zusammenfassung": vorgang.zusammenfassung or "",
            "belege_anzahl": len(daten.get("beleg_ids") or []),
            "rechnungen_anzahl": len(daten.get("rechnung_ids") or []),
            "bewegungen_anzahl": len(daten.get("bewegung_ids") or []),
            "emails_gesendet": int(daten.get("emails_gesendet") or 0),
        })
    return ergebnis


def email_export_ausfuehren(
    session: Session,
    konto: str = "",
    nur_ungeliefert: bool = True,
    vorgang_id: int | None = None,
) -> dict:
    from app.domain import berechne
    from app.pdf import rechnung_pdf

    kategorien_map = {k.schluessel: k for k in kategorien_lesen(session)}
    versand_opt = versand_optionen_lesen(session)
    stb_email = versand_opt["stb_email"]
    ausgang_email = versand_opt["ausgang_email"]

    if vorgang_id is not None:
        alt = session.get(ExportVorgang, vorgang_id)
        if alt is None:
            raise ValueError("Exportvorgang nicht gefunden.")
        daten = json.loads(alt.daten_json or "{}")
        filter_konto = konto or daten.get("konto") or alt.konto or ""
        konto = filter_konto
        bewegungen = [session.get(Bewegung, bid) for bid in (daten.get("bewegung_ids") or [])]
        bewegungen = [
            b for b in bewegungen
            if b is not None and (not filter_konto or filter_konto == "ausgang" or b.quelle == filter_konto)
        ]
        if filter_konto == "ausgang":
            bewegungen = []
        belege_Paare: list[tuple[Beleg, str]] = []
        if filter_konto != "ausgang":
            for eintrag in daten.get("belege") or []:
                b = session.get(Beleg, eintrag.get("beleg_id"))
                ziel_k = eintrag.get("konto") or (b.quelle if b is not None else "")
                if b is not None and (not filter_konto or ziel_k == filter_konto or b.quelle == filter_konto):
                    belege_Paare.append((b, ziel_k))
            if not belege_Paare and daten.get("beleg_ids"):
                for bid in daten.get("beleg_ids") or []:
                    b = session.get(Beleg, bid)
                    if b is not None and (not filter_konto or b.quelle == filter_konto):
                        belege_Paare.append((b, filter_konto or b.quelle))
        if not filter_konto or filter_konto == "ausgang":
            rechnungen = [
                session.get(Rechnung, rid, options=[selectinload(Rechnung.positionen)])
                for rid in (daten.get("rechnung_ids") or [])
            ]
            rechnungen = [r for r in rechnungen if r is not None]
        else:
            rechnungen = []
    else:
        if konto == "ausgang":
            bewegungen = []
            belege_Paare = []
        else:
            abfrage_bew = select(Bewegung).order_by(Bewegung.datum, Bewegung.bewegung_id)
            if konto:
                abfrage_bew = abfrage_bew.where(Bewegung.quelle == konto)
            if nur_ungeliefert:
                abfrage_bew = abfrage_bew.where(Bewegung.datev_geliefert.is_(None))
            bewegungen = list(session.scalars(abfrage_bew))

            alle_belege = {
                beleg.beleg_id: beleg
                for beleg in session.scalars(select(Beleg).order_by(Beleg.beleg_id))
                if not (beleg.datei or "").startswith("rechnung:")
            }
            ziel_konto_je_beleg: dict[int, str] = {}
            for bew in bewegungen:
                if bew.import_beleg_id and bew.import_beleg_id in alle_belege:
                    ziel_konto_je_beleg.setdefault(bew.import_beleg_id, bew.quelle)
                if bew.beleg_id and bew.beleg_id in alle_belege:
                    ziel_konto_je_beleg.setdefault(bew.beleg_id, bew.quelle)
                for link in session.scalars(select(BewegungBeleg).where(BewegungBeleg.bewegung_id == bew.bewegung_id)):
                    if link.beleg_id in alle_belege:
                        ziel_konto_je_beleg.setdefault(link.beleg_id, bew.quelle)
            for beleg in alle_belege.values():
                if konto and beleg.quelle != konto and beleg.beleg_id not in ziel_konto_je_beleg:
                    continue
                if nur_ungeliefert and beleg.datev_gesendet is not None:
                    continue
                if beleg.quelle in kategorien_map:
                    ziel_konto_je_beleg.setdefault(beleg.beleg_id, beleg.quelle)
            belege_Paare = []
            for bid in sorted(ziel_konto_je_beleg):
                b = alle_belege[bid]
                if nur_ungeliefert and b.datev_gesendet is not None:
                    continue
                belege_Paare.append((b, ziel_konto_je_beleg[bid]))

        if (not konto or konto == "ausgang") and ausgang_email:
            abfrage_r = select(Rechnung).where(
                Rechnung.rechnungs_nr.is_not(None),
                Rechnung.rechnungs_nr != "",
            ).options(selectinload(Rechnung.positionen))
            if nur_ungeliefert:
                abfrage_r = abfrage_r.where(Rechnung.datev_gesendet.is_(None))
            rechnungen = list(session.scalars(abfrage_r.order_by(Rechnung.rechnungs_nr, Rechnung.rechnungs_id)))
        else:
            rechnungen = []

    jetzt = datetime.now()
    emails_gesendet = 0
    gesendete_beleg_ids: list[int] = []
    gesendete_rechnung_ids: list[int] = []
    weiterverarbeitung_dateien: list[str] = []
    uebersprungen_ohne_adresse = 0

    # 1. Abrechnungen und zugehörige Belege je Beleg als einzelne E-Mail mit 1 Anhang an die Kategorie-Adresse senden
    for beleg, ziel_schluessel in belege_Paare:
        kat = kategorien_map.get(ziel_schluessel) or kategorien_map.get(beleg.quelle)
        empfaenger = (kat.datev_email if kat else "").strip()
        if not empfaenger:
            uebersprungen_ohne_adresse += 1
            continue
        pfad = ordner() / beleg.datei
        if not pfad.is_file():
            continue
        inhalt = pfad.read_bytes()
        betreff_text = f"Abrechnung {kat.name}: {beleg.dateiname}" if beleg.art == "abrechnung" else f"Beleg {kat.name}: {beleg.dateiname}"
        senden_datei(empfaenger, betreff_text, beleg.dateiname, inhalt)
        beleg.datev_gesendet = jetzt
        gesendete_beleg_ids.append(beleg.beleg_id)
        emails_gesendet += 1

    # 2. Ausgangsrechnungen (kompakt ohne Briefpapier) je Rechnung eine E-Mail an ausgang_email
    if rechnungen and ausgang_email:
        stamm = stammdaten_lesen(session)
        for rechnung in rechnungen:
            berechne(rechnung)
            original = (
                session.get(Rechnung, rechnung.storno_zu_rechnung_id, options=[selectinload(Rechnung.positionen)])
                if rechnung.storno_zu_rechnung_id
                else None
            )
            pdf = rechnung_pdf(rechnung, original, briefpapier=False, stammdaten=stamm)
            sicher = "".join(z if z.isalnum() or z in ".-_" else "_" for z in (rechnung.rechnungs_nr or str(rechnung.rechnungs_id)))
            dateiname = f"Ausgangsrechnung-{sicher}.pdf"
            senden_datei(ausgang_email, f"Ausgangsrechnung {rechnung.rechnungs_nr}", dateiname, pdf)
            rechnung.datev_gesendet = jetzt
            rechnung.gedruckt_buchhaltung = True
            gesendete_rechnung_ids.append(rechnung.rechnungs_id)
            emails_gesendet += 1

    # 3. Weiterverarbeitungsdateien (Dok.-Nr. 9226961) sammeln und in EINER E-Mail an StB-E-Mail senden
    bew_je_konto: dict[str, list[Bewegung]] = defaultdict(list)
    for bew in bewegungen:
        bew_je_konto[bew.quelle].append(bew)

    markierte_bewegung_ids: list[int] = []
    stb_anhaenge: list[tuple[str, bytes]] = []
    for kat_key, kat_bewegungen in bew_je_konto.items():
        kat = kategorien_map.get(kat_key)
        if kat is None:
            continue
        hat_wv = bool(kat.weiterverarbeitung and stb_email and kat_bewegungen)
        if hat_wv:
            wv_name, wv_bytes = datev_weiterverarbeitung_csv(kat_bewegungen, kat)
            stb_anhaenge.append((wv_name, wv_bytes))
            weiterverarbeitung_dateien.append(wv_name)
        if hat_wv or (kat.datev_email or "").strip():
            for bew in kat_bewegungen:
                if bew.datev_geliefert is None:
                    bew.datev_geliefert = jetzt
                markierte_bewegung_ids.append(bew.bewegung_id)

    if stb_email and (stb_anhaenge or gesendete_beleg_ids or gesendete_rechnung_ids):
        stb_betreff = (
            f"DATEV Übertragung ({len(stb_anhaenge)} Datev-Datei{'en' if len(stb_anhaenge) != 1 else ''})"
            if stb_anhaenge
            else "DATEV Übertragung abgeschlossen"
        )
        senden_dateien(
            stb_email,
            stb_betreff,
            stb_anhaenge,
            text=_stb_mail_text(len(stb_anhaenge)),
        )
        emails_gesendet += 1

    if emails_gesendet == 0:
        if uebersprungen_ohne_adresse > 0 and not stb_email:
            raise ValueError("Keine E-Mail-Adresse für die gewählten Konten oder den Steuerberater hinterlegt.")
        raise ValueError("Keine offenen Belege, Ausgangsrechnungen oder Bankumsätze zum Versenden gefunden.")

    teile_text = []
    if gesendete_beleg_ids:
        teile_text.append(f"{len(gesendete_beleg_ids)} Belege/Abrechnungen")
    if gesendete_rechnung_ids:
        teile_text.append(f"{len(gesendete_rechnung_ids)} Ausgangsrechnungen")
    if weiterverarbeitung_dateien:
        teile_text.append(f"{len(weiterverarbeitung_dateien)} Datev-Datei(en)")
    zusammenfassung = f"{emails_gesendet} E-Mails: " + (", ".join(teile_text) if teile_text else "versendet")

    vorgang = ExportVorgang(
        zeitpunkt=jetzt,
        art="email",
        konto=konto,
        zusammenfassung=zusammenfassung,
        daten_json=json.dumps({
            "konto": konto,
            "beleg_ids": gesendete_beleg_ids,
            "belege": [{"beleg_id": b.beleg_id, "konto": k} for b, k in belege_Paare if b.beleg_id in gesendete_beleg_ids],
            "rechnung_ids": gesendete_rechnung_ids,
            "bewegung_ids": markierte_bewegung_ids,
            "weiterverarbeitung": weiterverarbeitung_dateien,
            "emails_gesendet": emails_gesendet,
        }),
    )
    session.add(vorgang)
    session.flush()
    return {
        "export_id": vorgang.export_id,
        "zeitpunkt": vorgang.zeitpunkt.isoformat(timespec="minutes"),
        "zusammenfassung": zusammenfassung,
        "emails_gesendet": emails_gesendet,
        "belege_anzahl": len(gesendete_beleg_ids),
        "rechnungen_anzahl": len(gesendete_rechnung_ids),
        "bewegungen_anzahl": len(markierte_bewegung_ids),
        "weiterverarbeitung": weiterverarbeitung_dateien,
    }


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")


def _geld_gleich(links, rechts) -> bool:
    if links is None or rechts is None:
        return links is None and rechts is None
    return Decimal(links).quantize(Decimal("0.01")) == Decimal(rechts).quantize(Decimal("0.01"))


def sicherheit(zuordnung: str) -> str:
    if zuordnung in {"automatisch", "manuell"}:
        return "sicher"
    if zuordnung == "geraten":
        return "geraten"
    return "keine"


def vorschlaege_fuer(session: Session, bewegung: Bewegung) -> list[dict]:
    gelernte = _gelernte_gegenparteien(session)
    belegt = {
        andere.beleg_id
        for andere in session.scalars(select(Bewegung))
        if andere.beleg_id and andere.bewegung_id != bewegung.bewegung_id
    }
    treffer = []
    for beleg in session.scalars(select(Beleg).where(Beleg.art != "abrechnung")):
        if beleg.beleg_id in belegt:
            continue
        gruende = []
        if beleg.betrag is not None and (
            abs(beleg.betrag) == abs(bewegung.betrag)
            or _fremdwaehrung_passt(beleg.betrag, bewegung.zweck or "")
        ):
            gruende.append("gleicher Betrag")
        if _namen_oder_nummer_passt(beleg, bewegung, gelernte):
            gruende.append("Name")
        if not gruende:
            continue
        treffer.append((len(gruende), gruende, beleg))
    treffer.sort(key=lambda eintrag: (-eintrag[0], eintrag[2].dateiname))
    return [
        {
            "beleg_id": beleg.beleg_id,
            "dateiname": beleg.dateiname,
            "partner": beleg.partner,
            "betrag": f"{beleg.betrag:.2f}" if beleg.betrag is not None else None,
            "datum": beleg.datum.isoformat() if beleg.datum else None,
            "grund": ", ".join(gruende),
        }
        for _score, gruende, beleg in treffer[:8]
    ]


def korrigiere(session: Session, beleg_id: int, daten) -> Beleg:
    beleg = session.get(Beleg, beleg_id)
    if beleg is None:
        raise ValueError("Beleg nicht gefunden.")
    if daten.datum != beleg.datum:
        beleg.datum = daten.datum
        beleg.datum_herkunft = "korrigiert"
    if not _geld_gleich(daten.betrag, beleg.betrag):
        beleg.betrag = daten.betrag
        beleg.betrag_herkunft = "korrigiert"
    partner = (daten.partner or "").strip()
    if partner != (beleg.partner or ""):
        beleg.partner = partner
        beleg.partner_herkunft = "korrigiert"
    nummer = getattr(daten, "rechnungsnummer", None)
    if nummer is not None and nummer.strip() != (beleg.rechnungsnummer or ""):
        beleg.rechnungsnummer = nummer.strip()
    quelle = getattr(daten, "quelle", None)
    if quelle is not None and quelle.strip():
        ziel_quelle = quelle.strip()
        if not _quelle_gueltig(session, ziel_quelle):
            raise ValueError(f"Unbekannte Quelle {ziel_quelle}.")
        beleg.quelle = ziel_quelle
    partner_zeile = partner_pflegen(
        session,
        beleg.partner or "",
        beleg.text_auszug or "",
        datum=beleg.datum,
        betrag=beleg.betrag,
        nummer=beleg.rechnungsnummer,
    )
    beleg.geschaeftspartner_id = partner_zeile.partner_id if partner_zeile is not None else None
    return beleg


def herkunft_nachziehen(session: Session) -> None:
    offen = session.scalars(select(Beleg).where(Beleg.art != "abrechnung", Beleg.betrag_herkunft == ""))
    for beleg in offen:
        if not beleg.text_auszug and not beleg.dateiname:
            continue
        erkannt = erkenne(beleg.text_auszug or "", beleg.dateiname, eigene_namen(session))
        if beleg.betrag is None and erkannt["betrag"] is not None:
            beleg.betrag = erkannt["betrag"]
        beleg.betrag_herkunft = erkannt["betrag_herkunft"] or ("geraten" if beleg.betrag is not None else "")
        if beleg.datum is None and erkannt["datum"] is not None:
            beleg.datum = erkannt["datum"]
        beleg.datum_herkunft = erkannt["datum_herkunft"] or ("geraten" if beleg.datum is not None else "")
        if not beleg.partner and erkannt["partner"]:
            beleg.partner = erkannt["partner"]
        beleg.partner_herkunft = erkannt["partner_herkunft"] or ("geraten" if beleg.partner else "")
        if not beleg.rechnungsnummer and erkannt["rechnungsnummer"]:
            beleg.rechnungsnummer = erkannt["rechnungsnummer"]


def naechste_bewegung(session: Session, bewegung_id: int, konto: str = "") -> int | None:
    abfrage = select(Bewegung).order_by(Bewegung.datum.desc(), Bewegung.bewegung_id.desc())
    if konto:
        abfrage = abfrage.where(Bewegung.quelle == konto)
    reihe = list(session.scalars(abfrage))
    for index, bewegung in enumerate(reihe):
        if bewegung.bewegung_id == bewegung_id and index + 1 < len(reihe):
            return reihe[index + 1].bewegung_id
    return None


def vorige_bewegung(session: Session, bewegung_id: int, konto: str = "") -> int | None:
    abfrage = select(Bewegung).order_by(Bewegung.datum.desc(), Bewegung.bewegung_id.desc())
    if konto:
        abfrage = abfrage.where(Bewegung.quelle == konto)
    reihe = list(session.scalars(abfrage))
    for index, bewegung in enumerate(reihe):
        if bewegung.bewegung_id == bewegung_id and index > 0:
            return reihe[index - 1].bewegung_id
    return None


def beleg_ids_je(session: Session) -> dict[int, list[int]]:
    gruppen: dict[int, list[int]] = defaultdict(list)
    for link in session.scalars(select(BewegungBeleg).order_by(BewegungBeleg.bewegung_beleg_id)):
        gruppen[link.bewegung_id].append(link.beleg_id)
    for bewegung in session.scalars(select(Bewegung)):
        if bewegung.beleg_id and bewegung.beleg_id not in gruppen[bewegung.bewegung_id]:
            gruppen[bewegung.bewegung_id].insert(0, bewegung.beleg_id)
    return gruppen


def beleg_anzahlen(session: Session) -> dict[int, int]:
    zaehlung: dict[int, int] = defaultdict(int)
    for link in session.scalars(select(BewegungBeleg)):
        zaehlung[link.bewegung_id] += 1
    for bewegung in session.scalars(select(Bewegung)):
        if bewegung.beleg_id and zaehlung[bewegung.bewegung_id] == 0:
            zaehlung[bewegung.bewegung_id] = 1
    return zaehlung


def bewegung_je_beleg(session: Session) -> dict[int, Bewegung]:
    bewegungen = {bewegung.bewegung_id: bewegung for bewegung in session.scalars(select(Bewegung))}
    zuordnung: dict[int, Bewegung] = {}
    for bewegung in bewegungen.values():
        if bewegung.beleg_id:
            zuordnung[bewegung.beleg_id] = bewegung
    for link in session.scalars(select(BewegungBeleg)):
        ziel = bewegungen.get(link.bewegung_id)
        if ziel is not None:
            zuordnung[link.beleg_id] = ziel
    return zuordnung


def beleg_gruppen(session: Session, bewegung: Bewegung, alle: bool = False) -> dict:
    ausgangsrechnungen_abgleichen(session)
    gelernte = _gelernte_gegenparteien(session)
    eigene = {link.beleg_id for link in session.scalars(select(BewegungBeleg).where(BewegungBeleg.bewegung_id == bewegung.bewegung_id))}
    if bewegung.beleg_id:
        eigene.add(bewegung.beleg_id)
    fremd = _belegt(session) - eigene
    vorschlaege = []
    uebrige = []
    ausgeblendet = 0
    for beleg in session.scalars(select(Beleg).where(Beleg.art != "abrechnung").order_by(Beleg.dateiname)):
        if beleg.beleg_id in fremd:
            continue
        ist_ausgang = beleg.art == "ausgang" or beleg.quelle == "ausgang"
        if bewegung.betrag > 0 and not ist_ausgang and beleg.beleg_id not in eigene:
            continue
        if bewegung.betrag < 0 and ist_ausgang and beleg.beleg_id not in eigene:
            continue
        if not alle and beleg.beleg_id not in eigene:
            stichtag = beleg.datum or (beleg.erstellt.date() if isinstance(beleg.erstellt, datetime) else beleg.erstellt)
            if stichtag is None:
                ausgeblendet += 1
                continue
            diff = (bewegung.datum - stichtag).days
            if diff < -5 or diff > 30:
                ausgeblendet += 1
                continue
        gruende = []
        rang = 0
        if beleg.betrag is not None and (
            abs(beleg.betrag) == abs(bewegung.betrag)
            or _fremdwaehrung_passt(beleg.betrag, bewegung.zweck or "")
        ):
            gruende.append("gleicher Betrag")
            rang += 4
        elif beleg.betrag is not None and abs(abs(beleg.betrag) - abs(bewegung.betrag)) <= Decimal("1.00"):
            gruende.append("ähnlicher Betrag")
            rang += 1
        if _namen_oder_nummer_passt(beleg, bewegung, gelernte):
            gruende.append("Name")
            rang += 3
        fenster = 60 if ist_ausgang else 14
        if beleg.datum is not None and abs((bewegung.datum - beleg.datum).days) <= fenster:
            if gruende:
                gruende.append("Zeitraum")
            rang += 1
        tage_abstand = abs((bewegung.datum - beleg.datum).days) if beleg.datum is not None else 9999
        eintrag = {
            "beleg_id": beleg.beleg_id,
            "dateiname": beleg.dateiname,
            "partner": beleg.partner,
            "rechnungsnummer": beleg.rechnungsnummer or "",
            "quelle": beleg.quelle,
            "betrag": f"{beleg.betrag:.2f}" if beleg.betrag is not None else None,
            "datum": beleg.datum.isoformat() if beleg.datum else None,
            "eingang": beleg.erstellt.date().isoformat() if isinstance(beleg.erstellt, datetime) else (beleg.erstellt.isoformat() if beleg.erstellt else None),
            "grund": ", ".join(gruende),
            "zugeordnet": beleg.beleg_id in eigene,
            "_rang": rang,
            "_tage": tage_abstand,
        }
        if eintrag["zugeordnet"] or rang >= 2:
            vorschlaege.append(eintrag)
        else:
            uebrige.append(eintrag)
    vorschlaege.sort(key=lambda e: (not e["zugeordnet"], -e["_rang"], e["_tage"], e["dateiname"]))
    uebrige.sort(key=lambda e: (e["_tage"], e["dateiname"]))
    for liste in (vorschlaege, uebrige):
        for eintrag in liste:
            eintrag.pop("_rang", None)
            eintrag.pop("_tage", None)
    return {
        "vorschlaege": vorschlaege,
        "uebrige": uebrige,
        "beleg_ids": sorted(eigene),
        "ausgeblendet": ausgeblendet,
    }


def bewegung_dict(bewegung: Bewegung, belege: dict[int, Beleg], anzahl: int | None = None, ids: list[int] | None = None) -> dict:
    beleg = belege.get(bewegung.beleg_id) if bewegung.beleg_id else None
    import_beleg = belege.get(bewegung.import_beleg_id) if bewegung.import_beleg_id else None
    beleg_anzahl = anzahl if anzahl is not None else (1 if bewegung.beleg_id else 0)
    return {
        "bewegung_id": bewegung.bewegung_id,
        "quelle": bewegung.quelle,
        "datum": bewegung.datum.isoformat(),
        "betrag": f"{bewegung.betrag:.2f}",
        "waehrung": bewegung.waehrung,
        "gegenpartei": bewegung.gegenpartei,
        "zweck": bewegung.zweck,
        "import_beleg_id": bewegung.import_beleg_id,
        "import_dateiname": import_beleg.dateiname if import_beleg else "",
        "beleg_id": bewegung.beleg_id,
        "beleg_dateiname": beleg.dateiname if beleg else "",
        "beleg_anzahl": beleg_anzahl,
        "beleg_ids": list(ids or ([bewegung.beleg_id] if bewegung.beleg_id else [])),
        "zuordnung": bewegung.zuordnung,
        "sicherheit": sicherheit(bewegung.zuordnung),
        "geprueft": bool(bewegung.geprueft),
        "ohne_beleg": beleg_anzahl == 0,
        "datev": vorschlag(bewegung.quelle),
        "datev_geliefert": bewegung.datev_geliefert.isoformat(timespec="minutes") if bewegung.datev_geliefert else None,
    }


def beleg_dict(beleg: Beleg, bewegung: Bewegung | None) -> dict:
    return {
        "beleg_id": beleg.beleg_id,
        "dateiname": beleg.dateiname,
        "art": beleg.art,
        "quelle": beleg.quelle,
        "betrag": f"{beleg.betrag:.2f}" if beleg.betrag is not None else None,
        "eingang": beleg.erstellt.date().isoformat() if isinstance(beleg.erstellt, datetime) else (beleg.erstellt.isoformat() if beleg.erstellt else None),
        "datum": beleg.datum.isoformat() if beleg.datum else None,
        "partner": beleg.partner or "",
        "rechnungsnummer": beleg.rechnungsnummer or "",
        "betrag_herkunft": beleg.betrag_herkunft or "",
        "datum_herkunft": beleg.datum_herkunft or "",
        "partner_herkunft": beleg.partner_herkunft or "",
        "pruefung": beleg.pruefung,
        "ocr_status": beleg.ocr_status or "",
        "ohne_bewegung": beleg.art != "abrechnung" and bewegung is None,
        "bewegung_id": bewegung.bewegung_id if bewegung else None,
        "datev": vorschlag(beleg.quelle),
        "datev_gesendet": beleg.datev_gesendet.isoformat(timespec="minutes") if beleg.datev_gesendet else None,
    }
