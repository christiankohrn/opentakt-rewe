"""Audit-Ereignisse: Wer hat wann was an Sicherheit und Konten geändert.

Reine Protokolltabelle für die Nachverfolgung, ohne Oberfläche.
"""

from sqlalchemy.orm import Session

from app.models import AuditEreignis, Benutzer
from app.zeit import utcnow


def protokollieren(
    session: Session,
    aktion: str,
    akteur: Benutzer | int | None = None,
    objekt_typ: str = "benutzer",
    objekt_id: str | int | None = None,
    daten: str | None = None,
) -> AuditEreignis:
    if isinstance(akteur, Benutzer):
        akteur_id = akteur.benutzer_id
    else:
        akteur_id = akteur
    ereignis = AuditEreignis(
        zeitpunkt=utcnow(),
        akteur_id=akteur_id,
        aktion=aktion,
        objekt_typ=objekt_typ,
        objekt_id=None if objekt_id is None else str(objekt_id),
        daten=daten,
    )
    session.add(ereignis)
    return ereignis
