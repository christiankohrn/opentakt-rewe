"""Automatischer Belegimport aus einem eigenen Postfach (IMAP).

Das Postfach ist nur für Belege da: Der Abruf holt ungesehene Mails,
importiert PDF- und Bild-Anhänge als Belege und markiert die Mails als
gelesen (auf Wunsch sortiert er sie in einen Erledigt-Ordner).
Datei-Duplikate erkennt der Import über die Prüfsumme, bereits
verarbeitete Mails über das Protokoll.
"""

import imaplib
import json
import os
import re
from datetime import datetime
from email import message_from_bytes
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MailImport

_ANHANG_ENDUNGEN = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".heic", ".heif", ".csv", ".xml", ".txt"}
_MAX_MAILS = 50


def _fehler_saeubern(text: str, passwort: str = "") -> str:
    sauber = text or "Unbekannter Fehler."
    geheim = passwort or get_settings().imap_password
    if geheim:
        sauber = sauber.replace(geheim, "***")
    return " ".join(sauber.split())[:500]


def postfach_pfad() -> Path:
    return Path(os.environ.get("BUCHHALTUNG_ENV_DATEI", "/etc/buchhaltung.env"))


def postfach_lesen() -> dict:
    settings = get_settings()
    return {
        "host": settings.imap_host,
        "port": settings.imap_port,
        "benutzer": settings.imap_user,
        "ordner": settings.imap_ordner or "INBOX",
        "erledigt": settings.imap_erledigt,
        "quelle": settings.imap_quelle or "eingang",
        "tls": settings.imap_tls,
        "passwort_gesetzt": bool(settings.imap_password),
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


def postfach_speichern(
    host: str,
    port: int,
    benutzer: str,
    ordner: str,
    erledigt: str,
    quelle: str,
    tls: bool,
    passwort: str,
) -> dict:
    pfad = postfach_pfad()
    if not pfad.is_file():
        raise FileNotFoundError(str(pfad))
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError("Port ist ungültig.")
    text = pfad.read_text(encoding="utf-8")
    werte = {
        "IMAP_HOST": (host or "").strip(),
        "IMAP_PORT": str(port),
        "IMAP_USER": (benutzer or "").strip(),
        "IMAP_ORDNER": (ordner or "").strip() or "INBOX",
        "IMAP_ERLEDIGT": (erledigt or "").strip(),
        "IMAP_QUELLE": (quelle or "").strip() or "eingang",
        "IMAP_TLS": "true" if tls else "false",
    }
    if passwort:
        werte["IMAP_PASSWORD"] = passwort
    for schluessel, wert in werte.items():
        text = _zeile(text, schluessel, wert)
    pfad.write_text(text, encoding="utf-8")
    settings = get_settings()
    settings.imap_host = werte["IMAP_HOST"]
    settings.imap_port = port
    settings.imap_user = werte["IMAP_USER"]
    settings.imap_ordner = werte["IMAP_ORDNER"]
    settings.imap_erledigt = werte["IMAP_ERLEDIGT"]
    settings.imap_quelle = werte["IMAP_QUELLE"]
    settings.imap_tls = tls
    if passwort:
        settings.imap_password = passwort
    return postfach_lesen()


def _einstellungen_nutzdaten(einstellungen: dict | None) -> dict:
    if einstellungen is not None:
        return {
            "host": (einstellungen.get("host") or "").strip(),
            "port": int(einstellungen.get("port") or 993),
            "benutzer": einstellungen.get("benutzer") or "",
            "passwort": einstellungen.get("passwort") or "",
            "tls": bool(einstellungen.get("tls", True)),
            "ordner": (einstellungen.get("ordner") or "INBOX").strip() or "INBOX",
            "erledigt": (einstellungen.get("erledigt") or "").strip(),
            "quelle": (einstellungen.get("quelle") or "eingang").strip() or "eingang",
        }
    settings = get_settings()
    return {
        "host": settings.imap_host.strip(),
        "port": settings.imap_port,
        "benutzer": settings.imap_user,
        "passwort": settings.imap_password,
        "tls": settings.imap_tls,
        "ordner": settings.imap_ordner.strip() or "INBOX",
        "erledigt": settings.imap_erledigt.strip(),
        "quelle": settings.imap_quelle.strip() or "eingang",
    }


def _verbindung(einstellungen: dict):
    host = einstellungen["host"]
    port = einstellungen["port"]
    try:
        if einstellungen["tls"]:
            server = imaplib.IMAP4_SSL(host, port)
        else:
            server = imaplib.IMAP4(host, port)
    except Exception as exc:
        raise RuntimeError(f"Postfach nicht erreichbar: {_fehler_saeubern(str(exc), einstellungen['passwort'])}") from None
    try:
        server.login(einstellungen["benutzer"], einstellungen["passwort"])
    except Exception as exc:
        try:
            server.logout()
        except Exception:
            pass
        raise RuntimeError(f"Anmeldung am Postfach fehlgeschlagen: {_fehler_saeubern(str(exc), einstellungen['passwort'])}") from None
    return server


def _ok(antwort: tuple) -> bytes:
    typ, daten = antwort
    if typ != "OK":
        raise RuntimeError("Der Server lehnte den Befehl ab.")
    return b"".join(teil for teil in daten if isinstance(teil, bytes))


def postfach_testen(einstellungen: dict | None = None) -> dict:
    daten = _einstellungen_nutzdaten(einstellungen)
    if not daten["host"]:
        raise ValueError("Kein Postfach konfiguriert (IMAP_HOST fehlt).")
    server = _verbindung(daten)
    try:
        try:
            server.select(daten["ordner"])
        except Exception as exc:
            raise RuntimeError(f"Ordner {daten['ordner']} nicht lesbar: {_fehler_saeubern(str(exc), daten['passwort'])}") from None
        gesamt = _ok(server.search(None, "ALL")).split()
        ungesehen = _ok(server.search(None, "UNSEEN")).split()
        try:
            server.close()
        except Exception:
            pass
        return {"ok": True, "ordner": daten["ordner"], "gesamt": len(gesamt), "ungesehen": len(ungesehen)}
    finally:
        try:
            server.logout()
        except Exception:
            pass


def anhaenge_aus_mail(nachricht: Message) -> list[tuple[str, bytes]]:
    gefunden: list[tuple[str, bytes]] = []
    gesehen: set[str] = set()
    zaehler = 0
    for teil in _nachricht_walk(nachricht):
        if teil.is_multipart():
            continue
        inhalt = teil.get_payload(decode=True)
        if not inhalt:
            continue
        dateiname = (teil.get_filename() or "").strip()
        typ = (teil.get_content_type() or "").lower()
        if not dateiname:
            if typ == "application/pdf":
                zaehler += 1
                dateiname = f"anhang-{zaehler}.pdf"
            elif typ.startswith("image/"):
                zaehler += 1
                dateiname = f"anhang-{zaehler}.jpg"
            else:
                continue
        if Path(dateiname).suffix.lower() not in _ANHANG_ENDUNGEN:
            continue
        finger = sha256(inhalt).hexdigest()
        if finger in gesehen:
            continue
        gesehen.add(finger)
        gefunden.append((Path(dateiname).name, inhalt))
    return gefunden


def _nachricht_walk(nachricht: Message):  # kleiner Umweg für alte Message-Objekte
    if hasattr(nachricht, "walk"):
        return nachricht.walk()
    return [nachricht]


def _absender(nachricht: Message) -> str:
    try:
        adressen = getaddresses([str(nachricht.get("From", ""))])
    except Exception:
        return str(nachricht.get("From", ""))[:200]
    if not adressen:
        return ""
    name, adresse = adressen[0]
    return (adresse or name or "")[:200]


def _art_und_quelle(session: Session, dateiname: str, inhalt: bytes, reserve_quelle: str) -> tuple[str, str]:
    from app.belege import _text
    from app.erkennung import klassifiziere_text

    art, quelle = klassifiziere_text(session, dateiname, _text(dateiname, inhalt))
    if art == "abrechnung" and quelle:
        return "abrechnung", quelle
    return "beleg", reserve_quelle


def _ablegen(server, nummer: str, ziel: str) -> None:
    typ, _ = server.copy(nummer, ziel)
    if typ != "OK":
        try:
            server.create(ziel)
        except Exception:
            pass
        typ, _ = server.copy(nummer, ziel)
    if typ != "OK":
        raise RuntimeError(f"Mail ließ sich nicht nach {ziel} sortieren.")
    server.store(nummer, "+FLAGS", "\\Deleted")
    try:
        server.expunge()
    except Exception:
        pass


def abrufen(session: Session, einstellungen: dict | None = None, limit: int = _MAX_MAILS) -> dict:
    from app.belege import _quelle_gueltig, importiere

    daten = _einstellungen_nutzdaten(einstellungen)
    if not daten["host"]:
        raise ValueError("Kein Postfach konfiguriert (IMAP_HOST fehlt).")
    if not _quelle_gueltig(session, daten["quelle"]):
        raise ValueError(f"Unbekannte Quelle {daten['quelle']}.")
    try:
        server = _verbindung(daten)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Postfach nicht erreichbar: {_fehler_saeubern(str(exc), daten['passwort'])}") from None
    mails = 0
    dateien = 0
    neu = 0
    uebersprungen = 0
    fehler: list[str] = []
    try:
        try:
            server.select(daten["ordner"])
        except Exception as exc:
            raise RuntimeError(f"Ordner {daten['ordner']} nicht lesbar: {_fehler_saeubern(str(exc), daten['passwort'])}") from None
        nummern = _ok(server.search(None, "UNSEEN")).split()
        for roh_nummer in nummern[-max(limit, 1):]:
            nummer = roh_nummer.decode("ascii", "replace")
            try:
                typ, teile = server.fetch(nummer, "(RFC822)")
                if typ != "OK":
                    raise RuntimeError("Mail ließ sich nicht laden.")
                roh = b"".join(teil[1] if isinstance(teil, tuple) else b"" for teil in teile)
                if not roh:
                    raise RuntimeError("Mail war leer.")
                nachricht = message_from_bytes(roh)
                kennung = (str(nachricht.get("Message-ID", "")) or sha256(roh).hexdigest()).strip()
                if session.scalar(select(MailImport).where(MailImport.message_id == kennung)) is not None:
                    uebersprungen += 1
                    server.store(nummer, "+FLAGS", "\\Seen")
                    continue
                anhaenge = anhaenge_aus_mail(nachricht)
                beleg_ids: list[int] = []
                for dateiname, inhalt in anhaenge:
                    art, quelle = _art_und_quelle(session, dateiname, inhalt, daten["quelle"])
                    ergebnis = importiere(session, dateiname, inhalt, art, quelle)
                    dateien += 1
                    if ergebnis.get("neu"):
                        neu += 1
                        beleg_ids.append(ergebnis["beleg_id"])
                try:
                    versand = parsedate_to_datetime(str(nachricht.get("Date", "")))
                    stempel = versand.replace(tzinfo=None) if versand else datetime.now()
                except Exception:
                    stempel = datetime.now()
                session.add(MailImport(
                    message_id=kennung[:500],
                    betreff=str(nachricht.get("Subject", ""))[:500],
                    absender=_absender(nachricht),
                    dateien=len(anhaenge),
                    beleg_ids_json=json.dumps(beleg_ids),
                    zeitpunkt=stempel,
                ))
                session.flush()
                mails += 1
                if daten["erledigt"]:
                    _ablegen(server, nummer, daten["erledigt"])
                else:
                    server.store(nummer, "+FLAGS", "\\Seen")
            except Exception as exc:
                fehler.append(f"Mail {nummer}: {_fehler_saeubern(str(exc), daten['passwort'])}")
        try:
            server.close()
        except Exception:
            pass
        return {"mails": mails, "dateien": dateien, "neu": neu, "uebersprungen": uebersprungen, "fehler": fehler}
    finally:
        try:
            server.logout()
        except Exception:
            pass


def protokoll(session: Session, limit: int = 50) -> list[dict]:
    zeilen = list(session.scalars(select(MailImport).order_by(MailImport.import_id.desc()).limit(limit)))
    ergebnis = []
    for zeile in zeilen:
        try:
            beleg_ids = json.loads(zeile.beleg_ids_json or "[]")
        except Exception:
            beleg_ids = []
        ergebnis.append({
            "import_id": zeile.import_id,
            "betreff": zeile.betreff,
            "absender": zeile.absender,
            "dateien": zeile.dateien,
            "beleg_ids": beleg_ids,
            "zeitpunkt": zeile.zeitpunkt.isoformat(timespec="minutes") if zeile.zeitpunkt else None,
        })
    return ergebnis
