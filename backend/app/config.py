from functools import lru_cache
import os
import secrets
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./buchhaltung-lokal.db"
    # Startwerte für den ersten Administrator. Werden nur gelesen, solange
    # die Tabelle benutzer noch leer ist.
    admin_benutzer: str = "admin"
    admin_passwort: str = ""
    # Veraltet: galt früher für die Anmeldung mit einem geteilten Passwort.
    # Dient nur noch als Rückfall für admin_passwort beim allerersten Start.
    buchhaltung_password: str = ""
    # Umgebung: development oder production. Nur production vertraut
    # ausschließlich den konfigurierten WebAuthn-Origins.
    environment: str = "development"
    # Öffentliche Adresse der App. Steht in Einladungs- und Reset-Mails und
    # ist der Fallback für WebAuthn (rp_id und Origins).
    public_url: str = "http://127.0.0.1:5173"
    # Passkeys: Relying-Party-ID (Hostname, keine IP). Leer = aus public_url.
    webauthn_rp_id: str = ""
    # Passkeys: erlaubte Browser-Origins, kommagetrennt. Leer = public_url.
    webauthn_origins: str = ""
    # LDAP/Active Directory. Aus = nur lokale Konten.
    ldap_enabled: bool = False
    ldap_url: str = ""
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    ldap_user_base: str = ""
    ldap_user_filter: str = "(sAMAccountName={username})"
    session_secret: str = Field(
        default="",
        validation_alias=AliasChoices("BUCHHALTUNG_SESSION_SECRET", "SESSION_SECRET"),
    )
    cookie_secure: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls: bool = True
    beleg_ordner: str = ""
    mustang_java: str = ""
    mustang_jar: str = ""
    azure_endpoint: str = ""
    azure_api_key: str = ""
    azure_deployment: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def _session_festhalten(geheim: str) -> None:
    os.environ["BUCHHALTUNG_SESSION_SECRET"] = geheim
    pfad = Path(os.environ.get("BUCHHALTUNG_ENV_DATEI", "/etc/buchhaltung.env"))
    if not pfad.is_file():
        return
    try:
        text = pfad.read_text(encoding="utf-8")
    except OSError:
        return
    zeilen = text.splitlines()
    neu = f"BUCHHALTUNG_SESSION_SECRET={geheim}"
    ersetzt = False
    for index, zeile in enumerate(zeilen):
        if zeile.startswith("BUCHHALTUNG_SESSION_SECRET=") or zeile.startswith("SESSION_SECRET="):
            wert = zeile.split("=", 1)[1]
            if wert and wert != "CHANGE_ME":
                return
            zeilen[index] = neu
            ersetzt = True
            break
    if not ersetzt:
        zeilen.append(neu)
    try:
        pfad.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    except OSError:
        return


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.session_secret or settings.session_secret == "CHANGE_ME":
        settings.session_secret = secrets.token_hex(32)
        _session_festhalten(settings.session_secret)
    return settings
