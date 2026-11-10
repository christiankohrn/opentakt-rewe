from decimal import Decimal, ROUND_HALF_UP


def epc_payload(name: str, iban: str, bic: str, betrag: Decimal, zweck: str) -> str:
    """EPC-QR für SEPA-Überweisungen. Verwendungszweck bleibt die Rechnungsnummer."""
    if not (name or "").strip():
        raise ValueError("Empfänger fehlt")
    kompakt = (iban or "").replace(" ", "")
    if not kompakt:
        raise ValueError("IBAN fehlt")
    amount = Decimal(betrag).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount == 0:
        raise ValueError("Betrag fehlt")
    lines = [
        "BCD",
        "2",
        "1",
        "SCT",
        bic or "",
        (name or "")[:70],
        kompakt,
        f"EUR{amount}",
        "",
        "",
        (zweck or "")[:140],
        "",
    ]
    return "\n".join(lines)
