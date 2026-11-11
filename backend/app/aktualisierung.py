"""Update-Check und One-Button-Update, Quelle ist GitHub.

Der Admin prüft den Stand auf GitHub und stößt per Knopf ein Update an.
Der Knopf legt nur eine Anfrage-Datei ab; die systemd-Path-Unit
`buchhaltung-update.path` startet darauf `deploy/update.sh --from-web` als
root. Läuft nur auf Servern mit dieser Unit, nie lokal.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit import protokollieren
from app.auth import require_admin
from app.branding import APP_VERSION, REPO_URL, UPDATE_BRANCH
from app.config import Settings, get_settings
from app.db import get_db
from app.models import Benutzer

router = APIRouter(prefix="/api")

ANFRAGE_DATEI = "update.request"
STATUS_DATEI = "update-status.json"
VERSION_DATEI = "version.json"
PROTOKOLL_DATEI = "update.log"
PROTOKOLL_ZEILEN = 30
GITHUB_TIMEOUT = 10.0
# Die systemd-Path-Unit beobachtet genau dieses Verzeichnis. Nur wenn das
# Backend dorthin schreibt, löst der Knopf wirklich ein Update aus.
UPDATE_UNIT_PFAD = Path("/etc/systemd/system/buchhaltung-update.path")
UPDATE_ANFRAGE_ORDNER = Path("/var/lib/buchhaltung")


class UpdateFehler(Exception):
    """Der Stand auf GitHub ließ sich nicht ermitteln (Text ist UI-tauglich)."""


def app_stamm() -> Path:
    # backend/app/aktualisierung.py -> backend/.. = Repo-Root bzw. /opt/buchhaltung
    return Path(__file__).resolve().parents[2]


def daten_ordner(settings: Settings | None = None) -> Path:
    """Ablage für Update-Dateien: auf dem Server das beobachtete Verzeichnis,
    sonst ein lokaler data/-Ordner (gitignoriert). Auflösung wie belege.ordner."""
    settings = settings or get_settings()
    belege = (settings.beleg_ordner or "").strip()
    pfad = Path(belege) if belege else Path("/var/lib/buchhaltung/belege")
    if not pfad.is_absolute():
        pfad = Path.cwd() / pfad
    try:
        if pfad.parent.resolve() == UPDATE_ANFRAGE_ORDNER.resolve() and pfad.parent.is_dir():
            return UPDATE_ANFRAGE_ORDNER
    except OSError:
        pass
    return Path.cwd() / "data"


def _api_repo() -> str:
    # https://github.com/christiankohrn/opentakt-rewe -> christiankohrn/opentakt-rewe
    return urlparse(REPO_URL).path.strip("/")


def update_unterstuetzt(settings: Settings | None = None) -> tuple[bool, str | None]:
    """One-Button-Update gibt es auf jedem Server mit Update-Unit (prod wie dev).

    Entscheidend ist das Layout, nicht `environment`: Updater-Skript und
    systemd-Path-Unit müssen da sein, und das Datenverzeichnis muss genau das
    beobachtete sein — sonst liefe die Anfrage ins Leere.
    """
    settings = settings or get_settings()
    skript = app_stamm() / "deploy" / "update.sh"
    if not skript.is_file() or not UPDATE_UNIT_PFAD.is_file():
        return False, "Das One-Button-Update gibt es nur auf dem Server."
    try:
        beobachtet = daten_ordner(settings).resolve() == UPDATE_ANFRAGE_ORDNER.resolve()
    except OSError:
        beobachtet = False
    if not beobachtet:
        return False, "Das One-Button-Update gibt es nur auf dem Server."
    return True, None


def _version_datei_lesen() -> dict:
    pfad = daten_ordner() / VERSION_DATEI
    try:
        if pfad.is_file():
            daten = json.loads(pfad.read_text(encoding="utf-8"))
            if isinstance(daten, dict):
                return daten
    except (OSError, ValueError):
        pass
    return {}


def _git_stand(stamm: Path) -> dict:
    try:
        sha = subprocess.run(
            ["git", "-C", str(stamm), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        info = subprocess.run(
            ["git", "-C", str(stamm), "log", "-1", "--format=%cI%n%s"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return {}
    if not sha:
        return {}
    return {
        "commit": sha,
        "commit_datum": info[0].strip() if info else None,
        "nachricht": info[1].strip() if len(info) > 1 else "",
    }


def installations_stand() -> dict:
    info: dict = {"version": APP_VERSION, "commit": None, "commit_datum": None, "nachricht": ""}
    gespeichert = _version_datei_lesen()
    if gespeichert.get("commit"):
        info.update({k: gespeichert.get(k) for k in ("commit", "commit_datum", "nachricht")})
        return info
    info.update(_git_stand(app_stamm()))
    return info


def json_laden(url: str, settings: Settings) -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Opentakt-Rewe/update-check"}
    token = (settings.github_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        antwort = httpx.get(url, headers=headers, timeout=GITHUB_TIMEOUT)
    except httpx.TimeoutException:
        raise UpdateFehler("GitHub antwortet nicht (Zeitüberschreitung). Später erneut versuchen.")
    except httpx.HTTPError:
        raise UpdateFehler("GitHub ist nicht erreichbar. Netzwerk des Servers prüfen.")
    if antwort.status_code == 403 and "rate limit" in antwort.text.lower():
        raise UpdateFehler("GitHub-Limit erreicht (zu viele Abfragen). Später erneut versuchen.")
    if antwort.status_code == 404:
        raise UpdateFehler(f"Branch {UPDATE_BRANCH!r} auf GitHub nicht gefunden.")
    if antwort.status_code >= 400:
        raise UpdateFehler(f"GitHub meldet Fehler {antwort.status_code}. Später erneut versuchen.")
    try:
        daten = antwort.json()
    except ValueError:
        raise UpdateFehler("GitHub hat unverständlich geantwortet. Später erneut versuchen.")
    return daten if isinstance(daten, dict) else {}


def remote_pruefen(settings: Settings, lokal: str | None) -> dict:
    """Fragt den GitHub-Stand ab und vergleicht mit dem installierten Commit."""
    api = f"https://api.github.com/repos/{_api_repo()}"
    kopf = json_laden(f"{api}/commits/{UPDATE_BRANCH}", settings)
    sha = (kopf.get("sha") or "").strip()
    if not sha:
        raise UpdateFehler("GitHub hat keinen Commit geliefert. Später erneut versuchen.")
    innen = kopf.get("commit") or {}
    autor = innen.get("committer") or {}
    remote = {
        "commit": sha,
        "commit_kurz": sha[:7],
        "datum": autor.get("date"),
        "nachricht": str(innen.get("message") or "").splitlines()[0][:160] if innen.get("message") else "",
        "url": kopf.get("html_url") or f"{REPO_URL}/commit/{sha}",
    }
    vergleich = "unbekannt"
    dahinter: int | None = None
    if lokal:
        verglichen = json_laden(f"{api}/compare/{lokal}...{sha}", settings)
        stand = (verglichen.get("status") or "").strip()
        if stand == "identical":
            vergleich = "aktuell"
            dahinter = 0
        elif stand == "behind":
            vergleich = "dahinter"
            dahinter = int(verglichen.get("behind_by") or 0)
        elif stand == "ahead":
            vergleich = "voraus"
            dahinter = 0
        elif stand == "diverged":
            vergleich = "abgewichen"
            dahinter = int(verglichen.get("behind_by") or 0)
    return {"remote": remote, "vergleich": vergleich, "dahinter": dahinter}


def _leerer_status() -> dict:
    return {
        "remote": None,
        "vergleich": "unbekannt",
        "dahinter": None,
        "letzte_pruefung": None,
        "update": {"zustand": "idle"},
    }


def status_lesen() -> dict:
    gemischt = _leerer_status()
    try:
        pfad = daten_ordner() / STATUS_DATEI
        if pfad.is_file():
            daten = json.loads(pfad.read_text(encoding="utf-8"))
            if isinstance(daten, dict):
                gemischt.update(daten)
    except (OSError, ValueError):
        pass
    if not isinstance(gemischt.get("update"), dict):
        gemischt["update"] = {"zustand": "idle"}
    return gemischt


def status_schreiben(teil: dict) -> dict:
    aktuell = status_lesen()
    aktuell.update(teil)
    pfad = daten_ordner() / STATUS_DATEI
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(".tmp")
    tmp.write_text(json.dumps(aktuell, ensure_ascii=False), encoding="utf-8")
    tmp.replace(pfad)
    return aktuell


def _protokoll_ende() -> list[str]:
    try:
        pfad = daten_ordner() / PROTOKOLL_DATEI
        if not pfad.is_file():
            return []
        zeilen = pfad.read_text(encoding="utf-8", errors="replace").splitlines()
        return zeilen[-PROTOKOLL_ZEILEN:]
    except OSError:
        return []


def status_antwort(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    unterstuetzt, grund = update_unterstuetzt(settings)
    installiert = installations_stand()
    sha = installiert.get("commit") or ""
    gepuffert = status_lesen()
    update = dict(gepuffert.get("update") or {"zustand": "idle"})
    update["protokoll"] = _protokoll_ende()
    return {
        "unterstuetzt": unterstuetzt,
        "grund": grund,
        "installiert": {
            "version": installiert.get("version"),
            "commit": sha or None,
            "commit_kurz": sha[:7] if sha else None,
            "commit_datum": installiert.get("commit_datum"),
            "nachricht": installiert.get("nachricht") or "",
        },
        "quelle": {"repo": _api_repo(), "branch": UPDATE_BRANCH, "url": REPO_URL},
        "remote": gepuffert.get("remote"),
        "vergleich": gepuffert.get("vergleich", "unbekannt"),
        "dahinter": gepuffert.get("dahinter"),
        "letzte_pruefung": gepuffert.get("letzte_pruefung"),
        "update": update,
    }


def jetzt_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def update_anfordern(name: str, benutzer_id: int) -> dict:
    einstellungen = get_settings()
    unterstuetzt, grund = update_unterstuetzt(einstellungen)
    if not unterstuetzt:
        raise HTTPException(409, grund or "Update auf diesem System nicht möglich.")
    zustand = (status_lesen().get("update") or {}).get("zustand")
    if zustand == "running":
        raise HTTPException(409, "Ein Update läuft bereits.")
    installiert = installations_stand()
    ordner = daten_ordner(einstellungen)
    ordner.mkdir(parents=True, exist_ok=True)
    # Direkt schreiben (kein Rename): Die systemd-Path-Unit reagiert auf die Änderung.
    (ordner / ANFRAGE_DATEI).write_text(
        json.dumps(
            {"gestartet_von": name, "gestartet_von_id": benutzer_id, "gestartet_am": jetzt_iso()},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    status_schreiben(
        {
            "update": {
                "zustand": "running",
                "gestartet_von": name,
                "gestartet_am": jetzt_iso(),
                "von_commit": (installiert.get("commit") or "")[:7] or None,
                "nach_commit": None,
                "beendet_am": None,
                "fehler": None,
            }
        }
    )
    return status_antwort(einstellungen)


@router.get("/update/status")
def update_status(admin: Benutzer = Depends(require_admin)) -> dict:
    return status_antwort()


@router.post("/update/check")
def update_check(admin: Benutzer = Depends(require_admin)) -> dict:
    einstellungen = get_settings()
    installiert = installations_stand()
    try:
        ergebnis = remote_pruefen(einstellungen, installiert.get("commit"))
    except UpdateFehler as exc:
        raise HTTPException(502, str(exc)) from exc
    status_schreiben({**ergebnis, "letzte_pruefung": jetzt_iso()})
    return status_antwort(einstellungen)


@router.post("/update/apply", status_code=202)
def update_apply(admin: Benutzer = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    antwort = update_anfordern(admin.benutzername, admin.benutzer_id)
    protokollieren(db, "update.apply", admin, "system", "update", json.dumps({"von": admin.benutzername}))
    db.commit()
    return antwort
