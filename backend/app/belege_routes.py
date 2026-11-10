from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_login
from app.azure_ki import verfeinern
from app.auszuege import euro
from app.belege import (
    abrechnungen_uebersicht,
    beleg_anzahlen,
    beleg_ids_je,
    beleg_dict,
    beleg_gruppen,
    bewegung_dict,
    bewegung_entfernen,
    bewegung_je_beleg,
    datev_weiterverarbeitung_csv,
    datev_zip,
    email_export_ausfuehren,
    export_vorgaenge_liste,
    herkunft_nachziehen,
    entfernen,
    importiere,
    korrigiere,
    vorschau_erkennen,
    naechste_bewegung,
    vorige_bewegung,
    senden,
    setze_belege,
    stand,
    zuordnen,
    _text,
)
from app.datev_adressen import ADRESSEN, vorschlag
from app.db import get_db
from app.erechnung import erechnung_aus_pdf
from app.kategorien import kategorien_lesen
from app.mailer import SmtpFehlt
from app.erkennung import abrechnungen_sicherstellen, partner_pflegen, partner_sicherstellen
from app.models import AbrechnungsKriterium, Beleg, Bewegung, Geschaeftspartner, Kategorie

router = APIRouter(prefix="/api", dependencies=[Depends(require_login)])


class ZuordnungIn(BaseModel):
    beleg_id: int | None = None
    beleg_ids: list[int] | None = None


class DatevIn(BaseModel):
    adresse: str | None = None


class BelegIn(BaseModel):
    datum: date | None = None
    betrag: Decimal | None = None
    partner: str = ""
    rechnungsnummer: str | None = None
    quelle: str | None = None


class BelegeKontoIn(BaseModel):
    beleg_ids: list[int]
    quelle: str


class EmailExportIn(BaseModel):
    konto: str = ""
    nur_ungeliefert: bool = True


class ExportWiederholenIn(BaseModel):
    konto: str = ""


class ZeileIn(BaseModel):
    geprueft: bool = True
    beleg_id: int | None = None
    beleg_ids: list[int] | None = None
    konto: str = ""


class GeprueftIn(BaseModel):
    geprueft: bool


class KriteriumIn(BaseModel):
    schluessel: str
    art: str
    muster: str


class PartnerIn(BaseModel):
    partner_id: int | None = None
    name: str
    ust_id: str = ""
    steuernummer: str = ""
    iban: str = ""
    datum_muster: str = ""
    nummer_muster: str = ""
    betrag_muster: str = ""


def _konto(konto: str, session: Session) -> str:
    if not konto or konto == "ausgang":
        return konto or ""
    if session.scalar(select(Kategorie).where(Kategorie.schluessel == konto)) is None:
        raise HTTPException(status_code=400, detail="Unbekanntes Konto.")
    return konto


def _typ(name: str) -> str:
    klein = name.casefold()
    if klein.endswith(".pdf"):
        return "application/pdf"
    if klein.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if klein.endswith(".png"):
        return "image/png"
    if klein.endswith(".webp"):
        return "image/webp"
    if klein.endswith(".gif"):
        return "image/gif"
    return "application/octet-stream"


def _karten(session: Session) -> dict[int, Beleg]:
    return {beleg.beleg_id: beleg for beleg in session.scalars(select(Beleg))}


@router.get("/belege/stand")
def belege_stand(session: Session = Depends(get_db)) -> dict:
    return stand(session)


@router.get("/belege")
def belege_liste(konto: str = "", session: Session = Depends(get_db)) -> list:
    kategorien_lesen(session)
    _konto(konto, session)
    herkunft_nachziehen(session)
    zuordnen(session)
    belege = [
        beleg
        for beleg in session.scalars(select(Beleg).order_by(Beleg.beleg_id.desc()))
        if not (beleg.datei or "").startswith("rechnung:")
    ]
    bewegungen = bewegung_je_beleg(session)
    if konto:
        belege = [
            beleg for beleg in belege
            if beleg.quelle == konto or (bewegungen.get(beleg.beleg_id) and bewegungen[beleg.beleg_id].quelle == konto)
        ]
    return [beleg_dict(beleg, bewegungen.get(beleg.beleg_id)) for beleg in belege]


@router.put("/belege/{beleg_id}")
def beleg_korrigieren(beleg_id: int, body: BelegIn, session: Session = Depends(get_db)) -> dict:
    try:
        beleg = korrigiere(session, beleg_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    bewegung = session.scalar(select(Bewegung).where(Bewegung.beleg_id == beleg.beleg_id))
    return beleg_dict(beleg, bewegung)


@router.post("/belege/konto")
def belege_konto_setzen(body: BelegeKontoIn, session: Session = Depends(get_db)) -> dict:
    from app.belege import _quelle_gueltig

    ziel = (body.quelle or "").strip()
    if not ziel or not _quelle_gueltig(session, ziel):
        raise HTTPException(status_code=400, detail=f"Unbekannte Quelle {ziel}.")
    geaendert = 0
    for beleg_id in body.beleg_ids:
        beleg = session.get(Beleg, beleg_id)
        if beleg is not None and beleg.quelle != ziel:
            beleg.quelle = ziel
            geaendert += 1
    session.flush()
    return {"geaendert": geaendert, "quelle": ziel}


@router.get("/bewegungen")
def bewegungen_liste(konto: str = "", session: Session = Depends(get_db)) -> list:
    kategorien_lesen(session)
    _konto(konto, session)
    zuordnen(session)
    karten = _karten(session)
    anzahlen = beleg_anzahlen(session)
    ids_je = beleg_ids_je(session)
    bewegungen = session.scalars(select(Bewegung).order_by(Bewegung.datum.desc(), Bewegung.bewegung_id.desc()))
    zeilen = [
        bewegung_dict(bewegung, karten, anzahlen.get(bewegung.bewegung_id, 0), ids_je.get(bewegung.bewegung_id, []))
        for bewegung in bewegungen
    ]
    if konto:
        zeilen = [zeile for zeile in zeilen if zeile["quelle"] == konto]
    return zeilen


@router.get("/bewegungen/{bewegung_id}")
def bewegung_lesen(bewegung_id: int, konto: str = "", alle_belege: bool = False, session: Session = Depends(get_db)) -> dict:
    bewegung = session.get(Bewegung, bewegung_id)
    if bewegung is None:
        raise HTTPException(status_code=404, detail="Bewegung nicht gefunden.")
    daten = bewegung_dict(bewegung, _karten(session), beleg_anzahlen(session).get(bewegung_id, 0))
    daten.update(beleg_gruppen(session, bewegung, alle=alle_belege))
    daten["naechste_id"] = naechste_bewegung(session, bewegung_id, konto)
    daten["vorige_id"] = vorige_bewegung(session, bewegung_id, konto)
    return daten


@router.post("/bewegungen/{bewegung_id}/geprueft")
def bewegung_geprueft(bewegung_id: int, body: GeprueftIn, session: Session = Depends(get_db)) -> dict:
    bewegung = session.get(Bewegung, bewegung_id)
    if bewegung is None:
        raise HTTPException(status_code=404, detail="Bewegung nicht gefunden.")
    bewegung.geprueft = body.geprueft
    return {"geprueft": bool(bewegung.geprueft)}


@router.post("/bewegungen/{bewegung_id}/weiter")
def bewegung_weiter(bewegung_id: int, body: ZeileIn, session: Session = Depends(get_db)) -> dict:
    bewegung = session.get(Bewegung, bewegung_id)
    if bewegung is None:
        raise HTTPException(status_code=404, detail="Bewegung nicht gefunden.")
    try:
        if body.beleg_ids is not None:
            setze_belege(session, bewegung_id, body.beleg_ids)
            bewegung = session.get(Bewegung, bewegung_id)
        elif bewegung.beleg_id != body.beleg_id:
            setze_belege(session, bewegung_id, [] if body.beleg_id is None else [body.beleg_id])
            bewegung = session.get(Bewegung, bewegung_id)
        elif body.beleg_id is not None:
            bewegung.zuordnung = "manuell"
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    bewegung.geprueft = body.geprueft
    naechste = naechste_bewegung(session, bewegung_id, body.konto)
    return {"gespeichert": bewegung_id, "naechste_id": naechste}


def _uebernehmen(
    session: Session,
    beleg: Beleg,
    partner: str | None,
    betrag: str | None,
    datum: str | None,
    nummer: str | None,
) -> None:
    if partner is not None and partner.strip() != (beleg.partner or ""):
        beleg.partner = partner.strip()
        beleg.partner_herkunft = "korrigiert"
    if nummer is not None and nummer.strip() != (beleg.rechnungsnummer or ""):
        beleg.rechnungsnummer = nummer.strip()
    if datum is not None:
        bisher = beleg.datum.isoformat() if beleg.datum else ""
        if datum != bisher:
            beleg.datum = date.fromisoformat(datum) if datum else None
            beleg.datum_herkunft = "korrigiert"
    if betrag is not None:
        text = betrag.strip()
        try:
            neu = euro(text) if text else None
        except (InvalidOperation, ValueError):
            raise HTTPException(status_code=400, detail="Betrag ist keine Zahl.") from None
        if neu != beleg.betrag:
            beleg.betrag = neu
            beleg.betrag_herkunft = "korrigiert"
    if beleg.art != "abrechnung" and beleg.partner:
        partner_zeile = partner_pflegen(
            session,
            beleg.partner,
            beleg.text_auszug or "",
            datum=beleg.datum,
            betrag=beleg.betrag,
            nummer=beleg.rechnungsnummer,
        )
        if partner_zeile is not None:
            beleg.geschaeftspartner_id = partner_zeile.partner_id


@router.post("/belege/erkennen")
async def beleg_erkennen(datei: UploadFile = File(...), session: Session = Depends(get_db)) -> dict:
    inhalt = await datei.read()
    if not inhalt:
        raise HTTPException(status_code=400, detail="Die Datei ist leer.")
    return vorschau_erkennen(session, datei.filename or "beleg", inhalt)


@router.post("/belege/ki")
async def beleg_ki(datei: UploadFile = File(...), session: Session = Depends(get_db)) -> dict:
    inhalt = await datei.read()
    if not inhalt:
        raise HTTPException(status_code=400, detail="Die Datei ist leer.")
    name = datei.filename or "beleg"
    basis = vorschau_erkennen(session, name, inhalt)
    try:
        return verfeinern(_text(name, inhalt), basis, inhalt=inhalt, dateiname=name)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.post("/belege/{beleg_id}/ki")
def beleg_ki_gespeichert(beleg_id: int, session: Session = Depends(get_db)) -> dict:
    from app.belege import ordner

    beleg = session.get(Beleg, beleg_id)
    if beleg is None:
        raise HTTPException(status_code=404, detail="Beleg nicht gefunden.")
    basis = {
        "art": beleg.art,
        "quelle": beleg.quelle,
        "partner": beleg.partner or "",
        "betrag": f"{beleg.betrag:.2f}" if beleg.betrag is not None else "",
        "datum": beleg.datum.isoformat() if beleg.datum else "",
        "rechnungsnummer": beleg.rechnungsnummer or "",
    }
    roh_inhalt = None
    if not (beleg.text_auszug or "").strip():
        pfad = ordner() / beleg.datei
        if pfad.is_file():
            roh_inhalt = pfad.read_bytes()
    try:
        ergebnis = verfeinern(beleg.text_auszug or "", basis, inhalt=roh_inhalt, dateiname=beleg.dateiname)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    _uebernehmen(
        session,
        beleg,
        ergebnis.get("partner"),
        ergebnis.get("betrag"),
        ergebnis.get("datum"),
        ergebnis.get("rechnungsnummer"),
    )
    return ergebnis


@router.post("/belege")
async def beleg_hochladen(
    datei: UploadFile = File(...),
    art: str = Form(...),
    quelle: str = Form(...),
    partner: str | None = Form(None),
    betrag: str | None = Form(None),
    datum: str | None = Form(None),
    rechnungsnummer: str | None = Form(None),
    session: Session = Depends(get_db),
) -> dict:
    inhalt = await datei.read()
    if len(inhalt) > 30 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Datei ist größer als 30 MB.")
    if not inhalt:
        raise HTTPException(status_code=400, detail="Die Datei ist leer.")
    ergebnis = importiere(session, datei.filename or "beleg", inhalt, art, quelle)
    beleg = session.get(Beleg, ergebnis["beleg_id"])
    if beleg is not None and ergebnis.get("neu"):
        _uebernehmen(session, beleg, partner, betrag, datum, rechnungsnummer)
    ergebnis["zugeordnet"] = zuordnen(session)
    ergebnis["stand"] = stand(session)
    return ergebnis


@router.post("/bewegungen/{bewegung_id}/zuordnung")
def bewegung_zuordnen(bewegung_id: int, body: ZuordnungIn, session: Session = Depends(get_db)) -> dict:
    try:
        ids = body.beleg_ids if body.beleg_ids is not None else ([] if body.beleg_id is None else [body.beleg_id])
        bewegung = setze_belege(session, bewegung_id, ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return bewegung_dict(bewegung, _karten(session), len(ids))


@router.get("/datev/adressen")
def datev_adressen(session: Session = Depends(get_db)) -> dict:
    return {
        "adressen": [
            {"schluessel": schluessel, "name": name, "postfach": postfach}
            for schluessel, (postfach, name) in ADRESSEN.items()
        ],
        "konto": None,
        "hinweis": "Für Kontoauszüge gibt es keine DATEV-Adresse namens Konto.",
        "vorschlaege": {
            kategorie.schluessel: vorschlag(kategorie.schluessel)
            for kategorie in kategorien_lesen(session)
        },
    }


@router.get("/datev/zip")
def datev_paket(
    konto: str = "",
    nur_ungeliefert: bool = False,
    markieren: bool = False,
    session: Session = Depends(get_db),
) -> Response:
    _konto(konto, session)
    paket = datev_zip(session, konto=konto, nur_ungeliefert=nur_ungeliefert, als_geliefert_markieren=markieren)
    return Response(
        content=paket,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="datev-belege.zip"'},
    )


@router.get("/datev/weiterverarbeitung")
def datev_weiterverarbeitung_download(
    konto: str,
    nur_ungeliefert: bool = False,
    session: Session = Depends(get_db),
) -> Response:
    _konto(konto, session)
    kategorie = session.scalar(select(Kategorie).where(Kategorie.schluessel == konto))
    if kategorie is None:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden.")
    abfrage = select(Bewegung).where(Bewegung.quelle == konto).order_by(Bewegung.datum, Bewegung.bewegung_id)
    if nur_ungeliefert:
        abfrage = abfrage.where(Bewegung.datev_geliefert.is_(None))
    bewegungen = list(session.scalars(abfrage))
    dateiname, inhalt = datev_weiterverarbeitung_csv(bewegungen, kategorie)
    return Response(
        content=inhalt,
        media_type="text/csv; charset=windows-1252",
        headers={"Content-Disposition": f'attachment; filename="{dateiname}"'},
    )


@router.get("/exporte")
def exporte_anzeigen(session: Session = Depends(get_db)) -> list:
    return export_vorgaenge_liste(session)


@router.post("/exporte/email")
def export_per_email(body: EmailExportIn, session: Session = Depends(get_db)) -> dict:
    _konto(body.konto, session)
    try:
        return email_export_ausfuehren(session, konto=body.konto, nur_ungeliefert=body.nur_ungeliefert)
    except SmtpFehlt as exc:
        raise HTTPException(status_code=503, detail=f"SMTP fehlt: {exc}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.post("/exporte/{export_id}/wiederholen")
def export_wiederholen(export_id: int, body: ExportWiederholenIn | None = None, session: Session = Depends(get_db)) -> dict:
    konto = (body.konto if body else "").strip()
    if konto:
        _konto(konto, session)
    try:
        return email_export_ausfuehren(session, konto=konto, vorgang_id=export_id)
    except SmtpFehlt as exc:
        raise HTTPException(status_code=503, detail=f"SMTP fehlt: {exc}") from None
    except ValueError as exc:
        status = 404 if "nicht gefunden" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.get("/abrechnungen/dateien")
def abrechnungen_dateien(konto: str = "", session: Session = Depends(get_db)) -> list:
    kategorien_lesen(session)
    _konto(konto, session)
    return abrechnungen_uebersicht(session, konto=konto)


@router.delete("/bewegungen/{bewegung_id}")
def bewegung_loeschen(bewegung_id: int, session: Session = Depends(get_db)) -> dict:
    try:
        bewegung_entfernen(session, bewegung_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return {"geloescht": bewegung_id}


@router.post("/belege/{beleg_id}/datev")
def beleg_an_datev(beleg_id: int, body: DatevIn | None = None, session: Session = Depends(get_db)) -> dict:
    try:
        name = senden(session, beleg_id, body.adresse if body else None)
    except SmtpFehlt as exc:
        raise HTTPException(status_code=503, detail=f"SMTP fehlt: {exc}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return {"ok": True, "gesendet_an": name}


@router.delete("/belege/{beleg_id}")
def beleg_loeschen(beleg_id: int, session: Session = Depends(get_db)) -> dict:
    try:
        entfernen(session, beleg_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return {"geloescht": beleg_id}


@router.get("/belege/{beleg_id}/erechnung")
def beleg_erechnung(beleg_id: int, session: Session = Depends(get_db)) -> dict:
    from app.belege import beleg_inhalt_laden

    beleg = session.get(Beleg, beleg_id)
    if beleg is None:
        raise HTTPException(status_code=404, detail="Beleg nicht gefunden.")
    inhalt = beleg_inhalt_laden(session, beleg)
    if not inhalt:
        return {"vorhanden": False}
    try:
        daten = erechnung_aus_pdf(inhalt)
    except Exception:
        return {"vorhanden": False}
    if not daten:
        return {"vorhanden": False}
    daten["vorhanden"] = True
    return daten


def _kriterium_dict(zeile: AbrechnungsKriterium) -> dict:
    return {"kriterium_id": zeile.kriterium_id, "schluessel": zeile.schluessel, "art": zeile.art, "muster": zeile.muster}


def _partner_dict(zeile: Geschaeftspartner) -> dict:
    return {
        "partner_id": zeile.partner_id,
        "name": zeile.name,
        "ust_id": zeile.ust_id or "",
        "steuernummer": zeile.steuernummer or "",
        "iban": zeile.iban or "",
        "datum_muster": zeile.datum_muster or "",
        "nummer_muster": zeile.nummer_muster or "",
        "betrag_muster": zeile.betrag_muster or "",
    }


@router.get("/abrechnungen")
def abrechnungen_liste(session: Session = Depends(get_db)) -> list:
    abrechnungen_sicherstellen(session)
    return [_kriterium_dict(zeile) for zeile in session.scalars(select(AbrechnungsKriterium).order_by(AbrechnungsKriterium.kriterium_id))]


@router.put("/abrechnungen")
def abrechnungen_setzen(body: list[KriteriumIn], session: Session = Depends(get_db)) -> list:
    arten = {"dateiname", "absender", "iban", "kartentext"}
    for zeile in session.scalars(select(AbrechnungsKriterium)):
        session.delete(zeile)
    session.flush()
    for eintrag in body:
        schluessel = eintrag.schluessel.strip()
        muster = eintrag.muster.strip()
        art = eintrag.art.strip()
        if art not in arten or not schluessel or not muster:
            raise HTTPException(status_code=400, detail="Kriterium unvollständig.")
        session.add(AbrechnungsKriterium(schluessel=schluessel, art=art, muster=muster))
    session.flush()
    return [_kriterium_dict(zeile) for zeile in session.scalars(select(AbrechnungsKriterium).order_by(AbrechnungsKriterium.kriterium_id))]


@router.get("/geschaeftspartner")
def partner_liste(session: Session = Depends(get_db)) -> list:
    partner_sicherstellen(session)
    return [_partner_dict(zeile) for zeile in session.scalars(select(Geschaeftspartner).order_by(Geschaeftspartner.name))]


@router.put("/geschaeftspartner")
def partner_setzen(body: list[PartnerIn], session: Session = Depends(get_db)) -> list:
    behalten: set[int] = set()
    for eintrag in body:
        name = eintrag.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Der Name fehlt.")
        partner = session.get(Geschaeftspartner, eintrag.partner_id) if eintrag.partner_id else None
        if partner is None:
            partner = Geschaeftspartner(name=name)
            session.add(partner)
            session.flush()
        partner.name = name
        partner.ust_id = eintrag.ust_id.strip()
        partner.steuernummer = eintrag.steuernummer.strip()
        partner.iban = eintrag.iban.strip()
        partner.datum_muster = eintrag.datum_muster.strip()
        partner.nummer_muster = eintrag.nummer_muster.strip()
        partner.betrag_muster = eintrag.betrag_muster.strip()
        behalten.add(partner.partner_id)
    for partner in list(session.scalars(select(Geschaeftspartner))):
        if partner.partner_id in behalten:
            continue
        benutzt = session.scalar(select(Beleg.beleg_id).where(Beleg.geschaeftspartner_id == partner.partner_id))
        if benutzt is None:
            session.delete(partner)
    session.flush()
    return [_partner_dict(zeile) for zeile in session.scalars(select(Geschaeftspartner).order_by(Geschaeftspartner.name))]


@router.get("/belege/{beleg_id}/datei")
def beleg_datei(beleg_id: int, session: Session = Depends(get_db)) -> Response:
    from app.belege import beleg_inhalt_laden

    beleg = session.get(Beleg, beleg_id)
    if beleg is None:
        raise HTTPException(status_code=404, detail="Beleg nicht gefunden.")
    inhalt = beleg_inhalt_laden(session, beleg)
    if inhalt is None:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")
    return Response(
        content=inhalt,
        media_type=_typ(beleg.dateiname),
        headers={"Content-Disposition": f'inline; filename="{beleg.dateiname}"', "Cache-Control": "no-store"},
    )
