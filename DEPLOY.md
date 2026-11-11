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

Unter `/opt/buchhaltung` liegt kein Git-Repository. Umgebung (`/etc/buchhaltung.env`), Datenbank und Belege (`/var/lib/buchhaltung/belege`) bleiben unangetastet.

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
chown -R buchhaltung:buchhaltung /opt/buchhaltung
su buchhaltung -s /bin/sh -c "cd /opt/buchhaltung/backend && .venv/bin/pip install -q -r requirements.txt"
su buchhaltung -s /bin/sh -c "cd /opt/buchhaltung/frontend && npm ci --no-audit --no-fund && npm run build"
su postgres -s /bin/sh -c "pg_dump -Fc buchhaltung" > /var/backups/buchhaltung/pre-update-$(date +%F-%H%M).dump
systemctl restart buchhaltung.service
```

Prüfung: `curl -fsS https://rewe.firma.de/api/health`. Zeigt der Browser noch die alte Oberfläche, die Seite neu laden.

## Hinweise

- SMTP, Beleg-Postfach (IMAP) und Azure-KI lassen sich in der UI unter Einstellungen eintragen; sie landen in `/etc/buchhaltung.env`.
- Für das Postfach ein eigenes Postfach nur für Belege verwenden. Der Abruf importiert PDF- und Bild-Anhänge ungesehener Mails und markiert sie als gelesen (auf Wunsch sortiert er sie in den Erledigt-Ordner). Von Hand: `su buchhaltung -s /bin/sh -c "cd /opt/buchhaltung/backend && .venv/bin/python -m app.cli mailimport"`.
- Die Legacy-Variable `BUCHHALTUNG_PASSWORD` wird nur noch als Rückfall für `ADMIN_PASSWORT` beim allerersten Start gelesen.
- Logs: `journalctl -u buchhaltung.service`, Timer: `systemctl list-timers 'buchhaltung-*'`.
