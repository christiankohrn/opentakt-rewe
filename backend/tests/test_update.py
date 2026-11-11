import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.config import get_settings
from app.db import Base
from app.models import AuditEreignis, Benutzer
from app.security import hash_password
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


@pytest.fixture()
def daten_tmp(tmp_path, monkeypatch):
    import app.aktualisierung as akt

    settings = get_settings()
    monkeypatch.setattr(settings, "beleg_ordner", str(tmp_path / "belege"))
    monkeypatch.setattr(akt, "UPDATE_ANFRAGE_ORDNER", tmp_path)
    return tmp_path


def test_daten_ordner_lokal(tmp_path, monkeypatch):
    import app.aktualisierung as akt

    from pathlib import Path

    settings = get_settings()
    monkeypatch.setattr(settings, "beleg_ordner", "belege-test")
    monkeypatch.setattr(akt, "UPDATE_ANFRAGE_ORDNER", tmp_path / "server")
    assert akt.daten_ordner(settings) == Path.cwd() / "data"


def _request(sitzung=None):
    return Request({"type": "http", "headers": [], "session": dict(sitzung or {})})


def _admin(session, admin_pw):
    admin = seed_if_empty(session)
    assert admin is not None
    admin.passwort_aendern = False
    session.commit()
    return admin


def _benutzer(session, name="berta"):
    benutzer = Benutzer(
        benutzername=name,
        name=name,
        email=None,
        passwort_hash=hash_password("geheim123"),
        rolle="benutzer",
        aktiv=True,
    )
    session.add(benutzer)
    session.commit()
    return benutzer


def test_update_braucht_admin(session, admin_pw):
    from app.auth import require_admin

    admin = _admin(session, admin_pw)
    benutzer = _benutzer(session)
    with pytest.raises(HTTPException) as anonym:
        require_admin(_request(), session)
    assert anonym.value.status_code == 401
    with pytest.raises(HTTPException) as fremd:
        require_admin(_request({"uid": benutzer.benutzer_id, "rev": 0}), session)
    assert fremd.value.status_code == 403
    assert require_admin(_request({"uid": admin.benutzer_id, "rev": 0}), session).rolle == "admin"


def test_status_meldet_version_und_lokal_nicht_unterstuetzt(session, admin_pw):
    from app.aktualisierung import update_status
    from app.branding import APP_VERSION

    admin = _admin(session, admin_pw)
    antwort = update_status(admin)
    assert antwort["installiert"]["version"] == APP_VERSION
    assert antwort["unterstuetzt"] is False
    assert antwort["grund"]
    assert antwort["quelle"]["branch"] == "main"
    assert "github.com" in antwort["quelle"]["url"]


def test_status_schreiben_legt_ordner_an(tmp_path, monkeypatch):
    import app.aktualisierung as akt

    monkeypatch.setattr(akt, "daten_ordner", lambda settings=None: tmp_path / "neu" / "daten")
    geschrieben = akt.status_schreiben({"letzte_pruefung": "x"})
    assert geschrieben["letzte_pruefung"] == "x"
    assert (tmp_path / "neu" / "daten" / "update-status.json").is_file()


def test_check_speichert_remote_stand(session, admin_pw, daten_tmp, monkeypatch):
    import app.aktualisierung as akt

    admin = _admin(session, admin_pw)
    kopf = {
        "sha": "feedface" * 5,
        "html_url": "https://github.com/x/y/commit/feedface",
        "commit": {"message": "Neu: Update-Knopf\n\nDetails", "committer": {"date": "2026-11-10T10:00:00Z"}},
    }
    vergleich = {"status": "behind", "behind_by": 3, "ahead_by": 0}

    def fake_laden(url, settings):
        if url.endswith("/commits/main"):
            return kopf
        assert "/compare/" in url
        return vergleich

    monkeypatch.setattr(akt, "json_laden", fake_laden)
    monkeypatch.setattr(akt, "installations_stand", lambda: {"version": "0.1.0", "commit": "a" * 40})

    antwort = akt.update_check(admin)
    assert antwort["remote"]["commit"] == kopf["sha"]
    assert antwort["remote"]["nachricht"] == "Neu: Update-Knopf"
    assert antwort["vergleich"] == "dahinter"
    assert antwort["dahinter"] == 3
    assert antwort["letzte_pruefung"]

    gepuffert = akt.update_status(admin)
    assert gepuffert["remote"]["commit"] == kopf["sha"]
    assert gepuffert["vergleich"] == "dahinter"


def test_check_ohne_lokalen_commit_ist_unbekannt(session, admin_pw, daten_tmp, monkeypatch):
    import app.aktualisierung as akt

    admin = _admin(session, admin_pw)
    kopf = {
        "sha": "b" * 40,
        "html_url": "https://github.com/x/y/commit/b",
        "commit": {"message": "Irgendwas", "committer": {"date": "2026-11-10T10:00:00Z"}},
    }
    aufrufe = []

    def fake_laden(url, settings):
        aufrufe.append(url)
        return kopf

    monkeypatch.setattr(akt, "json_laden", fake_laden)
    monkeypatch.setattr(akt, "installations_stand", lambda: {"version": "0.1.0", "commit": None})

    antwort = akt.update_check(admin)
    assert antwort["vergleich"] == "unbekannt"
    assert antwort["remote"]["commit"] == "b" * 40
    assert len(aufrufe) == 1


def test_check_github_fehler_ist_502(session, admin_pw, daten_tmp, monkeypatch):
    import app.aktualisierung as akt

    admin = _admin(session, admin_pw)

    def kaputt(url, settings):
        raise akt.UpdateFehler("GitHub ist nicht erreichbar. Netzwerk prüfen.")

    monkeypatch.setattr(akt, "json_laden", kaputt)
    with pytest.raises(HTTPException) as exc:
        akt.update_check(admin)
    assert exc.value.status_code == 502
    assert "GitHub" in exc.value.detail


def test_apply_ohne_server_layout_409(session, admin_pw, daten_tmp):
    import app.aktualisierung as akt

    admin = _admin(session, admin_pw)
    with pytest.raises(HTTPException) as exc:
        akt.update_apply(admin, session)
    assert exc.value.status_code == 409
    assert "Server" in exc.value.detail


def test_apply_schreibt_anfrage_und_sperrt(session, admin_pw, daten_tmp, monkeypatch):
    import app.aktualisierung as akt

    admin = _admin(session, admin_pw)
    monkeypatch.setattr(akt, "update_unterstuetzt", lambda settings=None: (True, None))
    monkeypatch.setattr(akt, "installations_stand", lambda: {"version": "0.1.0", "commit": "c" * 40})

    antwort = akt.update_apply(admin, session)
    assert antwort["update"]["zustand"] == "running"

    anfrage = daten_tmp / "update.request"
    assert anfrage.is_file()
    inhalt = json.loads(anfrage.read_text(encoding="utf-8"))
    assert inhalt["gestartet_von"] == "admin"
    ereignis = session.scalar(select(AuditEreignis).where(AuditEreignis.aktion == "update.apply"))
    assert ereignis is not None

    with pytest.raises(HTTPException) as exc:
        akt.update_apply(admin, session)
    assert exc.value.status_code == 409


def test_unterstuetzt_mit_server_layout(tmp_path, monkeypatch):
    import app.aktualisierung as akt
    from app.config import get_settings

    settings = get_settings()
    stamm = tmp_path / "app"
    (stamm / "deploy").mkdir(parents=True)
    (stamm / "deploy" / "update.sh").touch()
    unit = tmp_path / "buchhaltung-update.path"
    unit.touch()
    monkeypatch.setattr(akt, "app_stamm", lambda: stamm)
    monkeypatch.setattr(akt, "UPDATE_UNIT_PFAD", unit)
    monkeypatch.setattr(akt, "UPDATE_ANFRAGE_ORDNER", tmp_path)
    monkeypatch.setattr(settings, "beleg_ordner", str(tmp_path / "belege"))
    assert akt.update_unterstuetzt(settings) == (True, None)

    woanders = tmp_path / "anderswo"
    woanders.mkdir()
    monkeypatch.setattr(akt, "UPDATE_ANFRAGE_ORDNER", woanders)
    unterstuetzt, grund = akt.update_unterstuetzt(settings)
    assert unterstuetzt is False
    assert "Server" in (grund or "")
