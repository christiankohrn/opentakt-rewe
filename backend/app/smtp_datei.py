"""SMTP-Felder in der Umgebungsdatei. Das Passwort wird nur geschrieben, nie gelesen zurückgegeben."""

import os
import re
from pathlib import Path

from app.config import get_settings


def smtp_pfad() -> Path:
    return Path(os.environ.get("BUCHHALTUNG_ENV_DATEI", "/etc/buchhaltung.env"))


def smtp_lesen() -> dict:
    settings = get_settings()
    return {
        "host": settings.smtp_host,
        "port": settings.smtp_port,
        "benutzer": settings.smtp_user,
        "absender": settings.smtp_from,
        "tls": settings.smtp_tls,
        "passwort_gesetzt": bool(settings.smtp_password),
    }


def _zeile(text: str, schluessel: str, wert: str) -> str:
    if "\n" in wert or "\r" in wert:
        raise ValueError(f"{schluessel} enthält einen Zeilenumbruch.")
    muster = re.compile(rf"^(export\s+)?{re.escape(schluessel)}=.*$", re.MULTILINE)
    neu = f"{schluessel}={wert}"
    if muster.search(text):
        return muster.sub(neu, text, count=1)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + neu + "\n"


def smtp_speichern(host: str, port: int, benutzer: str, absender: str, tls: bool, passwort: str) -> dict:
    pfad = smtp_pfad()
    if not pfad.is_file():
        raise FileNotFoundError(str(pfad))
    text = pfad.read_text(encoding="utf-8")
    werte = {
        "SMTP_HOST": host.strip(),
        "SMTP_PORT": str(int(port)),
        "SMTP_USER": benutzer.strip(),
        "SMTP_FROM": absender.strip(),
        "SMTP_TLS": "true" if tls else "false",
    }
    if passwort:
        werte["SMTP_PASSWORD"] = passwort
    for schluessel, wert in werte.items():
        text = _zeile(text, schluessel, wert)
    pfad.write_text(text, encoding="utf-8")
    settings = get_settings()
    settings.smtp_host = werte["SMTP_HOST"]
    settings.smtp_port = int(port)
    settings.smtp_user = werte["SMTP_USER"]
    settings.smtp_from = werte["SMTP_FROM"]
    settings.smtp_tls = tls
    if passwort:
        settings.smtp_password = passwort
    return smtp_lesen()
