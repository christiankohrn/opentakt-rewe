import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.auth import authenticate, benutzer_dict, current_benutzer, write_session
from app.benutzer import benutzer_aktualisieren, benutzer_anlegen, benutzer_loeschen, eigenes_passwort
from app.config import get_settings
from app.db import Base
from app.models import Benutzer
from app.schemas import LoginIn, PasswortIn
from app.seed import seed_if_empty
from app.routes import login, me, passwort_aendern


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


@pytest.fixture()
def admin_pw(monkeypatch):
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


def test_seed_legt_genau_einen_admin_an(session, admin_pw):
    admin = seed_if_empty(session)
    assert admin is not None
    assert admin.benutzername == "admin"
    assert admin.rolle == "admin"
    assert admin.passwort_aendern is True
    assert seed_if_empty(session) is None


def test_seed_verlangt_passwort(session):
    settings = get_settings()
    vorher = (settings.admin_passwort, settings.buchhaltung_password)
    settings.admin_passwort = ""
    settings.buchhaltung_password = ""
    try:
        with pytest.raises(ValueError, match="ADMIN_PASSWORT"):
            seed_if_empty(session)
    finally:
        settings.admin_passwort, settings.buchhaltung_password = vorher


def test_login_und_me_und_passwortwechsel(session, admin_pw):
    request = _request()
    daten = login(LoginIn(benutzername="Admin", password=admin_pw), request, session)
    assert daten["benutzername"] == "admin"
    assert daten["passwort_aendern"] is True
    assert request.session["uid"] == daten["benutzer_id"]
    assert me(request, session)["benutzername"] == "admin"
    with pytest.raises(HTTPException) as exc:
        current_benutzer(request, session)
    assert exc.value.status_code == 403
    geaendert = passwort_aendern(PasswortIn(alt=admin_pw, neu="sicher1234"), request, session)
    assert geaendert["passwort_aendern"] is False
    assert current_benutzer(request, session).benutzername == "admin"
    assert authenticate(session, "admin", "sicher1234") is not None
    assert authenticate(session, "admin", admin_pw) is None


def test_login_falsch(session, admin_pw):
    seed_if_empty(session)
    with pytest.raises(HTTPException) as exc:
        login(LoginIn(benutzername="admin", password="falsch"), _request(), session)
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        login(LoginIn(benutzername="niemand", password=admin_pw), _request(), session)
    assert exc.value.status_code == 401


def test_sitzung_rev_wird_geprueft(session, admin_pw):
    admin = seed_if_empty(session)
    request = _request()
    write_session(request, admin)
    assert current_benutzer(request, session, allow_passwort_aendern=True).benutzer_id == admin.benutzer_id
    admin.session_rev = 99
    with pytest.raises(HTTPException) as exc:
        current_benutzer(request, session, allow_passwort_aendern=True)
    assert exc.value.status_code == 401
    assert request.session == {}
    with pytest.raises(HTTPException) as exc:
        current_benutzer(_request(), session)
    assert exc.value.status_code == 401


def test_benutzer_anlegen_regeln(session, admin_pw):
    admin = seed_if_empty(session)
    neu = benutzer_anlegen(session, "Mit.Arbeiter-1", "Mit", "m@example.org", "geheim123", "benutzer")
    assert neu.passwort_aendern is True
    assert benutzer_dict(neu)["benutzername"] == "mit.arbeiter-1"
    assert "passwort_hash" not in benutzer_dict(neu)
    with pytest.raises(ValueError, match="schon"):
        benutzer_anlegen(session, "MIT.arbeiter-1", "", "", "geheim123", "benutzer")
    with pytest.raises(ValueError, match="Benutzername"):
        benutzer_anlegen(session, "x", "", "", "geheim123", "benutzer")
    with pytest.raises(ValueError, match="mindestens"):
        benutzer_anlegen(session, "kurz", "", "", "123", "benutzer")
    with pytest.raises(ValueError, match="Rolle"):
        benutzer_anlegen(session, "chef", "", "", "geheim123", "chef")
    assert admin.benutzername == "admin"


def test_letzter_admin_ist_geschuetzt(session, admin_pw):
    admin = seed_if_empty(session)
    zweiter = benutzer_anlegen(session, "zweiter", "", "", "geheim123", "admin")
    with pytest.raises(ValueError, match="eigene"):
        benutzer_aktualisieren(session, admin.benutzer_id, admin, rolle="benutzer")
    with pytest.raises(ValueError, match="eigene"):
        benutzer_aktualisieren(session, admin.benutzer_id, admin, aktiv=False)
    with pytest.raises(ValueError, match="eigene"):
        benutzer_loeschen(session, admin.benutzer_id, admin)
    benutzer_aktualisieren(session, zweiter.benutzer_id, admin, rolle="benutzer")
    with pytest.raises(ValueError, match="letzte"):
        benutzer_aktualisieren(session, admin.benutzer_id, zweiter, rolle="benutzer")
    with pytest.raises(ValueError, match="letzte"):
        benutzer_loeschen(session, admin.benutzer_id, zweiter)
    eigenes_passwort(session, zweiter, "geheim123", "neu12345")
    assert zweiter.passwort_aendern is False
    with pytest.raises(ValueError, match="falsch"):
        eigenes_passwort(session, zweiter, "anders", "neu123456")


def test_inaktiver_kann_sich_nicht_anmelden(session, admin_pw):
    admin = seed_if_empty(session)
    assert authenticate(session, "admin", admin_pw) is not None
    admin.aktiv = False
    assert authenticate(session, "admin", admin_pw) is None
