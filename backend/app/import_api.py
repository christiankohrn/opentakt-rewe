"""PDF-Upload ohne Browser-Sitzung.

POST /api/import/belege erwartet Authorization: Bearer und den Token
aus BELEG_UPLOAD_TOKEN. Ohne gesetzten Token bleibt die Schnittstelle aus.
"""

import secrets

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.belege import importiere, stand, zuordnen
from app.config import get_settings
from app.db import get_db

router = APIRouter(prefix="/api/import")
_MAX_BYTES = 30 * 1024 * 1024


def token_pruefen(authorization: str | None = Header(default=None)) -> None:
    erwartet = (get_settings().beleg_upload_token or "").strip()
    if not erwartet:
        raise HTTPException(status_code=503, detail="Upload-Token ist nicht gesetzt.")
    geliefert = ""
    if authorization and authorization.lower().startswith("bearer "):
        geliefert = authorization.split(" ", 1)[1].strip()
    if not geliefert or not secrets.compare_digest(geliefert, erwartet):
        raise HTTPException(status_code=401, detail="Token ungültig.")


def _ist_pdf(name: str, inhalt: bytes, inhaltstyp: str) -> bool:
    if not inhalt.startswith(b"%PDF"):
        return False
    if name.lower().endswith(".pdf"):
        return True
    return (inhaltstyp or "").split(";", 1)[0].strip().lower() == "application/pdf"


@router.post("/belege")
async def beleg_import(
    datei: UploadFile = File(...),
    quelle: str = Form("eingang"),
    art: str = Form("beleg"),
    session: Session = Depends(get_db),
    _: None = Depends(token_pruefen),
) -> dict:
    inhalt = await datei.read()
    if len(inhalt) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="Datei ist größer als 30 MB.")
    if not inhalt:
        raise HTTPException(status_code=400, detail="Die Datei ist leer.")
    name = datei.filename or "beleg.pdf"
    if not _ist_pdf(name, inhalt, datei.content_type or ""):
        raise HTTPException(status_code=400, detail="Nur PDF-Dateien.")
    try:
        ergebnis = importiere(session, name, inhalt, (art or "beleg").strip() or "beleg", (quelle or "eingang").strip() or "eingang")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    ergebnis["zugeordnet"] = zuordnen(session)
    ergebnis["stand"] = stand(session)
    return ergebnis
