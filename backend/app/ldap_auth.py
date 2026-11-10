"""Anmeldung gegen LDAP/Active Directory.

Aus, solange LDAP nicht konfiguriert ist. Erfolgreiche LDAP-Anmeldungen
legen beim ersten Mal ein lokales Konto an (Rolle benutzer), damit
Sitzungen, TOTP und Audit einheitlich bleiben. Das Passwort selbst wird
nie gespeichert.
"""

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Benutzer
from app.security import hash_password


def try_ldap_login(session: Session, benutzername: str, passwort: str, vorhanden: Benutzer | None) -> Benutzer | None:
    settings = get_settings()
    if not settings.ldap_enabled or not settings.ldap_url:
        return None
    try:
        from ldap3 import ALL, Connection, Server
        from ldap3.utils.conv import escape_filter_chars
    except ImportError:
        return None

    server = Server(settings.ldap_url, get_info=ALL, connect_timeout=5)
    suchfilter = settings.ldap_user_filter.format(username=escape_filter_chars(benutzername))
    bind: dict = {}
    if settings.ldap_bind_dn:
        bind = {"user": settings.ldap_bind_dn, "password": settings.ldap_bind_password}
    verbindung = Connection(server, auto_bind=True, **bind)
    verbindung.search(settings.ldap_user_base, suchfilter, attributes=["displayName", "mail", "distinguishedName"])
    if not verbindung.entries:
        verbindung.unbind()
        return None
    eintrag = verbindung.entries[0]
    dn = str(eintrag.distinguishedName)
    verbindung.unbind()
    pruefung = Connection(server, user=dn, password=passwort, auto_bind=False)
    if not pruefung.bind():
        return None
    pruefung.unbind()

    name = str(eintrag.displayName) if "displayName" in eintrag else benutzername
    email = str(eintrag.mail) if "mail" in eintrag else None
    if vorhanden:
        if not vorhanden.aktiv:
            return None
        vorhanden.name = name or vorhanden.name
        vorhanden.email = email or vorhanden.email
        vorhanden.auth_quelle = "ldap"
        session.flush()
        return vorhanden
    benutzer = Benutzer(
        benutzername=benutzername,
        name=name or benutzername,
        email=email,
        passwort_hash=hash_password("ldap-keine-lokale-anmeldung"),
        auth_quelle="ldap",
        rolle="benutzer",
        aktiv=True,
    )
    session.add(benutzer)
    session.flush()
    return benutzer
