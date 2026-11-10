# Mitwirken

Danke, dass du Opentakt Rewe verbessern willst. Kleine, nachvollziehbare Änderungen sind leichter zu prüfen als große Sammel-PRs.

## Ablauf

1. Issue öffnen oder an einem bestehenden Issue arbeiten.
2. Fork bzw. Branch vom aktuellen Hauptbranch.
3. Lokal entwickeln und die Tests laufen lassen.
4. Pull Request mit kurzer Beschreibung: **Warum**, nicht nur **Was**.

Bitte keine Secrets, `.env`-Dateien, Datenbanken, Belege oder Kontoauszüge committen.

## Lokale Umgebung

Siehe [README.md](README.md#schnellstart-entwicklung). Kurz:

- Backend: Python 3.12+, `pip install -r backend/requirements.txt`
- Frontend: Node 20+, `npm install` in `frontend/`
- Umgebung: `.env` in `backend/` mit `ADMIN_PASSWORT` und `DATABASE_URL` (Vorlage: `deploy/buchhaltung.env.example`)
- API: `uvicorn` auf Port 8000, UI: Vite auf 5173 (`/api` wird proxied)

## Tests

```bash
cd backend && python -m pytest
cd frontend && npx tsc --noEmit
```

Neue Logik (Rechenregeln, Belegerkennung, DATEV-Export, Kontenabgleich) bitte mit einem Pytest abdecken, im Stil der Dateien unter `backend/tests/`.

## Stil

- Backend: Python 3.12, Typen wo sie helfen, deutsche Nutzertexte in API-Fehlern.
- Frontend: TypeScript `strict`, bestehende Komponenten und CSS-Variablen aus `styles.css` wiederverwenden.
- Hell- und Dunkelmodus bedenken (alle Farben als Variablen, keine hartcodierten Hex-Werte in Komponenten).
- Keine Formatter-only-Diffs in fachlichen PRs.

## Pull Requests

- Ein Thema pro PR.
- Breaking Changes (Umgebung, Datenbankschema, DATEV-Format) deutlich benennen.
- Screenshots oder kurzes Terminal-Log helfen bei UI- und Deploy-Änderungen.
- Keine Produktnamen anderer Software in PR-Texten, UI oder neuer Dokumentation.

Mit dem Beitrag akzeptierst du, dass er unter der [AGPL-3.0-or-later](LICENSE) des Projekts steht.
