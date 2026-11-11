# Changelog

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionierung nach [SemVer](https://semver.org/lang/de/).

## [Unreleased]

- Automatischer Belegimport aus einem eigenen Postfach (IMAP): ungesehene Mails werden abgerufen, Anhänge als Belege importiert, Mails als gelesen markiert oder in einen Erledigt-Ordner sortiert; Abruf per Timer alle 15 Minuten, von Hand in den Einstellungen oder per `python -m app.cli mailimport`
- Lokale Texterkennung (OCR) für alle Belege: Textteil wird beim Import geprüft, textlose PDFs und Bilder werden automatisch gelesen (Tesseract, Deutsch/Englisch); Status steht am Beleg, OCR lässt sich in der Belegbearbeitung erneut anstoßen
- Scan-Seite fürs Smartphone: Beleg fotografieren, Umrisse werden automatisch gesucht und lassen sich an Ecken nachziehen, mehrseitige Scans werden als PDF importiert
- Mobil angepasste Oberfläche (Navigation oben, Spalten untereinander, größere Trefferflächen) und App-Icons für Homescreen und PWA
- Zwei-Faktor per Authenticator-App (TOTP) mit Backup-Codes und eigenem MFA-Login-Schritt
- Passkeys (WebAuthn) zum Registrieren und passwortlosen Anmelden
- Optionale Anmeldung gegen LDAP/Active Directory
- Einladungen und Passwort-Resets per E-Mail mit Einmal-Links
- Audit-Protokoll (`audit_ereignisse`) für Anmeldungen, Konten und Sicherheitsänderungen
- Rate-Limits an anonymen Auth-Endpunkten

## [0.1.0] - 2026-11-10

Erste öffentliche Version von **Opentakt Rewe**.

- Rechnungen mit Positionen, Serienrechnungen, Storno, Mahnungen und Mailversand
- Kundenverwaltung
- Belegimport (PDF, Bild, CSV, camt) mit Erkennung von Partner, Betrag, Datum und Rechnungsnummer
- Kontoauszüge (N26, Amex, Miles & More, Volksbank) und automatische Zuordnung von Belegen zu Umsätzen
- E-Rechnung (ZUGFeRD/XRechnung) und EPC-QR-Code auf Rechnungen
- DATEV-Export (ZIP mit Belegen, Weiterverarbeitungsdatei Dok.-Nr. 9226961) und DATEV-Versand per E-Mail
- Stammdaten, Konten, Abrechnungskriterien und Geschäftspartner in den Einstellungen pflegbar
- Optionale Azure-KI zur Belegerkennung (nur auf Knopfdruck)
- Benutzerkonten mit Rollen (Admin, Benutzer); Seed-Admin muss beim ersten Login ein eigenes Passwort vergeben
- Opentakt-Farbwelt mit Hell- und Dunkelmodus
- Debian-Deploy (systemd, nginx, PostgreSQL-Backups)
- AGPL-3.0-or-later
