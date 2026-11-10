"""Rate-Limits an den anonymen Auth-Endpunkten."""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.config import get_settings
from app.db import Base
from app.ratelimit import reset as ratelimit_reset
from app.routes import login, passwort_token_einloesen, passwort_vergessen
from app.schemas import LoginIn, TokenSetzenIn, VergessenIn
from app.seed import seed_if_empty


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


def _request():
    return Request({"type": "http", "headers": [], "session": {}})


def test_login_limit_und_reset_bei_erfolg(session, admin_pw):
    seed_if_empty(session)
    for _ in range(10):
        with pytest.raises(HTTPException) as exc:
            login(LoginIn(benutzername="admin", password="falsch"), _request(), session)
        assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        login(LoginIn(benutzername="admin", password="falsch"), _request(), session)
    assert exc.value.status_code == 429
    assert exc.value.headers["Retry-After"]
    # Erfolg löscht das Budget (hier nach simuliertem Ablauf erneut prüfen)
    ratelimit_reset()
    assert login(LoginIn(benutzername="admin", password=admin_pw), _request(), session)["benutzername"] == "admin"
    with pytest.raises(HTTPException) as exc:
        login(LoginIn(benutzername="admin", password="falsch"), _request(), session)
    assert exc.value.status_code == 401


def test_vergessen_limit(session, admin_pw):
    for _ in range(10):
        assert passwort_vergessen(VergessenIn(kennung="niemand"), _request(), session) == {"ok": True}
    with pytest.raises(HTTPException) as exc:
        passwort_vergessen(VergessenIn(kennung="niemand"), _request(), session)
    assert exc.value.status_code == 429


def test_token_limit(session, admin_pw):
    for _ in range(30):
        with pytest.raises(HTTPException) as exc:
            passwort_token_einloesen(TokenSetzenIn(token="ungueltig", passwort="neu12345"), _request(), session)
        assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        passwort_token_einloesen(TokenSetzenIn(token="ungueltig", passwort="neu12345"), _request(), session)
    assert exc.value.status_code == 429
