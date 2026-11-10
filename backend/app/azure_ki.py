"""Azure Foundry nur auf Knopfdruck. Der Schlüssel wird geschrieben und nicht zurückgegeben."""

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from app.config import get_settings

_API = "2025-04-01-preview"


def azure_lesen() -> dict:
    settings = get_settings()
    return {
        "endpoint": settings.azure_endpoint,
        "deployment": settings.azure_deployment,
        "schluessel_gesetzt": bool(settings.azure_api_key),
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


def azure_speichern(endpoint: str, deployment: str, schluessel: str) -> dict:
    pfad = Path(os.environ.get("BUCHHALTUNG_ENV_DATEI", "/etc/buchhaltung.env"))
    if not pfad.is_file():
        raise FileNotFoundError(str(pfad))
    text = pfad.read_text(encoding="utf-8")
    werte = {"AZURE_ENDPOINT": endpoint.strip().rstrip("/"), "AZURE_DEPLOYMENT": deployment.strip()}
    if schluessel:
        werte["AZURE_API_KEY"] = schluessel
    for schluessel_name, wert in werte.items():
        text = _zeile(text, schluessel_name, wert)
    pfad.write_text(text, encoding="utf-8")
    settings = get_settings()
    settings.azure_endpoint = werte["AZURE_ENDPOINT"]
    settings.azure_deployment = werte["AZURE_DEPLOYMENT"]
    if schluessel:
        settings.azure_api_key = schluessel
    os.environ["AZURE_ENDPOINT"] = settings.azure_endpoint
    os.environ["AZURE_DEPLOYMENT"] = settings.azure_deployment
    if schluessel:
        os.environ["AZURE_API_KEY"] = schluessel
    return azure_lesen()


def _fehlt() -> list[str]:
    settings = get_settings()
    namen = []
    if not settings.azure_endpoint:
        namen.append("Endpoint")
    if not settings.azure_api_key:
        namen.append("Schlüssel")
    if not settings.azure_deployment:
        namen.append("Deployment")
    return namen


def responses_url(endpoint: str) -> str:
    """Responses-API am Host. Ein schon vorhandener Pfad wird nicht noch einmal angehängt."""
    basis = (endpoint or "").strip().rstrip("/")
    if "://" not in basis:
        basis = "https://" + basis
    teile = urlsplit(basis)
    host = urlunsplit((teile.scheme, teile.netloc, "", "", "")).rstrip("/")
    return f"{host}/openai/responses?api-version={_API}"


def _text_aus_antwort(daten: dict) -> str:
    if isinstance(daten.get("output_text"), str) and daten["output_text"].strip():
        return daten["output_text"]
    teile: list[str] = []
    for eintrag in daten.get("output") or []:
        if not isinstance(eintrag, dict):
            continue
        inhalt = eintrag.get("content")
        if isinstance(inhalt, list):
            for stueck in inhalt:
                if isinstance(stueck, dict) and isinstance(stueck.get("text"), str):
                    teile.append(stueck["text"])
        elif isinstance(eintrag.get("text"), str):
            teile.append(eintrag["text"])
    if teile:
        return "\n".join(teile)
    raise RuntimeError("Azure lieferte keine Antwort.")


def _senden(eingabe: str | list) -> tuple[str, int]:
    fehlt = _fehlt()
    if fehlt:
        raise RuntimeError("Azure ist nicht konfiguriert. Fehlend: " + ", ".join(fehlt) + ".")
    settings = get_settings()
    url = responses_url(settings.azure_endpoint)
    body = json.dumps({"model": settings.azure_deployment, "input": eingabe}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "api-key": settings.azure_api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as antwort:
            status = getattr(antwort, "status", 200)
            daten = json.loads(antwort.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        exc.read()
        raise RuntimeError(f"Azure antwortet mit {exc.code}.") from None
    except urllib.error.URLError:
        raise RuntimeError("Azure ist nicht erreichbar.") from None
    return _text_aus_antwort(daten), int(status)


def _aufruf(eingabe: str | list) -> str:
    text, _status = _senden(eingabe)
    return text


def _bild_data_url(inhalt: bytes | None, dateiname: str = "") -> str:
    if not inhalt:
        return ""
    klein = (dateiname or "").lower()
    if klein.endswith(".pdf") or inhalt.lstrip().startswith(b"%PDF"):
        try:
            import pymupdf

            doc = pymupdf.open(stream=inhalt, filetype="pdf")
            try:
                if len(doc) == 0:
                    return ""
                png = doc[0].get_pixmap(dpi=150).tobytes("png")
            finally:
                doc.close()
            return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        except Exception:
            return ""
    if klein.endswith((".jpg", ".jpeg")):
        return "data:image/jpeg;base64," + base64.b64encode(inhalt).decode("ascii")
    if klein.endswith(".png"):
        return "data:image/png;base64," + base64.b64encode(inhalt).decode("ascii")
    if klein.endswith(".webp"):
        return "data:image/webp;base64," + base64.b64encode(inhalt).decode("ascii")
    return ""


def azure_testen() -> dict:
    text, status = _senden("Antworte nur mit ok.")
    kurz = text.strip()[:20]
    if get_settings().azure_api_key:
        kurz = kurz.replace(get_settings().azure_api_key, "")
    return {"ok": True, "status": status, "antwort": kurz}


def verfeinern(text: str, basis: dict, inhalt: bytes | None = None, dateiname: str = "") -> dict:
    """Ergänzt die programmatische Erkennung. Leere Felder bleiben beim Programm."""
    prompt = (
        "Verbessere die erkannte Rechnung. Antworte nur mit JSON "
        "{\"partner\",\"betrag\",\"datum\",\"rechnungsnummer\"}. "
        "Betrag als 0.00, Datum als JJJJ-MM-TT. Unbekanntes Feld leer lassen. "
        "Die programmatische Erkennung ist: "
        + json.dumps(basis, ensure_ascii=False)
        + "\n\nBeleg:\n"
        + (text or "")[:8000]
    )
    eingabe: str | list = prompt
    if not (text or "").strip() and inhalt:
        bild_url = _bild_data_url(inhalt, dateiname)
        if bild_url:
            eingabe = [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": bild_url},
                    ],
                }
            ]
    antwort = _aufruf(eingabe)
    anfang = antwort.find("{")
    ende = antwort.rfind("}")
    if anfang < 0 or ende < anfang:
        return basis
    try:
        roh = json.loads(antwort[anfang:ende + 1])
    except json.JSONDecodeError:
        return basis
    ergebnis = dict(basis)
    for feld in ("partner", "betrag", "datum", "rechnungsnummer"):
        wert = roh.get(feld)
        if isinstance(wert, str) and wert.strip():
            ergebnis[feld] = wert.strip()
    return ergebnis
