"""Serverseitige Seiten-Vorschau für PDF- und Textbelege via PyMuPDF.

Verhindert Browser-/iOS-WebKit-Speicherabstürze bei hochauflösenden
Scanner-PDFs (z. B. Brother-MRC-Scans mit 75-Megapixel-JBIG2-Masken) und
ermöglicht Vorschauen auch für CSV-/XML-/MT940-Kontoauszüge.
"""

import base64
import fitz

TEXT_ENDUNGEN = (".csv", ".txt", ".sta", ".mt940", ".xml", ".camt", ".json")
BILD_ENDUNGEN = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def ist_pdf(name: str, inhalt: bytes) -> bool:
    return inhalt[:5] == b"%PDF-" or name.casefold().endswith(".pdf")


def ist_bild(name: str) -> bool:
    return name.casefold().endswith(BILD_ENDUNGEN)


def pdf_seiten_anzahl(inhalt: bytes) -> int:
    with fitz.open(stream=inhalt, filetype="pdf") as doc:
        return len(doc)


def pdf_seite_png(inhalt: bytes, seite: int, max_kante: int = 1600) -> bytes:
    with fitz.open(stream=inhalt, filetype="pdf") as doc:
        gesamt = len(doc)
        if seite < 1 or seite > gesamt:
            raise ValueError(f"Seite {seite} liegt außerhalb von 1..{gesamt}.")
        blatt = doc[seite - 1]
        kante = max(float(blatt.rect.width), float(blatt.rect.height), 1.0)
        faktor = max(0.2, min(2.2, max_kante / kante))
        pixmap = blatt.get_pixmap(matrix=fitz.Matrix(faktor, faktor), alpha=False)
        return pixmap.tobytes("png")


def text_vorschau(name: str, inhalt: bytes, max_zeilen: int = 160) -> str | None:
    probe = inhalt[:65536]
    if not name.casefold().endswith(TEXT_ENDUNGEN) and (b"\x00" in probe[:4096] or not probe):
        return None
    try:
        text = probe.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = probe.decode("cp1252", errors="replace")
    zeilen = text.splitlines()
    auszug = "\n".join(zeilen[:max_zeilen])
    if len(zeilen) > max_zeilen or len(inhalt) > len(probe):
        auszug += "\n…"
    return auszug


def lokale_datei_vorschau(name: str, inhalt: bytes, max_seiten: int = 5) -> dict:
    if ist_pdf(name, inhalt):
        with fitz.open(stream=inhalt, filetype="pdf") as doc:
            gesamt = len(doc)
            anzahl = min(gesamt, max_seiten)
            bilder: list[str] = []
            for index in range(anzahl):
                blatt = doc[index]
                kante = max(float(blatt.rect.width), float(blatt.rect.height), 1.0)
                faktor = max(0.2, min(1.8, 1200 / kante))
                png = blatt.get_pixmap(matrix=fitz.Matrix(faktor, faktor), alpha=False).tobytes("png")
                bilder.append("data:image/png;base64," + base64.b64encode(png).decode("ascii"))
            return {"art": "pdf", "gesamt": gesamt, "seiten": bilder}
    if ist_bild(name):
        return {"art": "bild", "gesamt": 1, "seiten": []}
    auszug = text_vorschau(name, inhalt)
    if auszug is not None:
        return {"art": "text", "gesamt": 1, "seiten": [], "text": auszug}
    return {"art": "datei", "gesamt": 0, "seiten": []}
