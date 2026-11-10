# Sicherheit

Opentakt Rewe speichert Rechnungs-, Beleg- und Kontodaten. Bitte behandelt Funde entsprechend.

## Melden

**Keine öffentlichen Issues** für Sicherheitslücken.

1. GitHub: [privates Security Advisory](https://github.com/christiankohrn/opentakt-rewe/security/advisories/new)
2. Oder direkt an den Maintainer [@christiankohrn](https://github.com/christiankohrn)

Bitte mitliefern, soweit möglich:

- betroffene Version / Commit
- Schritte zur Reproduktion
- Auswirkung (z. B. fremde Belege lesen, Sitzung übernehmen)

Wir bestätigen den Eingang in der Regel innerhalb weniger Tage und koordinieren eine Behebung, bevor Details öffentlich werden.

## Was wir besonders ernst nehmen

- Authentifizierung und Sitzungen (Cookie, `BUCHHALTUNG_SESSION_SECRET`)
- Zwei-Faktor, Passkeys, LDAP-Anbindung und Mail-Token (Einladung, Reset)
- Rechte zwischen Benutzer und Administrator
- Pfade und Uploads (Beleg-Uploads, DATEV-Export), SQL, XSS in der PWA
- Leak von `.env`, Datenbank, Belegordner oder Seed-Passwörtern
- Mitgelieferte Secrets (SMTP-, Azure-Schlüssel) in Issues oder PRs

## Betrieb

- `ADMIN_PASSWORT`, SMTP/Azure-Schlüssel und Session-Secret nur in `/etc/buchhaltung.env` (Rechte 640), nie ins Git
- Seed-Passwort nach dem ersten Login ändern (die App erzwingt das beim Erst-Login)
- HTTPS in Produktion
- Backups unter `/var/backups/buchhaltung/` und der Belegordner sind ebenso schützenswert wie die Datenbank
