# Agent notes — Opentakt Rewe

Öffentliche Doku: `README.md`, `DEPLOY.md`, `CONTRIBUTING.md`.

## Stack

Python FastAPI + PostgreSQL (Server) oder SQLite (lokal) + React/Vite-PWA. systemd + nginx. Serienlauf und Backup via systemd-timer.

## Lokal

Siehe README (Schnellstart). Health: `GET /api/health`. Kein interaktives pdb.

## Debian-Pfade (nach `deploy/setup-server.sh`)

- App: `/opt/buchhaltung`
- Umgebung: `/etc/buchhaltung.env` (Rechte 640)
- Belege: `/var/lib/buchhaltung/belege`
- Backups: `/var/backups/buchhaltung/`
- Dienstbenutzer: `buchhaltung`

Installationspfade, Umgebungsvariablen und der Session-Cookie heißen weiter `buchhaltung`, damit bestehende Installationen ohne Migration laufen. Der Produktname ist **Opentakt Rewe**.

## Seed

Auf leerer Datenbank legt der Start den Administrator aus `ADMIN_BENUTZER`/`ADMIN_PASSWORT` an (Rückfall: `BUCHHALTUNG_PASSWORD`). Er muss beim ersten Login ein eigenes Passwort vergeben; weitere Benutzer legt der Admin in der UI unter Benutzer an.

## Texte

Keine Produktnamen anderer Software in PRs, UI, Commit-Messages oder neuer Dokumentation. Nicht vergleichen, nicht erwähnen.
