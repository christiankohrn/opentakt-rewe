"""LDAP-Anmeldung mit gefälschtem ldap3 (kein Server nötig)."""

import sys
import types

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.auth import authenticate
from app.config import get_settings
from app.db import Base
from app.models import Benutzer
from app.benutzer import benutzer_anlegen


class FakeEntry:
    def __init__(self, dn, attrs):
        self.distinguishedName = dn
        self._attrs = attrs

    def __contains__(self, key):
        return key in self._attrs

    def __getitem__(self, key):
        return self._attrs[key]

    def __getattr__(self, key):
        if key.startswith("_"):
            raise AttributeError(key)
        try:
            return self.__dict__["_attrs"][key]
        except KeyError:
            raise AttributeError(key) from None


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
def ldap(monkeypatch):
    calls: dict = {"binds": [], "searches": []}
    entries: list = []

    class FakeConnection:
        def __init__(self, server, auto_bind=False, user=None, password=None, **_kwargs):
            self.server = server
            self.user = user
            self.password = password
            self.entries = entries
            if auto_bind:
                self.bind()

        def bind(self):
            calls["binds"].append((self.user, self.password))
            return self.password == "ldap-geheim"

        def search(self, base, search_filter, attributes=None):
            calls["searches"].append(search_filter)
            return True

        def unbind(self):
            return True

    fake = types.ModuleType("ldap3")
    fake.ALL = "all"
    fake.Connection = FakeConnection
    fake.Server = lambda *args, **kwargs: ("server", args, kwargs)
    conv = types.ModuleType("ldap3.utils.conv")

    def _escape(value: str) -> str:
        return value.replace("\\", "\\5c").replace("*", "\\2a").replace("(", "\\28").replace(")", "\\29")

    conv.escape_filter_chars = _escape
    utils = types.ModuleType("ldap3.utils")
    utils.conv = conv
    fake.utils = utils
    monkeypatch.setitem(sys.modules, "ldap3", fake)
    monkeypatch.setitem(sys.modules, "ldap3.utils", utils)
    monkeypatch.setitem(sys.modules, "ldap3.utils.conv", conv)

    settings = get_settings()
    vorher = (
        settings.ldap_enabled, settings.ldap_url, settings.ldap_bind_dn,
        settings.ldap_bind_password, settings.ldap_user_base, settings.ldap_user_filter,
    )
    settings.ldap_enabled = True
    settings.ldap_url = "ldap://test.local"
    settings.ldap_bind_dn = ""
    settings.ldap_bind_password = ""
    settings.ldap_user_base = "ou=users,dc=test,dc=local"
    settings.ldap_user_filter = "(sAMAccountName={username})"
    try:
        yield {"calls": calls, "entries": entries, "settings": settings}
    finally:
        (settings.ldap_enabled, settings.ldap_url, settings.ldap_bind_dn,
         settings.ldap_bind_password, settings.ldap_user_base, settings.ldap_user_filter) = vorher


def _eintrag(name="Ldap Nutzer", mail="ldap@example.org"):
    return FakeEntry(
        f"cn={name},ou=users,dc=test,dc=local",
        {"displayName": name, "mail": mail, "distinguishedName": f"cn={name}"},
    )


def test_neuer_ldap_nutzer_wird_angelegt(session, ldap):
    ldap["entries"].append(_eintrag())
    benutzer = authenticate(session, "ldapnutzer", "ldap-geheim")
    assert benutzer is not None
    assert benutzer.auth_quelle == "ldap"
    assert benutzer.rolle == "benutzer"
    assert benutzer.name == "Ldap Nutzer"
    assert benutzer.email == "ldap@example.org"
    assert authenticate(session, "ldapnutzer", "falsch") is None


def test_filter_wird_escapet(session, ldap):
    ldap["entries"].append(_eintrag())
    assert authenticate(session, "*)(uid=*", "ldap-geheim") is not None
    assert ldap["calls"]["searches"] == ["(sAMAccountName=\\2a\\29\\28uid=\\2a)"]


def test_inaktiver_wird_abgelehnt(session, ldap):
    benutzer = benutzer_anlegen(session, "kartei", "Kartei", "", "geheim123", "benutzer")
    benutzer.auth_quelle = "ldap"
    benutzer.aktiv = False
    ldap["entries"].append(_eintrag("Kartei"))
    assert authenticate(session, "kartei", "ldap-geheim") is None


def test_ausgeschaltet_kein_ldap(session, ldap):
    ldap["settings"].ldap_enabled = False
    ldap["entries"].append(_eintrag())
    assert authenticate(session, "neu", "ldap-geheim") is None


def test_lokales_passwort_geht_vor(session, ldap):
    benutzer_anlegen(session, "lokal", "Lokal", "", "geheim123", "benutzer")
    ldap["entries"].append(_eintrag("Lokal"))
    gefunden = authenticate(session, "lokal", "geheim123")
    assert gefunden is not None
    assert gefunden.auth_quelle == "local"
    assert isinstance(gefunden, Benutzer)
