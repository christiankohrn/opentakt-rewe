#!/usr/bin/env bash
# Opentakt Rewe auf Debian 12/13 einrichten: PostgreSQL, API als systemd-Dienst,
# täglicher Serienlauf, tägliches pg_dump-Backup, nginx-Site.
#
# Aufruf als root aus einem Klon:
#   export DOMAIN=rewe.firma.de ADMIN_PASSWORT='...'
#   bash deploy/setup-server.sh
#
# Das Skript ist erneut lauffähig. /etc/buchhaltung.env wird nur angelegt,
# nie überschrieben. Zertifikate holt das Skript nicht: Die nginx-Site wird
# nur verlinkt, wenn /etc/nginx/certs/<DOMAIN>/fullchain.pem und privkey.pem
# existieren.
set -euo pipefail

DOMAIN="${DOMAIN:-${1:-}}"
if [ -z "$DOMAIN" ]; then
  echo "DOMAIN fehlt. Beispiel: DOMAIN=rewe.firma.de $0" >&2
  exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte als root ausführen." >&2
  exit 1
fi
if [ -z "${ADMIN_PASSWORT:-}" ]; then
  echo "ADMIN_PASSWORT fehlt (Startpasswort für den Administrator)." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TREE="${TREE:-$(dirname "$SCRIPT_DIR")}"
APP=/opt/buchhaltung
ENV_FILE=/etc/buchhaltung.env
DB_NAME=buchhaltung
DB_USER=buchhaltung

echo "== Pakete =="
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y postgresql postgresql-contrib python3-venv rsync nginx \
  fonts-dejavu-core fonts-liberation curl ca-certificates gnupg \
  tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng

if ! command -v node >/dev/null 2>&1; then
  echo "== Node.js 22 =="
  mkdir -p /etc/apt/keyrings
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
    | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
  echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
    > /etc/apt/sources.list.d/nodesource.list
  apt-get update
  apt-get install -y nodejs
fi

echo "== Benutzer und Verzeichnisse =="
id "$DB_USER" >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin "$DB_USER"
mkdir -p "$APP" /var/lib/buchhaltung/belege /var/backups/buchhaltung
chown -R "$DB_USER:$DB_USER" /var/lib/buchhaltung /var/backups/buchhaltung

echo "== PostgreSQL =="
systemctl enable --now postgresql >/dev/null 2>&1 || service postgresql start
if ! su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'\"" | grep -q 1; then
  DB_PASS="$(openssl rand -hex 24)"
  su postgres -c "psql -c \"CREATE USER $DB_USER PASSWORD '$DB_PASS'\""
  su postgres -c "psql -c \"CREATE DATABASE $DB_NAME OWNER $DB_USER\""
  echo "$DB_PASS" > /root/.buchhaltung-db-pass
  chmod 600 /root/.buchhaltung-db-pass
  echo "DB-Passwort steht in /root/.buchhaltung-db-pass"
else
  DB_PASS="$(cat /root/.buchhaltung-db-pass 2>/dev/null || true)"
fi

echo "== Umgebung =="
if [ ! -f "$ENV_FILE" ]; then
  SECRET="$(openssl rand -hex 32)"
  {
    echo "# Opentakt Rewe, angelegt $(date -u +%Y-%m-%d). Nicht ins Git."
    echo "DATABASE_URL=postgresql+psycopg://$DB_USER:${DB_PASS:-BITTE-EINTRAGEN}@127.0.0.1:5432/$DB_NAME"
    echo "ADMIN_BENUTZER=admin"
    echo "ADMIN_PASSWORT=$ADMIN_PASSWORT"
    echo "BUCHHALTUNG_SESSION_SECRET=$SECRET"
    echo "COOKIE_SECURE=true"
    echo "ENVIRONMENT=production"
    echo "PUBLIC_URL=https://$DOMAIN"
    echo "BUCHHALTUNG_ENV_DATEI=$ENV_FILE"
    echo "BELEG_ORDNER=/var/lib/buchhaltung/belege"
    echo "SMTP_HOST="
    echo "SMTP_PORT=587"
    echo "SMTP_USER="
    echo "SMTP_PASSWORD="
    echo "SMTP_FROM="
    echo "SMTP_TLS=true"
    echo "IMAP_HOST="
    echo "IMAP_PORT=993"
    echo "IMAP_USER="
    echo "IMAP_PASSWORD="
    echo "IMAP_TLS=true"
    echo "IMAP_ORDNER=INBOX"
    echo "IMAP_ERLEDIGT="
    echo "IMAP_QUELLE=eingang"
    echo "MUSTANG_JAVA="
    echo "MUSTANG_JAR="
    echo "AZURE_ENDPOINT="
    echo "AZURE_API_KEY="
    echo "AZURE_DEPLOYMENT="
  } > "$ENV_FILE"
  chmod 640 "$ENV_FILE"
  chown root:"$DB_USER" "$ENV_FILE"
  echo "$ENV_FILE angelegt."
else
  echo "$ENV_FILE existiert, bleibt unverändert."
fi

echo "== App nach $APP =="
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' --exclude 'backend/.venv' \
  --exclude 'node_modules' --exclude 'frontend/node_modules' \
  --exclude 'frontend/dist' \
  --exclude '__pycache__' \
  --exclude 'data' --exclude '*.db*' \
  "$TREE/" "$APP/"
chown -R "$DB_USER:$DB_USER" "$APP"

echo "== Backend =="
su "$DB_USER" -s /bin/sh -c "cd $APP/backend && python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt"

echo "== Frontend =="
su "$DB_USER" -s /bin/sh -c "cd $APP/frontend && npm ci --no-audit --no-fund && npm run build"

echo "== systemd =="
cat > /etc/systemd/system/buchhaltung.service <<EOF
[Unit]
Description=Opentakt Rewe API
After=network.target postgresql.service

[Service]
Type=simple
User=$DB_USER
WorkingDirectory=$APP/backend
EnvironmentFile=$ENV_FILE
ExecStart=$APP/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/buchhaltung-serie.service <<EOF
[Unit]
Description=Opentakt Rewe Serienlauf
After=network.target postgresql.service

[Service]
Type=oneshot
User=$DB_USER
WorkingDirectory=$APP/backend
EnvironmentFile=$ENV_FILE
ExecStart=$APP/backend/.venv/bin/python -m app.cli serie
EOF
cat > /etc/systemd/system/buchhaltung-serie.timer <<EOF
[Unit]
Description=Opentakt Rewe Serienlauf täglich

[Timer]
OnCalendar=*-*-* 06:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
cat > /etc/systemd/system/buchhaltung-mailimport.service <<EOF
[Unit]
Description=Opentakt Rewe Beleg-Import aus dem Postfach
After=network.target postgresql.service

[Service]
Type=oneshot
User=$DB_USER
WorkingDirectory=$APP/backend
EnvironmentFile=$ENV_FILE
ExecStart=$APP/backend/.venv/bin/python -m app.cli mailimport
EOF
cat > /etc/systemd/system/buchhaltung-mailimport.timer <<EOF
[Unit]
Description=Opentakt Rewe Postfach-Abruf alle 15 Minuten

[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
EOF
cat > /etc/systemd/system/buchhaltung-backup.service <<'EOF'
[Unit]
Description=Opentakt Rewe Datenbank-Backup

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'su postgres -s /bin/sh -c "pg_dump -Fc buchhaltung" > /var/backups/buchhaltung/buchhaltung-$(date +%%F).dump && find /var/backups/buchhaltung -name "buchhaltung-*.dump" -mtime +14 -delete'
EOF
cat > /etc/systemd/system/buchhaltung-backup.timer <<EOF
[Unit]
Description=Opentakt Rewe Backup täglich

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now buchhaltung.service
systemctl enable --now buchhaltung-serie.timer
systemctl enable --now buchhaltung-backup.timer
systemctl enable --now buchhaltung-mailimport.timer

echo "== nginx =="
SITE=/etc/nginx/sites-available/buchhaltung
cat > "$SITE" <<EOF
# Opentakt Rewe. Zertifikate erwartet unter /etc/nginx/certs/$DOMAIN/.
server {
  listen 443 ssl;
  server_name $DOMAIN;
  ssl_certificate /etc/nginx/certs/$DOMAIN/fullchain.pem;
  ssl_certificate_key /etc/nginx/certs/$DOMAIN/privkey.pem;

  root $APP/frontend/dist;
  index index.html;

  location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
  }

  location / {
    try_files \$uri \$uri/ /index.html;
  }
}
EOF
if [ -f "/etc/nginx/certs/$DOMAIN/fullchain.pem" ] && [ -f "/etc/nginx/certs/$DOMAIN/privkey.pem" ]; then
  ln -sf "$SITE" /etc/nginx/sites-enabled/buchhaltung
  nginx -t && systemctl reload nginx
  echo "nginx-Site $DOMAIN aktiv."
else
  echo "Zertifikate fehlen, Site nicht verlinkt."
  echo "Erwartet: /etc/nginx/certs/$DOMAIN/fullchain.pem und privkey.pem"
  echo "Danach: ln -s $SITE /etc/nginx/sites-enabled/buchhaltung && nginx -t && systemctl reload nginx"
fi

echo
echo "Fertig. API-Check lokal: curl -fsS http://127.0.0.1:8000/api/health"
echo "Danach als admin anmelden und das Passwort wechseln."
