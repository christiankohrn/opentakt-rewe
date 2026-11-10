import pyotp
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.auth import write_session
from app.benutzer import benutzer_anlegen
from app.config import get_settings
from app.db import Base
from app.models import AuditEreignis, Benutzer
from app.ratelimit import reset as ratelimit_reset
from app.routes import (
    login,
    mfa,
    sicherheit_status,
    totp_aktivieren,
    totp_backup_neu,
    totp_deaktivieren,
    totp_einrichten,
)
from app.schemas import LoginIn, MfaIn, TotpAktivierenIn, TotpDeaktivierenIn


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
def admin_pw():
    settings = get_settings()
    vorher = (settings.admin_benutzer, settings.admin_passwort, settings.buchhaltung_password)
    settings.admin_benutzer = "admin"
    settings.admin_passwort = "anfang123"
    settings.buchhaltung_password = ""
    try:
        yield "anfang123"
    finally:
        settings.admin_benutzer, settings.admin_passwort, settings.buchhaltung_password = vorher


def _request(sitzung=None):
    return Request({"type": "http", "headers": [], "session": dict(sitzung or {})})


def _angemeldet(session, benutzer):
    benutzer.passwort_aendern = False
    session.flush()
    request = _request()
    write_session(request, benutzer)
    return request


def test_totp_einrichten_aktivieren_und_login(session, admin_pw):
    nutzer = benutzer_anlegen(session, "mfa", "Mfa", "", "geheim123", "benutzer")
    request = _angemeldet(session, nutzer)

    start = totp_einrichten(request, session)
    assert start["otpauth_uri"].startswith("otpauth://totp/")
    assert start["qr_svg"].startswith("data:image/svg+xml;base64,")
    assert sicherheit_status(request, session)["totp_aktiv"] is False

    with pytest.raises(HTTPException) as exc:
        totp_aktivieren(TotpAktivierenIn(code="000000"), request, session)
    assert exc.value.status_code == 400

    codes = totp_aktivieren(TotpAktivierenIn(code=pyotp.TOTP(start["secret"]).now()), request, session)[
        "backup_codes"
    ]
    assert len(codes) == 10
    assert all(len(code) == 11 and code[5] == "-" for code in codes)
    status = sicherheit_status(request, session)
    assert status["totp_aktiv"] is True
    assert status["backup_codes_uebrig"] == 10

    # Login verlangt jetzt den zweiten Faktor
    anfrage = _request()
    antwort = login(LoginIn(benutzername="mfa", password="geheim123"), anfrage, session)
    assert antwort["mfa_erforderlich"] is True
    assert set(antwort["methoden"]) == {"totp", "backup_code"}
    assert "uid" not in anfrage.session

    with pytest.raises(HTTPException) as exc:
        mfa(MfaIn(code="000000"), anfrage, session)
    assert exc.value.status_code == 401

    daten = mfa(MfaIn(code=pyotp.TOTP(start["secret"]).now()), anfrage, session)
    assert daten["benutzername"] == "mfa"
    assert anfrage.session["uid"] == nutzer.benutzer_id

    aktionen = [z.aktion for z in session.scalars(select(AuditEreignis).order_by(AuditEreignis.ereignis_id))]
    assert "totp.aktivieren" in aktionen
    assert "anmeldung" in aktionen


def test_backup_code_nur_einmal(session, admin_pw):
    nutzer = benutzer_anlegen(session, "backup", "", "", "geheim123", "benutzer")
    request = _angemeldet(session, nutzer)
    start = totp_einrichten(request, session)
    codes = totp_aktivieren(TotpAktivierenIn(code=pyotp.TOTP(start["secret"]).now()), request, session)[
        "backup_codes"
    ]

    anfrage = _request()
    login(LoginIn(benutzername="backup", password="geheim123"), anfrage, session)
    mfa(MfaIn(code=codes[0].lower().replace("-", "")), anfrage, session)
    assert sicherheit_status(_angemeldet(session, nutzer), session)["backup_codes_uebrig"] == 9

    erneut = _request()
    login(LoginIn(benutzername="backup", password="geheim123"), erneut, session)
    with pytest.raises(HTTPException):
        mfa(MfaIn(code=codes[0]), erneut, session)

    neu = totp_backup_neu(MfaIn(code=pyotp.TOTP(start["secret"]).now()), _angemeldet(session, nutzer), session)[
        "backup_codes"
    ]
    assert neu != codes
    assert sicherheit_status(_angemeldet(session, nutzer), session)["backup_codes_uebrig"] == 10


def test_deaktivieren_braucht_passwort_und_code(session, admin_pw):
    nutzer = benutzer_anlegen(session, "weg", "", "", "geheim123", "benutzer")
    request = _angemeldet(session, nutzer)
    start = totp_einrichten(request, session)
    totp_aktivieren(TotpAktivierenIn(code=pyotp.TOTP(start["secret"]).now()), request, session)

    with pytest.raises(HTTPException) as exc:
        totp_deaktivieren(TotpDeaktivierenIn(passwort="falsch", code="000000"), request, session)
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException):
        totp_deaktivieren(TotpDeaktivierenIn(passwort="geheim123", code="000000"), request, session)

    assert totp_deaktivieren(
        TotpDeaktivierenIn(passwort="geheim123", code=pyotp.TOTP(start["secret"]).now()), request, session
    ) == {"ok": True}
    assert sicherheit_status(request, session)["totp_aktiv"] is False

    # Login wieder ohne zweiten Faktor
    anfrage = _request()
    daten = login(LoginIn(benutzername="weg", password="geheim123"), anfrage, session)
    assert daten["benutzername"] == "weg"


def test_mfa_session_laeuft_ab(session, admin_pw):
    nutzer = benutzer_anlegen(session, "ablauf", "", "", "geheim123", "benutzer")
    request = _angemeldet(session, nutzer)
    start = totp_einrichten(request, session)
    totp_aktivieren(TotpAktivierenIn(code=pyotp.TOTP(start["secret"]).now()), request, session)

    anfrage = _request()
    login(LoginIn(benutzername="ablauf", password="geheim123"), anfrage, session)
    anfrage.session["pending_mfa"]["exp"] = 1
    with pytest.raises(HTTPException) as exc:
        mfa(MfaIn(code=pyotp.TOTP(start["secret"]).now()), anfrage, session)
    assert exc.value.status_code == 401
    assert anfrage.session == {}
