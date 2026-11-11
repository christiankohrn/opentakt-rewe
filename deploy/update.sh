#!/bin/bash
set -euo pipefail
# Aktualisiert eine laufende Installation. Als root laufen lassen.
#
# Manuell (Code wurde vorher per rsync nach /opt/buchhaltung kopiert):
#   bash /opt/buchhaltung/deploy/update.sh
# Aus der Weboberfläche (GitHub ist die Quelle, systemd-Path-Unit ruft auf):
#   update.sh --from-web   (klont, kopiert, startet sich als --continue-from-web neu)
APP=/opt/buchhaltung
DATA=/var/lib/buchhaltung
BACKUP=/var/backups/buchhaltung
USER=buchhaltung
export DATA
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
MODE="${1:-}"

LOG="$DATA/update.log"
META="$DATA/.update-meta.json"
LOCK="$DATA/update.lock"

# Pflegt den Update-Teil von $DATA/update-status.json. Argumente: zustand [fehler] [commit].
update_state() {
  STATE="$1" STATE_ERROR="${2:-}" STATE_TO="${3:-}" python3 <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

data = Path(os.environ.get("DATA", "/var/lib/buchhaltung"))
p = data / "update-status.json"
try:
    cur = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
except ValueError:
    cur = {}
if not isinstance(cur, dict):
    cur = {}
upd = cur.get("update") if isinstance(cur.get("update"), dict) else {}
upd["zustand"] = os.environ["STATE"]
if os.environ.get("STATE_TO"):
    upd["nach_commit"] = os.environ["STATE_TO"][:7]
if os.environ.get("STATE_ERROR"):
    upd["fehler"] = os.environ["STATE_ERROR"][:500]
if os.environ["STATE"] in {"done", "failed"}:
    upd["beendet_am"] = datetime.now(timezone.utc).isoformat()
cur["update"] = upd
tmp = p.with_suffix(".tmp")
tmp.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
tmp.replace(p)
PY
  chown buchhaltung:buchhaltung "$DATA/update-status.json" || true
}

# Git-Stand eines Verzeichnisses als JSON nach stdout (leer bei Fehler).
git_meta_json() {
  python3 - "$1" <<'PY'
import json
import subprocess
import sys

d = sys.argv[1]

def run(*args):
    try:
        return subprocess.run(
            ["git", "-C", d, *args], capture_output=True, text=True, timeout=10, check=True
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""

print(json.dumps({
    "commit": run("rev-parse", "HEAD"),
    "commit_date": run("log", "-1", "--format=%cI"),
    "message": run("log", "-1", "--format=%s")[:160],
}))
PY
}

# Schreibt $DATA/version.json. Argumente: commit datum nachricht.
write_version_json() {
  V_COMMIT="$1" V_DATE="$2" V_MSG="$3" python3 <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

data = Path(os.environ.get("DATA", "/var/lib/buchhaltung"))
p = data / "version.json"
doc = {
    "commit": os.environ.get("V_COMMIT") or None,
    "commit_datum": os.environ.get("V_DATE") or None,
    "nachricht": (os.environ.get("V_MSG") or "")[:160],
    "installed_at": datetime.now(timezone.utc).isoformat(),
    "source": "github",
    "branch": "main",
}
tmp = p.with_suffix(".tmp")
tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
tmp.replace(p)
PY
  chown buchhaltung:buchhaltung "$DATA/version.json" || true
}

# Schreibt $DATA/version.json aus dem Git-Stand eines Verzeichnisses (leise ohne .git).
write_version_from_dir() {
  eval "$(git_meta_json "$1" | python3 -c '
import json
import shlex
import sys

try:
    d = json.load(sys.stdin)
except ValueError:
    d = {}
print("META_COMMIT=" + shlex.quote(str(d.get("commit") or "")))
print("META_DATE=" + shlex.quote(str(d.get("commit_date") or "")))
print("META_MSG=" + shlex.quote(str(d.get("message") or "")))
')"
  if [ -n "${META_COMMIT:-}" ]; then
    write_version_json "$META_COMMIT" "$META_DATE" "$META_MSG"
  fi
}

install_update_units() {
  install -m 644 "$APP/deploy/buchhaltung-update.service" /etc/systemd/system/buchhaltung-update.service
  install -m 644 "$APP/deploy/buchhaltung-update.path" /etc/systemd/system/buchhaltung-update.path
  systemctl daemon-reload
  systemctl enable --now buchhaltung-update.path
}

wait_health() {
  local url="${1:-http://127.0.0.1:8000/api/health}"
  local i
  for i in $(seq 1 40); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "Health OK ($url)"
      return 0
    fi
    sleep 1
  done
  echo "Warnung: $url antwortet noch nicht" >&2
  return 1
}

fail() {
  echo "FEHLER: $1" >&2
  update_state failed "$1"
  exit 1
}

if [ ! -w "$DATA" ]; then
  echo "Keine Schreibrechte auf $DATA — als root starten." >&2
  exit 1
fi
# --from-web übergibt per exec an --continue-from-web. Die Sperre bleibt liegen,
# der zweite Prozess übernimmt sie (kein zweites mkdir, sonst bricht er ab).
if [ "$MODE" = "--continue-from-web" ]; then
  if [ ! -d "$LOCK" ]; then
    echo "Update-Sperre fehlt. Abbruch." >&2
    update_state failed "Update-Sperre fehlt."
    exit 1
  fi
elif ! mkdir "$LOCK" 2>/dev/null; then
  echo "Ein Update läuft bereits. Abbruch."
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

# Die zweite Phase (--continue-from-web) hakt sich per exec ein und hängt an.
if [ "$MODE" != "--continue-from-web" ]; then
  : >"$LOG"
fi
exec > >(tee -a "$LOG") 2>&1

if [ "$MODE" = "--from-web" ]; then
  rm -f "$DATA/update.request"
  update_state running
  echo "==> Klone von GitHub ($STAMP)"
  WORK="$DATA/tmp-update"
  rm -rf "$WORK"
  GIT_URL="${GIT_URL:-https://github.com/christiankohrn/opentakt-rewe.git}"
  git clone --depth 1 "$GIT_URL" "$WORK" || fail "GitHub-Klon ist fehlgeschlagen."
  git_meta_json "$WORK" >"$META" || fail "Commit konnte nicht gelesen werden."
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
    "$WORK"/ "$APP"/
  rm -rf "$WORK"
  chmod a+x "$APP/deploy/"*.sh
  echo "==> Code synchron, starte neue Version"
  exec bash "$APP/deploy/update.sh" --continue-from-web
fi

FROM_WEB=0
if [ "$MODE" = "--continue-from-web" ]; then
  FROM_WEB=1
fi

if [ "$MODE" != "" ] && [ "$MODE" != "--continue-from-web" ]; then
  echo "Unbekannte Option: $MODE" >&2
  exit 1
fi

chown -R "$USER:$USER" "$APP"
# deploy/ gehört root: Der Dienst darf das Update-Skript und die Units,
# die als root laufen, nicht verändern können.
chown -R root:root "$APP/deploy"
chmod 755 "$APP/deploy" "$APP/deploy/"*.sh

mkdir -p "$BACKUP/pre-update"
su postgres -s /bin/sh -c "pg_dump -Fc buchhaltung" >"$BACKUP/pre-update/app-$STAMP.dump" \
  || fail "Datenbank-Backup ist fehlgeschlagen."
chmod 600 "$BACKUP/pre-update/app-$STAMP.dump"

if [ -x "$APP/backend/.venv/bin/pip" ]; then
  su "$USER" -s /bin/sh -c "cd $APP/backend && .venv/bin/pip install -q -r requirements.txt" \
    || fail "pip install ist fehlgeschlagen."
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "npm fehlt — Frontend wird nicht gebaut" >&2
elif [ -f "$APP/frontend/package.json" ]; then
  cd "$APP/frontend"
  su "$USER" -s /bin/sh -c "cd $APP/frontend && npm ci --no-audit --no-fund && npm run build" \
    || fail "Frontend-Build ist fehlgeschlagen."
fi

install_update_units

# Installierten Stand festhalten: aus dem Web-Klon oder, manuell, aus /tmp.
META_COMMIT=""
META_DATE=""
META_MSG=""
if [ "$FROM_WEB" = "1" ] && [ -f "$META" ]; then
  eval "$(python3 - "$META" <<'PY'
import json
import shlex
import sys

try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, ValueError):
    d = {}
print("META_COMMIT=" + shlex.quote(str(d.get("commit") or "")))
print("META_DATE=" + shlex.quote(str(d.get("commit_date") or "")))
print("META_MSG=" + shlex.quote(str(d.get("message") or "")))
PY
)"
  rm -f "$META"
  if [ -n "$META_COMMIT" ]; then
    write_version_json "$META_COMMIT" "$META_DATE" "$META_MSG"
  fi
elif [ -d "/tmp/opentakt-rewe/.git" ]; then
  write_version_from_dir /tmp/opentakt-rewe
fi

systemctl restart buchhaltung.service
if wait_health "http://127.0.0.1:8000/api/health"; then
  update_state done "" "$META_COMMIT"
  echo "Update $STAMP fertig"
else
  fail "Der Dienst startet nach dem Update nicht."
fi
