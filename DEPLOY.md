# Deployment — Opentakt Rewe

On-Prem: Python FastAPI + PostgreSQL + React-PWA hinter nginx, systemd und eigenen Zertifikaten.
Zielsystem: **Debian 12 oder 13**, SSH-Zugang als **root** für die Erstinstallation.

## Neue Maschine

DNS zeigt auf die Maschine, der Tree liegt z. B. unter `/tmp/opentakt-rewe`:

```bash
export DOMAIN=rewe.firma.de ADMIN_PASSWORT='sicheres-startpasswort'
bash /tmp/opentakt-rewe/deploy/setup-server.sh
```

Das Skript richtet ein:

- PostgreSQL mit Datenbank und Benutzer `buchhaltung` (nur localhost)
- App unter `/opt/buchhaltung`, Umgebung in `/etc/buchhaltung.env` (Rechte 640)
- `buchhaltung.service` (API auf `127.0.0.1:8000`), Migrationen laufen beim Start
- `buchhaltung-serie.timer` (täglicher Serienlauf, 6 Uhr)
- `buchhaltung-backup.timer` (`pg_dump` nach `/var/backups/buchhaltung`, 14 Tage aufgehoben)
- `buchhaltung-mailimport.timer` (Postfach-Abruf alle 15 Minuten; ruht ohne `IMAP_HOST`)
- Texterkennung (`tesseract-ocr` mit deutschen und englischen Daten) für Belege ohne Textteil
- nginx-Site für `DOMAIN`

Zertifikate holt das Skript **nicht**. Die Site wird nur verlinkt, wenn
`/etc/nginx/certs/<DOMAIN>/fullchain.pem` und `privkey.pem` existieren.
Sonst nach dem Ablegen von Hand verlinken:

```bash
ln -s /etc/nginx/sites-available/buchhaltung /etc/nginx/sites-enabled/buchhaltung
nginx -t && systemctl reload nginx
```

Danach als `admin` anmelden und das Passwort wechseln (die App verlangt das beim ersten Login).

## Laufende Installation aktualisieren

Quelle ist immer GitHub (`main`-Branch). Als Admin in der Oberfläche unter **Einstellungen → Update** (Reiter nur für Admins sichtbar) auf **Jetzt prüfen** und dann **Update installieren** klicken. Das legt `/var/lib/buchhaltung/update.request` an; die Path-Unit `buchhaltung-update.path` startet darauf den Dienst `buchhaltung-update.service`, der `deploy/update.sh --from-web` als root ausführt. Das Skript sichert die Datenbank per `pg_dump` nach `/var/backups/buchhaltung/pre-update/`, holt den Code, installiert Abhängigkeiten, baut das Frontend und startet den Dienst neu (Migrationen laufen beim Start). Stand und Protokoll stehen in `/var/lib/buchhaltung/update-status.json` und `/var/lib/buchhaltung/update.log`. Umgebung, Datenbank, Belege, nginx und Zertifikate bleiben unangetastet.

Auf Installationen von vor dieser Funktion fehlt die Path-Unit noch: einmal manuell wie unten aktualisieren — `update.sh` installiert sie dann, und danach geht es per Knopf.

Manuell als root auf dem Server (Ersatzweg, auch bei kaputter Oberfläche):

```bash
rm -rf /tmp/opentakt-rewe
git clone --depth 1 https://github.com/christiankohrn/opentakt-rewe.git /tmp/opentakt-rewe
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'backend/.venv' \
  --exclude 'node_modules' \
  --exclude 'frontend/node_modules' \
  --exclude 'frontend/dist' \
  --exclude '__pycache__' \
  --exclude 'data' \
  --exclude '*.db*' \
  /tmp/opentakt-rewe/ /opt/buchhaltung/
bash /opt/buchhaltung/deploy/update.sh
```

Unter `/opt/buchhaltung` liegt kein Git-Repository. `deploy/setup-server.sh` nicht für ein normales Update starten: es schreibt Units und nginx-Site neu.

Prüfung: `curl -fsS https://rewe.firma.de/api/health`. Zeigt der Browser noch die alte Oberfläche, die Seite neu laden.

## Hinweise

- SMTP, Beleg-Postfach (IMAP) und Azure-KI lassen sich in der UI unter Einstellungen eintragen; sie landen in `/etc/buchhaltung.env`.
- Für das Postfach ein eigenes Postfach nur für Belege verwenden. Der Abruf importiert PDF- und Bild-Anhänge ungesehener Mails und markiert sie als gelesen (auf Wunsch sortiert er sie in den Erledigt-Ordner). Von Hand: `su buchhaltung -s /bin/sh -c "cd /opt/buchhaltung/backend && .venv/bin/python -m app.cli mailimport"`.
- Die Legacy-Variable `BUCHHALTUNG_PASSWORD` wird nur noch als Rückfall für `ADMIN_PASSWORT` beim allerersten Start gelesen.
- Logs: `journalctl -u buchhaltung.service`, Timer: `systemctl list-timers 'buchhaltung-*'`.
- Update per Knopf: `buchhaltung-update.path` beobachtet `/var/lib/buchhaltung/update.request` und startet `buchhaltung-update.service`. Tut sich nach dem Klick nichts: `systemctl status buchhaltung-update.path`, Protokoll in `/var/lib/buchhaltung/update.log`.
