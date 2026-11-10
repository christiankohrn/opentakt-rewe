"""Einladungen und Passwort-Resets mit gefälschtem SMTP."""

import re
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.benutzer import benutzer_anlegen
from app.config import get_settings
from app.db import Base
from app.models import AuditEreignis, Benutzer, MailToken
from app.ratelimit import reset as ratelimit_reset
from app.routes import (
    benutzer_neu,
    benutzer_zugangsmail,
    login,
    passwort_token_einloesen,
    passwort_token_info,
    passwort_vergessen,
)
from app.schemas import BenutzerNeuIn, LoginIn, TokenSetzenIn, VergessenIn
from app.seed import seed_if_empty
from app.zeit import utcnow
from app.zugangsmail import zugangstoken_erstellen, zugangstoken_suchen


class FakeSMTP:
    outbox: list = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        FakeSMTP.outbox.append(msg)


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
def mail(monkeypatch):
    import smtplib

    FakeSMTP.outbox = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    settings = get_settings()
    vorher = (
        settings.smtp_host, settings.smtp_port, settings.smtp_from,
        settings.smtp_user, settings.smtp_password, settings.smtp_tls,
        settings.public_url, settings.admin_passwort, settings.buchhaltung_password,
    )
    settings.smtp_host = "mail.test"
    settings.smtp_port = 587
    settings.smtp_from = "noreply@test.local"
    settings.smtp_user = ""
    settings.smtp_password = ""
    settings.smtp_tls = False
    settings.public_url = "https://rewe.test"
    settings.admin_passwort = "anfang123"
    settings.buchhaltung_password = ""
    try:
        yield FakeSMTP.outbox
    finally:
        (settings.smtp_host, settings.smtp_port, settings.smtp_from,
         settings.smtp_user, settings.smtp_password, settings.smtp_tls,
         settings.public_url, settings.admin_passwort, settings.buchhaltung_password) = vorher


def _request(sitzung=None):
    return Request({"type": "http", "headers": [], "session": dict(sitzung or {})})


def _token_aus_mail(msg) -> str:
    text = msg.get_body(preferencelist=("plain",)).get_content()
    treffer = re.search(r"token=([A-Za-z0-9_-]+)", text)
    assert treffer
    return treffer.group(1)


def test_token_lebenszyklus(session, mail):
    nutzer = benutzer_anlegen(session, "token", "", "t@example.org", "geheim123", "benutzer")
    roh = zugangstoken_erstellen(session, nutzer, "reset")
    assert zugangstoken_suchen(session, roh) is not None
    # Neuer Token entwertet den alten
    neu = zugangstoken_erstellen(session, nutzer, "reset")
    assert zugangstoken_suchen(session, roh) is None
    assert zugangstoken_suchen(session, neu) is not None
    zeile = session.scalar(select(MailToken).where(MailToken.benutzer_id == nutzer.benutzer_id))
    zeile.laeuft_ab = utcnow() - timedelta(seconds=1)
    assert zugangstoken_suchen(session, neu) is None
    assert zugangstoken_suchen(session, "x" * 300) is None


def test_vergessen_verraet_nichts_und_drosselt(session, mail):
    assert passwort_vergessen(VergessenIn(kennung="niemand"), _request(), session) == {"ok": True}
    assert mail == []
    ohne_mail = benutzer_anlegen(session, "ohnemail", "", "", "geheim123", "benutzer")
    ohne_mail.passwort_aendern = False
    assert passwort_vergessen(VergessenIn(kennung="ohnemail"), _request(), session) == {"ok": True}
    assert mail == []

    nutzer = benutzer_anlegen(session, "reset", "", "r@example.org", "geheim123", "benutzer")
    nutzer.passwort_aendern = False
    assert passwort_vergessen(VergessenIn(kennung="R@example.org"), _request(), session) == {"ok": True}
    assert len(mail) == 1
    assert mail[0]["To"] == "r@example.org"
    assert "https://rewe.test/passwort-setzen?token=" in mail[0].get_body(preferencelist=("plain",)).get_content()
    # Zweite Anfrage im Fenster schickt nichts Neues
    assert passwort_vergessen(VergessenIn(kennung="reset"), _request(), session) == {"ok": True}
    assert len(mail) == 1

    token = _token_aus_mail(mail[0])
    info = passwort_token_info(token, _request(), session)
    assert info == {"benutzername": "reset", "name": "", "zweck": "reset"}
    assert passwort_token_einloesen(TokenSetzenIn(token=token, passwort="neu12345"), _request(), session) == {"ok": True}
    daten = login(LoginIn(benutzername="reset", password="neu12345"), _request(), session)
    assert daten["passwort_aendern"] is False
    with pytest.raises(HTTPException) as exc:
        passwort_token_einloesen(TokenSetzenIn(token=token, passwort="neu123456"), _request(), session)
    assert exc.value.status_code == 400


def test_einladung_bei_anlage(session, mail):
    admin = seed_if_empty(session)
    admin.passwort_aendern = False
    antwort = benutzer_neu(
        BenutzerNeuIn(benutzername="neu", name="Neu", email="neu@example.org", rolle="benutzer", einladung=True),
        admin,
        session,
    )
    assert antwort["mail_gesendet"] is True
    assert antwort["mail_fehler"] is None
    assert len(mail) == 1
    assert "Zugang einrichten" in mail[0]["Subject"]
    token = _token_aus_mail(mail[0])
    assert passwort_token_info(token, _request(), session)["zweck"] == "einladung"
    assert passwort_token_einloesen(TokenSetzenIn(token=token, passwort="start1234"), _request(), session) == {"ok": True}
    assert login(LoginIn(benutzername="neu", password="start1234"), _request(), session)["benutzername"] == "neu"

    aktionen = [z.aktion for z in session.scalars(select(AuditEreignis).order_by(AuditEreignis.ereignis_id))]
    assert "benutzer.anlegen" in aktionen
    assert "benutzer.einladung" in aktionen
    assert "passwort.einladung" in aktionen


def test_einladung_braucht_mail_und_lokales_konto(session, mail):
    admin = seed_if_empty(session)
    admin.passwort_aendern = False
    nutzer = benutzer_anlegen(session, "nomail", "", "", "geheim123", "benutzer")
    with pytest.raises(HTTPException) as exc:
        benutzer_zugangsmail(nutzer.benutzer_id, admin, session)
    assert exc.value.status_code == 400
    nutzer.auth_quelle = "ldap"
    nutzer.email = "ldap@example.org"
    with pytest.raises(HTTPException) as exc:
        benutzer_zugangsmail(nutzer.benutzer_id, admin, session)
    assert "Benutzerverzeichnis" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        benutzer_zugangsmail(9999, admin, session)
    assert exc.value.status_code == 404


def test_kurzes_passwort_wird_abgelehnt(session, mail):
    nutzer = benutzer_anlegen(session, "kurz", "", "k@example.org", "geheim123", "benutzer")
    nutzer.passwort_aendern = False
    roh = zugangstoken_erstellen(session, nutzer, "reset")
    with pytest.raises(HTTPException) as exc:
        passwort_token_einloesen(TokenSetzenIn(token=roh, passwort="kurz"), _request(), session)
    assert exc.value.status_code == 400
    assert isinstance(nutzer, Benutzer)
