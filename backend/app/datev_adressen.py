"""DATEV-Upload-Adressen je Belegart.

Die Schlüssel sind fest verdrahtet, die Adressen trägt jede Installation
selbst ein: Entweder hier als Startwerte oder pro Konto in den
Einstellungen (DATEV-Upload-E-Mail). Leere Adresse = kein Versand.
"""

ADRESSEN: dict[str, tuple[str, str]] = {
    "amex": ("", "Amex"),
    "lufthansakk": ("", "Lufthansa"),
    "rechnungsausgang": ("", "Rechnungsausgang"),
    "rechnungseingang": ("", "Rechnungseingang"),
    "sonstige": ("", "Sonstige"),
}

# Quelle des Belegs → Schlüssel in ADRESSEN. Kontoauszüge haben keinen Eintrag.
QUELLE_ADRESSE = {
    "amex": "amex",
    "miles": "lufthansakk",
    "ausgang": "rechnungsausgang",
    "eingang": "rechnungseingang",
}


def adresse(schluessel: str) -> tuple[str, str]:
    if schluessel not in ADRESSEN:
        namen = ", ".join(name for _, name in ADRESSEN.values())
        raise KeyError(f"Unbekannte DATEV-Adresse. Vorhanden: {namen}.")
    return ADRESSEN[schluessel]


def vorschlag(quelle: str) -> str | None:
    return QUELLE_ADRESSE.get(quelle)
