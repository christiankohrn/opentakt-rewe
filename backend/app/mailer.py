import smtplib
from email.message import EmailMessage

from app.config import get_settings

MAIL_TEXT = (
    "Sehr geehrte Damen und Herren,\n\n"
    "im Anhang finden Sie unsere Rechnung.\n"
    "Bei Rückfragen stehen wir Ihnen gerne zur Verfügung.\n"
)
MAIL_HTML = (
    "<span style='font-size:11pt;font-family:\"Aptos\",serif'>"
    "Sehr geehrte Damen und Herren,<br><br>"
    "im Anhang finden Sie unsere Rechnung.<br>"
    "Bei Rückfragen stehen wir Ihnen gerne zur Verfügung."
    "</span>"
)


class SmtpFehlt(Exception):
    def __init__(self, namen: list[str]):
        self.namen = namen
        super().__init__(", ".join(namen))


def smtp_pruefen() -> None:
    settings = get_settings()
    fehlt = []
    if not settings.smtp_host:
        fehlt.append("SMTP_HOST")
    if not settings.smtp_from:
        fehlt.append("SMTP_FROM")
    if fehlt:
        raise SmtpFehlt(fehlt)


def betreff(art: str, nummer: str) -> str:
    if art == "mahnung":
        return f"Mahnung zu {nummer}"
    return f"Rechnung {nummer}"


def senden(empfaenger: str, art: str, nummer: str, pdf: bytes, dateiname: str) -> None:
    senden_datei(empfaenger, betreff(art, nummer), dateiname, pdf, MAIL_TEXT, MAIL_HTML)


def senden_datei(
    empfaenger: str,
    betreff_text: str,
    dateiname: str,
    inhalt: bytes,
    text: str = "Im Anhang der Beleg.",
    html: str = "",
) -> None:
    senden_dateien(empfaenger, betreff_text, [(dateiname, inhalt)], text=text, html=html)


def senden_text(empfaenger: str, betreff_text: str, text: str) -> None:
    """Reine Textmail ohne Anhang, z. B. für Einladungen und Resets."""
    senden_dateien(empfaenger, betreff_text, [], text=text)


def senden_dateien(
    empfaenger: str,
    betreff_text: str,
    anhaenge: list[tuple[str, bytes]],
    text: str = "Im Anhang der Beleg.",
    html: str = "",
) -> None:
    smtp_pruefen()
    settings = get_settings()
    message = EmailMessage()
    message["Subject"] = betreff_text
    message["From"] = settings.smtp_from
    message["To"] = empfaenger
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    for dateiname, inhalt in anhaenge:
        haupt, sub = _mediatype(dateiname)
        message.add_attachment(inhalt, maintype=haupt, subtype=sub, filename=dateiname)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            if settings.smtp_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except Exception as exc:
        text_fehler = str(exc)
        if settings.smtp_password:
            text_fehler = text_fehler.replace(settings.smtp_password, "***")
        raise RuntimeError(f"E-Mail-Versand fehlgeschlagen: {text_fehler}") from None


def _mediatype(dateiname: str) -> tuple[str, str]:
    name = dateiname.casefold()
    if name.endswith(".pdf"):
        return "application", "pdf"
    if name.endswith(".xml"):
        return "application", "xml"
    if name.endswith(".csv"):
        return "text", "csv"
    if name.endswith((".jpg", ".jpeg")):
        return "image", "jpeg"
    if name.endswith(".png"):
        return "image", "png"
    if name.endswith(".webp"):
        return "image", "webp"
    return "application", "octet-stream"
