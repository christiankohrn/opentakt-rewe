"""Lokale Texterkennung (OCR) für Belege ohne Textteil.

Jeder Beleg wird beim Import geprüft: Enthält er lesbaren Text, läuft
nichts weiter. Sonst liest Tesseract (falls installiert) Bild- und
Scan-PDFs aus. Ohne Tesseract bleibt der Beleg textlos stehen und wird
als „ohne" markiert, statt den Import abzubrechen.
"""

import io
import re
import shutil
import subprocess

_TEXT_MINDESTENS = 30
_MAX_SEITEN = 10
_MAX_BILDKANTE = 4000
_BILD_ENDUNGEN = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".heic", ".heif"}
_HEIF_ANGEMELDET = False


def tesseract_pfad() -> str | None:
    return shutil.which("tesseract")


def _tesseract(argumente: list[str], eingabe: bytes | None = None) -> bytes:
    pfad = tesseract_pfad()
    if not pfad:
        raise RuntimeError("Tesseract ist nicht installiert.")
    lauf = subprocess.run(
        [pfad, *argumente],
        input=eingabe,
        capture_output=True,
        timeout=180,
        check=False,
    )
    if lauf.returncode != 0:
        fehler = (lauf.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(f"Tesseract meldet: {fehler[-1] if fehler else 'unbekannter Fehler'}")
    return lauf.stdout


def sprachen() -> str:
    """Beste verfügbare Sprachkombination, lieber Deutsch plus Englisch."""
    try:
        ausgabe = _tesseract(["--list-langs"]).decode("utf-8", "replace").casefold()
    except Exception:
        return ""
    hat_deu = "deu" in ausgabe
    hat_eng = "eng" in ausgabe
    if hat_deu and hat_eng:
        return "deu+eng"
    if hat_deu:
        return "deu"
    if hat_eng:
        return "eng"
    return ""


def _nutztext(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def braucht_ocr(dateiname: str, inhalt: bytes) -> bool:
    name = (dateiname or "").lower()
    if name.endswith(".pdf") or inhalt.lstrip().startswith(b"%PDF"):
        try:
            from app.auszuege import pdf_text

            return len(_nutztext(pdf_text(inhalt))) < _TEXT_MINDESTENS
        except Exception:
            return True
    if any(name.endswith(endung) for endung in _BILD_ENDUNGEN):
        return True
    return False


def _heif_anmelden() -> None:
    global _HEIF_ANGEMELDET
    if _HEIF_ANGEMELDET:
        return
    _HEIF_ANGEMELDET = True
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:
        pass


def _bild_nach_png(inhalt: bytes) -> bytes | None:
    _heif_anmelden()
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        bild = Image.open(io.BytesIO(inhalt))
    except Exception:
        return None
    try:
        if max(bild.size) > _MAX_BILDKANTE:
            bild.thumbnail((_MAX_BILDKANTE, _MAX_BILDKANTE), Image.LANCZOS)
        if bild.mode not in {"RGB", "L"}:
            bild = bild.convert("RGB")
        puffer = io.BytesIO()
        bild.save(puffer, format="PNG")
        return puffer.getvalue()
    except Exception:
        return None


def _pdf_seiten_als_png(inhalt: bytes) -> list[bytes]:
    try:
        import pymupdf
    except ImportError:
        return []
    try:
        doc = pymupdf.open(stream=inhalt, filetype="pdf")
    except Exception:
        return []
    try:
        seiten = []
        for seite in doc[:_MAX_SEITEN]:
            seiten.append(seite.get_pixmap(dpi=300).tobytes("png"))
        return seiten
    except Exception:
        return []
    finally:
        doc.close()


def _ocr_png(png: bytes) -> str:
    sprache = sprachen()
    argumente = ["stdin", "stdout", "--psm", "6"]
    if sprache:
        argumente += ["-l", sprache]
    return _tesseract(argumente, png).decode("utf-8", "replace")


def text_ermitteln(dateiname: str, inhalt: bytes) -> tuple[str, str, str]:
    """Liefert (Text, Status, Hinweis). Status: text, ocr, ohne oder leer."""
    name = (dateiname or "").lower()
    ist_pdf = name.endswith(".pdf") or inhalt.lstrip().startswith(b"%PDF")
    if ist_pdf:
        try:
            from app.auszuege import pdf_text

            text = pdf_text(inhalt)
        except Exception:
            text = ""
        if len(_nutztext(text)) >= _TEXT_MINDESTENS:
            return text, "text", ""
        if tesseract_pfad() is None:
            return "", "ohne", "Kein Text im PDF. OCR nicht verfügbar (Tesseract fehlt)."
        seiten = _pdf_seiten_als_png(inhalt)
        if not seiten:
            return "", "ohne", "Kein Text im PDF. Die Seiten ließen sich nicht lesen."
        try:
            gelesen = "\n".join(_ocr_png(png) for png in seiten).strip()
        except RuntimeError as exc:
            return "", "ohne", f"Kein Text im PDF. OCR fehlgeschlagen: {exc}"
        if len(_nutztext(gelesen)) < _TEXT_MINDESTENS:
            return "", "ohne", "Kein Text im PDF. Auch OCR fand keinen lesbaren Text."
        hinweis = "" if len(seiten) < _MAX_SEITEN else f"OCR las nur die ersten {_MAX_SEITEN} Seiten."
        return gelesen, "ocr", hinweis
    if any(name.endswith(endung) for endung in _BILD_ENDUNGEN):
        if tesseract_pfad() is None:
            return "", "ohne", "Bild ohne Text. OCR nicht verfügbar (Tesseract fehlt)."
        png = _bild_nach_png(inhalt)
        if png is None:
            return "", "ohne", "Bild ohne Text. Das Format ließ sich nicht lesen."
        try:
            gelesen = _ocr_png(png).strip()
        except RuntimeError as exc:
            return "", "ohne", f"Bild ohne Text. OCR fehlgeschlagen: {exc}"
        if len(_nutztext(gelesen)) < _TEXT_MINDESTENS:
            return "", "ohne", "Bild ohne Text. Auch OCR fand keinen lesbaren Text."
        return gelesen, "ocr", ""
    if name.endswith((".txt", ".csv", ".xml")):
        return inhalt.decode("utf-8", "replace"), "text", ""
    return "", "", ""
