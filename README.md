# Opentakt Rewe

Rechnungs- und Belegverwaltung von **Opentakt**: **Rechnungen schreiben, Belege einsammeln, Kontoumsätze zuordnen, DATEV-Export** — als Web-App auf dem eigenen Server.

Kein SaaS, keine Cloud-Pflicht. Python-Backend, PostgreSQL oder SQLite, React-PWA, nginx.

Opentakt Rewe ist das zweite Produkt unter dem Namen Opentakt, nach [Opentakt Zeit](https://github.com/christiankohrn/opentakt-zeit).

[![Lizenz](https://img.shields.io/static/v1?label=Lizenz&message=AGPL-3.0-or-later&color=blue)](LICENSE)
[![CI](https://github.com/christiankohrn/opentakt-rewe/actions/workflows/ci.yml/badge.svg)](https://github.com/christiankohrn/opentakt-rewe/actions/workflows/ci.yml)

## Funktionen

- Rechnungen mit Positionen, Serienrechnungen, Storno, Mahnungen und Mailversand
- Kundenverwaltung
- Belegimport per Drag & Drop (PDF, Bild, CSV, camt) mit Erkennung von Partner, Betrag, Datum und Rechnungsnummer
- Automatischer Belegimport aus einem eigenen Postfach (IMAP): Anhänge werden als Belege übernommen, Mails als gelesen markiert
- Lokale Texterkennung (OCR): Belege ohne Textteil werden beim Import automatisch gelesen, sonst als textlos markiert
- Scan-Seite fürs Smartphone: Beleg fotografieren, Umrisse werden automatisch gesucht, mehrseitige Scans als PDF importieren
- Kontoauszüge und automatische Zuordnung von Belegen zu Umsätzen
- E-Rechnung (ZUGFeRD/XRechnung) und EPC-QR-Code auf Rechnungen
- DATEV-Export (ZIP mit Belegen, Weiterverarbeitungsdatei Dok.-Nr. 9226961) und DATEV-Versand per E-Mail
- Stammdaten, Konten, Abrechnungskriterien und Geschäftspartner in den Einstellungen pflegbar; das System lernt aus Korrekturen
- Optionale Azure-KI zur Belegerkennung (nur auf Knopfdruck)
- Benutzerkonten mit Rollen, Zwei-Faktor (Authenticator-App + Backup-Codes), Passkeys, optional LDAP
- Einladungen und Passwort-Resets per E-Mail, Audit-Protokoll für sicherheitsrelevante Aktionen
- Hell- und Dunkelmodus

## Schnellstart (Entwicklung)

Voraussetzungen: Python 3.12+, Node 20+.

```bash
git clone https://github.com/christiankohrn/opentakt-rewe.git
cd opentakt-rewe

python3 -m venv backend/.venv
source backend/.venv/bin/activate    # Windows: backend\.venv\Scripts\activate
pip install -r backend/requirements.txt

cd frontend && npm install && cd ..
```

Umgebung in `backend/.env` (Vorlage: `deploy/buchhaltung.env.example`):

```bash
DATABASE_URL=sqlite:///./buchhaltung-lokal.db
ADMIN_PASSWORT=ein-sicheres-passwort
BELEG_ORDNER=./belege
```

Zwei Terminals:

```bash
# Backend, Port 8000
cd backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
# Frontend mit Proxy auf /api
cd frontend
npm run dev
```

Im Browser: [http://127.0.0.1:5173](http://127.0.0.1:5173)

Beim Start wendet die API ausstehende Migrationen an. Der Seed legt auf einer **leeren** Datenbank nur den Administrator an (Login `admin`, Passwort aus `ADMIN_PASSWORT`). Beim ersten Login muss ein eigenes Passwort vergeben werden; weitere Benutzer legt der Admin in der UI unter Benutzer an.

## Produktion (Debian)

Debian 12/13, SSH als root, Tree z. B. unter `/tmp/opentakt-rewe`:

```bash
export DOMAIN=rewe.firma.de ADMIN_PASSWORT='sicheres-startpasswort'
bash /tmp/opentakt-rewe/deploy/setup-server.sh
```

Danach liegen App, Umgebung und Belege unter `/opt/buchhaltung`, `/etc/buchhaltung.env` und `/var/lib/buchhaltung/belege`. Die Pfade, Dienste und Variablen heißen intern weiter `buchhaltung`, damit bestehende Installationen ohne Migration laufen. Das Skript holt kein Zertifikat: Die nginx-Site wird nur verlinkt, wenn `/etc/nginx/certs/<DOMAIN>/fullchain.pem` und `privkey.pem` existieren.

Ausführlich: [DEPLOY.md](DEPLOY.md).

## Tests

```bash
cd backend && python -m pytest
cd frontend && npx tsc --noEmit
```

## Konfiguration

Umgebungsvariablen (lokal in `backend/.env`, Produktion in `/etc/buchhaltung.env`). Vorlage: [`deploy/buchhaltung.env.example`](deploy/buchhaltung.env.example).

| Variable | Bedeutung |
| --- | --- |
| `DATABASE_URL` | SQLite (`sqlite:///./buchhaltung-lokal.db`) oder PostgreSQL (`postgresql+psycopg://…`) |
| `ADMIN_BENUTZER` / `ADMIN_PASSWORT` | Seed-Admin, nur auf leerer Datenbank gelesen |
| `BUCHHALTUNG_SESSION_SECRET` | Session-Cookie; `CHANGE_ME` wird beim ersten Start ersetzt |
| `COOKIE_SECURE` | `true` hinter HTTPS |
| `BELEG_ORDNER` | Ablage der Belegdateien, lokal z. B. `./belege` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS` | Mailversand; auch in der UI pflegbar |
| `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, `IMAP_PASSWORD`, `IMAP_TLS`, `IMAP_ORDNER`, `IMAP_ERLEDIGT`, `IMAP_QUELLE` | Beleg-Postfach für den automatischen Import; auch in der UI pflegbar |
| `AZURE_ENDPOINT`, `AZURE_API_KEY`, `AZURE_DEPLOYMENT` | Optionale KI-Belegerkennung; auch in der UI pflegbar |
| `MUSTANG_JAVA`, `MUSTANG_JAR` | Optionale E-Rechnungs-Prüfung, leer = aus |
| `GITHUB_TOKEN` | Optionaler Token für den Update-Check (mehr GitHub-Abfragen); leer geht auch |
| `ENVIRONMENT` | `development` oder `production` (Produktion vertraut nur konfigurierten WebAuthn-Origins) |
| `PUBLIC_URL` | Öffentliche Adresse; steht in Mail-Links und ist WebAuthn-Fallback |
| `WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGINS` | Passkeys; leer = aus `PUBLIC_URL` abgeleitet |
| `LDAP_ENABLED`, `LDAP_URL`, `LDAP_BIND_DN`, `LDAP_BIND_PASSWORD`, `LDAP_USER_BASE`, `LDAP_USER_FILTER` | Optionale Anmeldung gegen LDAP/Active Directory |

`.env`, `*.db` und Belegordner sind per `.gitignore` ausgeschlossen.

## Altdaten übernehmen (optional)

Wer Bestandsdaten aus einer SQL-CE-Datei (`.sdf`) mit den Tabellen `Kundes`, `Rechnungs`, `Positions`, `Serienpositionens`, `Options` hat, kann sie übernehmen:

```bash
# 1. Auf Windows: SDF nach JSON exportieren (SQL-CE-Bibliothek nötig)
python -m app.importer export --sdf PFAD\daten.sdf --dll PFAD\System.Data.SqlServerCe.dll --native PFAD\amd64 --out ..\data\import.jsonl
# 2. In die Datenbank laden
python -m app.importer load --json ..\data\import.jsonl
```

Dump und SDF bleiben außerhalb von Git (`data/` ist ignoriert).

## Mitwirken

Fehler, Ideen und Pull Requests sind willkommen. Bitte [CONTRIBUTING.md](CONTRIBUTING.md) und den [Verhaltenskodex](CODE_OF_CONDUCT.md) lesen. Sicherheitslücken **nicht** öffentlich tracken — siehe [SECURITY.md](SECURITY.md).

## Lizenz

[GNU Affero General Public License v3.0 oder später](LICENSE) (`AGPL-3.0-or-later`).

Copyright © 2026 Christian Kohrn.

Die AGPL passt zu einer App, die als Netz-Dienst läuft: selbst hosten, anpassen und kommerziell betreiben ist erlaubt. Wer eine veränderte Version **als Dienst für andere** anbietet, muss den zugehörigen Quellcode ebenfalls unter AGPL bereitstellen. Das verhindert geschlossene SaaS-Forks, ohne Selbst-Hosting einzuschränken.

Abhängigkeiten (FastAPI, React, …) behalten ihre eigenen Lizenzen.
