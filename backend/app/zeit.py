"""Naive UTC-Zeitstempel.

Die Datenbankspalten sind ohne Zeitzone angelegt (wie der Rest des
Schemas); alle neuen Zeitpunkte sind UTC ohne tzinfo, damit Vergleiche
in Python und in der Datenbank konsistent bleiben.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
