"""Passkeys Ende-zu-Ende mit einem Software-Authenticator (wie opentakt-zeit)."""

import hashlib
import json
import struct

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from app.auth import write_session
from app.benutzer import benutzer_anlegen
from app.config import get_settings
from app.db import Base
from app.models import AuditEreignis
from app.ratelimit import reset as ratelimit_reset
from app.routes import (
    passkey_liste,
    passkey_loeschen,
    passkey_optionen,
    passkey_registrieren_optionen,
    passkey_registrieren_verifizieren,
    passkey_umbenennen,
    passkey_verifizieren,
    sicherheit_status,
)
from app.schemas import PasskeyOptionenIn, PasskeyRegistrierenIn, PasskeyUmbenennenIn, PasskeyVerifyIn

ORIGIN = "http://test.local"
RP_ID = "test.local"


class RegistrationCredential:
    def __init__(self, credential_id: bytes, client_data: bytes, attestation: bytes):
        self.credential_id = credential_id
        self.client_data = client_data
        self.attestation = attestation

    def as_dict(self) -> dict:
        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(self.client_data),
                "attestationObject": bytes_to_base64url(self.attestation),
            },
            "clientExtensionResults": {},
        }


class AuthenticationCredential:
    def __init__(self, credential_id: bytes, client_data: bytes, auth_data: bytes, signature: bytes):
        self.credential_id = credential_id
        self.client_data = client_data
        self.auth_data = auth_data
        self.signature = signature

    def as_dict(self) -> dict:
        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(self.client_data),
                "authenticatorData": bytes_to_base64url(self.auth_data),
                "signature": bytes_to_base64url(self.signature),
                "userHandle": None,
            },
            "clientExtensionResults": {},
        }


class SoftAuthenticator:
    def __init__(self) -> None:
        self._key = ec.generate_private_key(ec.SECP256R1())
        self._credential_id = b"test-credential-id-001"
        self.sign_count = 0

    def _cose_key(self) -> bytes:
        numbers = self._key.public_key().public_numbers()
        return cbor2.dumps(
            {
                1: 2,
                3: -7,
                -1: 1,
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )

    def _sign(self, payload: bytes) -> bytes:
        return self._key.sign(payload, ec.ECDSA(hashes.SHA256()))

    def create(self, options: dict) -> dict:
        challenge = options["challenge"]
        client_data = json.dumps(
            {"type": "webauthn.create", "challenge": challenge, "origin": ORIGIN}
        ).encode()
        rp_hash = hashlib.sha256(RP_ID.encode()).digest()
        auth_data = (
            rp_hash
            + b"\x45"
            + struct.pack(">I", 0)
            + b"\x00" * 16
            + struct.pack(">H", len(self._credential_id))
            + self._credential_id
            + self._cose_key()
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return RegistrationCredential(self._credential_id, client_data, attestation).as_dict()

    def authenticate(self, options: dict, credential_id: bytes | None = None) -> dict:
        challenge = options["challenge"]
        client_data = json.dumps(
            {"type": "webauthn.get", "challenge": challenge, "origin": ORIGIN}
        ).encode()
        self.sign_count += 1
        rp_hash = hashlib.sha256(RP_ID.encode()).digest()
        auth_data = rp_hash + b"\x05" + struct.pack(">I", self.sign_count)
        signature = self._sign(auth_data + hashlib.sha256(client_data).digest())
        return AuthenticationCredential(credential_id or self._credential_id, client_data, auth_data, signature).as_dict()


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", future=True)

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as db:
        yield db


@pytest.fixture(autouse=True)
def _ratelimit():
    ratelimit_reset()
    yield
    ratelimit_reset()


@pytest.fixture()
def test_url():
    settings = get_settings()
    vorher = (settings.public_url, settings.webauthn_rp_id, settings.webauthn_origins)
    settings.public_url = ORIGIN
    settings.webauthn_rp_id = ""
    settings.webauthn_origins = ""
    try:
        yield ORIGIN
    finally:
        settings.public_url, settings.webauthn_rp_id, settings.webauthn_origins = vorher


def _request(sitzung=None):
    return Request({"type": "http", "headers": [], "session": dict(sitzung or {})})


def _angemeldet(session, benutzer):
    benutzer.passwort_aendern = False
    session.flush()
    request = _request()
    write_session(request, benutzer)
    return request


def test_passkey_registrieren_verwalten_und_anmelden(session, test_url):
    nutzer = benutzer_anlegen(session, "key", "Key", "", "geheim123", "benutzer")
    request = _angemeldet(session, nutzer)
    auth = SoftAuthenticator()

    optionen = passkey_registrieren_optionen(request, session)
    assert optionen["rp"]["id"] == RP_ID
    registriert = passkey_registrieren_verifizieren(
        PasskeyRegistrierenIn(credential=auth.create(optionen), name="Mein Key"), request, session
    )
    assert registriert["name"] == "Mein Key"
    assert [p["passkey_id"] for p in passkey_liste(request, session)] == [registriert["passkey_id"]]
    assert sicherheit_status(request, session)["passkeys"][0]["name"] == "Mein Key"

    umbenannt = passkey_umbenennen(
        registriert["passkey_id"], PasskeyUmbenennenIn(name="Neu"), request, session
    )
    assert umbenannt["name"] == "Neu"

    # Doppelte Registrierung desselben Keys wird abgelehnt
    optionen2 = passkey_registrieren_optionen(request, session)
    with pytest.raises(HTTPException) as exc:
        passkey_registrieren_verifizieren(
            PasskeyRegistrierenIn(credential=auth.create(optionen2)), request, session
        )
    assert exc.value.status_code == 400

    # Anmeldung mit Passkey (Discoverable Credential: allowCredentials leer, funktioniert mit & ohne Benutzername)
    anfrage = _request()
    login_optionen = passkey_optionen(PasskeyOptionenIn(benutzername=""), anfrage, session)
    assert login_optionen["rpId"] == RP_ID
    assert login_optionen["allowCredentials"] == []
    daten = passkey_verifizieren(
        PasskeyVerifyIn(credential=auth.authenticate(login_optionen)), anfrage, session
    )
    assert daten["benutzername"] == "key"
    assert anfrage.session["uid"] == nutzer.benutzer_id

    passkey_loeschen(registriert["passkey_id"], _angemeldet(session, nutzer), session)
    assert passkey_liste(_angemeldet(session, nutzer), session) == []
    with pytest.raises(HTTPException) as exc:
        passkey_loeschen(registriert["passkey_id"], _angemeldet(session, nutzer), session)
    assert exc.value.status_code == 404

    aktionen = [z.aktion for z in session.scalars(select(AuditEreignis).order_by(AuditEreignis.ereignis_id))]
    assert "passkey.registrieren" in aktionen
    assert "passkey.loeschen" in aktionen
    assert "anmeldung" in aktionen


def test_optionen_verraten_kein_konto(session, test_url):
    leer = passkey_optionen(PasskeyOptionenIn(benutzername=""), _request(), session)
    unbekannt = passkey_optionen(PasskeyOptionenIn(benutzername="niemand"), _request(), session)
    nutzer = benutzer_anlegen(session, "ohne", "", "", "geheim123", "benutzer")
    nutzer.passwort_aendern = False
    bekannt = passkey_optionen(PasskeyOptionenIn(benutzername="ohne"), _request(), session)
    assert leer["allowCredentials"] == []
    assert unbekannt["allowCredentials"] == []
    assert bekannt["allowCredentials"] == []


def test_synced_passkey_wie_1password_mit_backup_flags_und_sign_count_null(session, test_url):
    nutzer = benutzer_anlegen(session, "sync", "Sync", "", "geheim123", "admin")
    request = _angemeldet(session, nutzer)
    auth = SoftAuthenticator()

    optionen = passkey_registrieren_optionen(request, session)
    assert optionen["authenticatorSelection"]["residentKey"] == "required"
    reg_cred = auth.create(optionen)
    reg_cred["response"]["transports"] = ["internal", "hybrid"]
    passkey_registrieren_verifizieren(
        PasskeyRegistrierenIn(credential=reg_cred, name="1Password"), request, session
    )

    # 2. Registrierungs-Optionen enthalten gespeicherte Transports in excludeCredentials
    optionen_folge = passkey_registrieren_optionen(request, session)
    assert optionen_folge["excludeCredentials"][0]["transports"] == ["internal", "hybrid"]

    # 1Password-typische Assertion: Backup-Flags (UP|UV|BE|BS = 0x1D), sign_count = 0, userHandle gesetzt
    anfrage = _request()
    login_opt = passkey_optionen(PasskeyOptionenIn(benutzername=""), anfrage, session)
    client_data = json.dumps(
        {"type": "webauthn.get", "challenge": login_opt["challenge"], "origin": ORIGIN}
    ).encode()
    rp_hash = hashlib.sha256(RP_ID.encode()).digest()
    auth_data = rp_hash + b"\x1d" + struct.pack(">I", 0)
    sig = auth._sign(auth_data + hashlib.sha256(client_data).digest())
    cred = AuthenticationCredential(auth._credential_id, client_data, auth_data, sig).as_dict()
    cred["response"]["userHandle"] = bytes_to_base64url(str(nutzer.benutzer_id).encode())

    daten = passkey_verifizieren(PasskeyVerifyIn(credential=cred), anfrage, session)
    assert daten["benutzername"] == "sync"


def test_fremder_passkey_wird_abgelehnt(session, test_url):
    nutzer = benutzer_anlegen(session, "echt", "", "", "geheim123", "benutzer")
    request = _angemeldet(session, nutzer)
    auth = SoftAuthenticator()
    optionen = passkey_registrieren_optionen(request, session)
    passkey_registrieren_verifizieren(PasskeyRegistrierenIn(credential=auth.create(optionen)), request, session)

    anfrage = _request()
    login_optionen = passkey_optionen(PasskeyOptionenIn(benutzername="echt"), anfrage, session)
    fremd = SoftAuthenticator()
    with pytest.raises(HTTPException) as exc:
        passkey_verifizieren(PasskeyVerifyIn(credential=fremd.authenticate(login_optionen)), anfrage, session)
    assert exc.value.status_code == 401
    assert base64url_to_bytes(login_optionen["challenge"]) is not None
