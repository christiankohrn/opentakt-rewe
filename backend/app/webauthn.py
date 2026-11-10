"""Passkeys (WebAuthn): Registrieren und passwortloses Anmelden."""

import secrets
from urllib.parse import urlparse

from fastapi import Request
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialCreationOptions,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialRequestOptions,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.branding import PRODUCT_NAME
from app.config import get_settings
from app.models import Passkey

_DEV_HOSTS = {"localhost", "127.0.0.1"}


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _is_dev() -> bool:
    return get_settings().environment.strip().casefold() != "production"


def resolve_rp(request: Request) -> tuple[str, list[str]]:
    """Liefert (rp_id, erwartete Origins) für die aktuelle Anfrage.

    In Produktion gelten die konfigurierte rp_id und Origins (aus public_url
    abgeleitet, wenn leer). In Entwicklung wird zusätzlich ein
    localhost/127.0.0.1-Origin der Anfrage akzeptiert, damit Passkeys auf dem
    Vite-Dev-Server ohne weitere Config funktionieren.
    """
    settings = get_settings()
    origins: list[str] = [o.strip().rstrip("/") for o in settings.webauthn_origins.split(",") if o.strip()]
    if not origins and settings.public_url:
        origins = [settings.public_url.rstrip("/")]

    req_origin = (request.headers.get("origin") or "").rstrip("/")
    req_host = _host(req_origin)
    if _is_dev() and req_origin and req_host in _DEV_HOSTS and req_origin not in origins:
        origins.append(req_origin)

    if settings.webauthn_rp_id.strip():
        rp_id = settings.webauthn_rp_id.strip()
    elif _is_dev() and req_host in _DEV_HOSTS:
        rp_id = req_host
    else:
        rp_id = _host(settings.public_url) or "localhost"
    return rp_id, origins


def _deskriptoren(passkeys: list[Passkey]) -> list[PublicKeyCredentialDescriptor]:
    return [PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credential_id)) for p in passkeys]


def registrierungs_optionen(
    request: Request, benutzer_id: int, benutzername: str, name: str, vorhandene: list[Passkey]
) -> tuple[PublicKeyCredentialCreationOptions, str]:
    rp_id, _ = resolve_rp(request)
    optionen = generate_registration_options(
        rp_id=rp_id,
        rp_name=PRODUCT_NAME,
        user_name=benutzername,
        user_id=str(benutzer_id).encode("utf-8"),
        user_display_name=name or benutzername,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=_deskriptoren(vorhandene),
    )
    return optionen, rp_id


def registrierung_pruefen(request: Request, credential: dict, erwartete_challenge: str) -> tuple[str, str, int, str]:
    """Prüft eine Attestation und liefert (credential_id, public_key, sign_count, rp_id)."""
    rp_id, origins = resolve_rp(request)
    ergebnis = verify_registration_response(
        credential=credential,
        expected_challenge=base64url_to_bytes(erwartete_challenge),
        expected_rp_id=rp_id,
        expected_origin=origins,
        require_user_verification=False,
    )
    return (
        bytes_to_base64url(ergebnis.credential_id),
        bytes_to_base64url(ergebnis.credential_public_key),
        int(ergebnis.sign_count),
        rp_id,
    )


# Antwort immer auf dieselbe Mindestgröße auffüllen, damit Unbekannte,
# Konten ohne Passkeys und Konten mit wenigen Passkeys gleich aussehen.
MIN_ANMELDE_DATEN = 3


def anmelde_optionen(
    request: Request, passkeys: list[Passkey]
) -> tuple[PublicKeyCredentialRequestOptions, str]:
    rp_id, _ = resolve_rp(request)
    deskriptoren = _deskriptoren(passkeys)
    while len(deskriptoren) < MIN_ANMELDE_DATEN:
        deskriptoren.append(PublicKeyCredentialDescriptor(id=secrets.token_bytes(64)))
    optionen = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=deskriptoren,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return optionen, rp_id


def anmeldung_pruefen(
    request: Request, credential: dict, erwartete_challenge: str, passkey: Passkey
) -> int:
    """Prüft eine Assertion gegen einen gespeicherten Passkey und liefert den neuen Zähler."""
    rp_id, origins = resolve_rp(request)
    ergebnis = verify_authentication_response(
        credential=credential,
        expected_challenge=base64url_to_bytes(erwartete_challenge),
        expected_rp_id=rp_id,
        expected_origin=origins,
        credential_public_key=base64url_to_bytes(passkey.public_key),
        credential_current_sign_count=passkey.sign_count,
        require_user_verification=False,
    )
    return int(ergebnis.new_sign_count)


def credential_raw_id(credential: dict) -> str:
    roh = credential.get("rawId") or credential.get("id") or ""
    return str(roh)
