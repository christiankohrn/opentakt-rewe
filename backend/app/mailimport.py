"""Automatischer Belegimport aus einem eigenen Postfach (IMAP).

Das Postfach ist nur für Belege da: Der Abruf holt ungesehene Mails,
importiert PDF- und Bild-Anhänge als Belege und markiert die Mails als
gelesen (auf Wunsch sortiert er sie in einen Erledigt-Ordner).
Anhanglose Mails festgelegter Absender werden als PDF aus dem Nachrichtentext übernommen.
Datei-Duplikate erkennt der Import über die Prüfsumme, bereits
verarbeitete Mails über das Protokoll.
"""

import imaplib
import io
import json
import os
import re
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
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
        "pdf_absender": _absender_anzeige(settings.imap_pdf_absender),
        "upload_token_gesetzt": bool(settings.beleg_upload_token),
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


def _absender_liste(text: str) -> str:
    eintraege: list[str] = []
    gesehen: set[str] = set()
    for roh in re.split(r"[\n,;]+", text or ""):
        eintrag = roh.strip()
        if not eintrag or eintrag.casefold() in gesehen:
            continue
        if " " in eintrag or len(eintrag) > 200:
            raise ValueError("Absender sind E-Mail-Adressen oder @domain, eine pro Zeile.")
        gesehen.add(eintrag.casefold())
        eintraege.append(eintrag)
    return ",".join(eintraege)


def _absender_anzeige(text: str) -> str:
    return "\n".join(teil.strip() for teil in (text or "").split(",") if teil.strip())


def postfach_speichern(
    host: str,
    port: int,
    benutzer: str,
    ordner: str,
    erledigt: str,
    quelle: str,
    tls: bool,
    passwort: str,
    pdf_absender: str = "",
    upload_token: str = "",
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
        "IMAP_PDF_ABSENDER": _absender_liste(pdf_absender),
    }
    if passwort:
        werte["IMAP_PASSWORD"] = passwort
    if upload_token:
        werte["BELEG_UPLOAD_TOKEN"] = upload_token.strip()
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
    settings.imap_pdf_absender = werte["IMAP_PDF_ABSENDER"]
    if passwort:
        settings.imap_password = passwort
    if upload_token:
        settings.beleg_upload_token = upload_token.strip()
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
            "pdf_absender": (einstellungen.get("pdf_absender") or "").strip(),
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
        "pdf_absender": settings.imap_pdf_absender.strip(),
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


def absender_trifft(absender: str, liste: str) -> bool:
    adresse = (absender or "").strip().casefold()
    if not adresse:
        return False
    domain = adresse.split("@", 1)[1] if "@" in adresse else ""
    for roh in re.split(r"[\n,;]+", liste or ""):
        muster = roh.strip().casefold()
        if not muster:
            continue
        if muster.startswith("@"):
            ziel = muster[1:]
            if domain and domain == ziel:
                return True
        elif muster == adresse:
            return True
    return False


def _kopf(nachricht: Message, name: str) -> str:
    roh = str(nachricht.get(name, "") or "")
    try:
        return str(make_header(decode_header(roh))).strip()
    except Exception:
        return roh.strip()


def _teiltext(teil: Message) -> str:
    inhalt = teil.get_payload(decode=True)
    if not isinstance(inhalt, bytes) or not inhalt:
        return ""
    zeichensatz = teil.get_content_charset() or "utf-8"
    try:
        return inhalt.decode(zeichensatz, "replace")
    except LookupError:
        return inhalt.decode("utf-8", "replace")


class _HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.teile: list[str] = []
        self._aus = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._aus = True
        if tag in {"br", "p", "div", "tr", "li", "h1", "h2", "h3"}:
            self.teile.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._aus = False
        if tag in {"p", "div", "tr", "li"}:
            self.teile.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._aus:
            self.teile.append(data)


def _html_zu_text(html: str) -> str:
    parser = _HtmlText()
    parser.feed(html)
    text = "".join(parser.teile)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def nachrichtentext(nachricht: Message) -> str:
    klartext: list[str] = []
    html: list[str] = []
    for teil in _nachricht_walk(nachricht):
        if teil.is_multipart() or teil.get_filename():
            continue
        typ = (teil.get_content_type() or "").lower()
        if typ == "text/plain":
            klartext.append(_teiltext(teil))
        elif typ == "text/html":
            html.append(_teiltext(teil))
    if any(teil.strip() for teil in klartext):
        return "\n\n".join(teil.strip() for teil in klartext if teil.strip())
    if html:
        return _html_zu_text("\n".join(html))
    return ""


def _pdf_name(betreff: str) -> str:
    roh = re.sub(r"[^\w.\- ]+", "", betreff or "", flags=re.UNICODE).strip()
    roh = re.sub(r"\s+", "-", roh)[:80].strip(".-")
    if not roh:
        roh = "mail"
    if not roh.lower().endswith(".pdf"):
        roh += ".pdf"
    return roh


def _latin(text: str) -> str:
    return (text or "").encode("latin-1", "replace").decode("latin-1")


def mail_als_pdf(absender: str, datum: str, betreff: str, text: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfgen import canvas

    puffer = io.BytesIO()
    seite = canvas.Canvas(puffer, pagesize=A4)
    breite, hoehe = A4
    links, rechts = 50, breite - 50
    y = hoehe - 56

    def schreiben(block: str, schrift: str, groesse: int, hoehe_zeile: int) -> None:
        nonlocal y
        seite.setFont(schrift, groesse)
        for rohzeile in (block or "").splitlines() or [""]:
            rest = _latin(rohzeile)
            if not rest:
                y -= hoehe_zeile
            while rest:
                ende = len(rest)
                while ende > 1 and pdfmetrics.stringWidth(rest[:ende], schrift, groesse) > rechts - links:
                    ende -= 1
                if y < 50:
                    seite.showPage()
                    y = hoehe - 56
                    seite.setFont(schrift, groesse)
                seite.drawString(links, y, rest[:ende])
                y -= hoehe_zeile
                rest = rest[ende:].lstrip() if ende < len(rest) else ""

    schreiben(f"Von: {absender}", "Helvetica-Bold", 11, 15)
    schreiben(f"Datum: {datum}", "Helvetica", 10, 14)
    schreiben(f"Betreff: {betreff}", "Helvetica-Bold", 11, 16)
    y -= 6
    schreiben(text, "Helvetica", 10, 13)
    seite.save()
    return puffer.getvalue()


def mail_pdf_anhang(nachricht: Message) -> tuple[str, bytes] | None:
    text = nachrichtentext(nachricht).strip()
    if not text:
        return None
    betreff = _kopf(nachricht, "Subject") or "Mail"
    datum = _kopf(nachricht, "Date")
    return _pdf_name(betreff), mail_als_pdf(_absender(nachricht), datum, betreff, text)


def _art_und_quelle(session: Session, dateiname: str, inhalt: bytes, reserve_quelle: str) -> tuple[str, str]:
    from app.belege import _text
    from app.erkennung import klassifiziere_text

    art, quelle = klassifiziere_text(session, dateiname, _text(dateiname, inhalt))
    if art == "abrechnung" and quelle:
        return "abrechnung", quelle
    return "beleg", reserve_quelle


def _imap_meldung(antwort) -> str:
    if not antwort:
        return "keine Antwort"
    teil = antwort[0]
    if isinstance(teil, bytes):
        return teil.decode("utf-8", "replace") or "abgelehnt"
    return str(teil or "abgelehnt")


def _ordner_sicherstellen(server, ziel: str) -> None:
    try:
        typ, _antwort = server.status(ziel, "(MESSAGES)")
    except imaplib.IMAP4.error:
        typ = "NO"
    if typ != "OK":
        typ, antwort = server.create(ziel)
        if typ != "OK":
            raise RuntimeError(f"Ordner {ziel} ließ sich nicht anlegen ({_imap_meldung(antwort)}).")
    try:
        server.subscribe(ziel)
    except Exception:
        pass


def _ablegen(server, nummer: str, ziel: str) -> None:
    typ, antwort = server.copy(nummer, ziel)
    if typ != "OK":
        _ordner_sicherstellen(server, ziel)
        typ, antwort = server.copy(nummer, ziel)
    if typ != "OK":
        raise RuntimeError(f"Mail ließ sich nicht nach {ziel} sortieren ({_imap_meldung(antwort)}).")
    server.store(nummer, "+FLAGS", "\\Deleted")
    try:
        server.expunge()
    except Exception:
        pass


def _fetch_roh(teile) -> bytes:
    return b"".join(teil[1] if isinstance(teil, tuple) and isinstance(teil[1], bytes) else b"" for teil in teile or [])


def _message_id(roh: bytes) -> str:
    if not roh:
        return ""
    return str(message_from_bytes(roh).get("Message-ID", "") or "").strip()[:500]


def _bereits_importierte_verschieben(session: Session, server, ziel: str, schon: set[str], fehler: list[str], passwort: str) -> None:
    """Mails, die schon ein Beleg sind, aber noch im Eingang liegen, nachziehen.

    Der erste Versuch kann scheitern, wenn der Zielordner fehlt. Der Abruf
    markiert die Mail dabei nicht als gelesen, ältere Läufe haben das aber
    schon getan. Die bleiben sonst für immer im Eingang.
    """
    try:
        nummern = _ok(server.search(None, "ALL")).split()
    except Exception:
        return
    for roh_nummer in reversed(nummern[-_MAX_MAILS:]):
        nummer = roh_nummer.decode("ascii", "replace")
        try:
            typ, teile = server.fetch(nummer, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
            if typ != "OK":
                continue
            kennung = _message_id(_fetch_roh(teile))
            if not kennung or kennung in schon:
                continue
            if session.scalar(select(MailImport).where(MailImport.message_id == kennung)) is None:
                continue
            _ablegen(server, nummer, ziel)
            schon.add(kennung)
        except Exception as exc:
            fehler.append(f"Mail {nummer}: {_fehler_saeubern(str(exc), passwort)}")


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
        if daten["erledigt"]:
            _ordner_sicherstellen(server, daten["erledigt"])
        verschoben: set[str] = set()
        nummern = _ok(server.search(None, "UNSEEN")).split()
        for roh_nummer in reversed(nummern[-max(limit, 1):]):
            nummer = roh_nummer.decode("ascii", "replace")
            try:
                typ, teile = server.fetch(nummer, "(BODY.PEEK[])")
                if typ != "OK":
                    raise RuntimeError("Mail ließ sich nicht laden.")
                roh = _fetch_roh(teile)
                if not roh:
                    raise RuntimeError("Mail war leer.")
                nachricht = message_from_bytes(roh)
                kennung = (_message_id(roh) or sha256(roh).hexdigest()).strip()
                if session.scalar(select(MailImport).where(MailImport.message_id == kennung)) is not None:
                    uebersprungen += 1
                    if daten["erledigt"]:
                        _ablegen(server, nummer, daten["erledigt"])
                        verschoben.add(kennung)
                    else:
                        server.store(nummer, "+FLAGS", "\\Seen")
                    continue
                anhaenge = anhaenge_aus_mail(nachricht)
                if not anhaenge and absender_trifft(_absender(nachricht), daten.get("pdf_absender") or ""):
                    erzeugt = mail_pdf_anhang(nachricht)
                    if erzeugt is not None:
                        anhaenge = [erzeugt]
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
                    verschoben.add(kennung)
                else:
                    server.store(nummer, "+FLAGS", "\\Seen")
            except Exception as exc:
                fehler.append(f"Mail {nummer}: {_fehler_saeubern(str(exc), daten['passwort'])}")
        if daten["erledigt"]:
            _bereits_importierte_verschieben(session, server, daten["erledigt"], verschoben, fehler, daten["passwort"])
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
