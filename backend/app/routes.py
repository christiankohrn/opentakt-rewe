import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import and_, case, func, nulls_last, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from webauthn import options_to_json
from webauthn.helpers import bytes_to_base64url

from app.audit import protokollieren
from app.auth import (
    authenticate,
    benutzer_dict,
    benutzername_norm,
    bump_session_rev,
    current_benutzer,
    require_admin,
    require_login,
    write_session,
)
from app.benutzer import MIN_PASSWORT, benutzer_aktualisieren, benutzer_anlegen, benutzer_loeschen, eigenes_passwort
from app.db import get_db
from app.ratelimit import (
    FORGOT_MAX,
    FORGOT_WINDOW,
    LOGIN_MAX,
    LOGIN_WINDOW,
    MFA_MAX,
    MFA_WINDOW,
    PASSKEY_MAX,
    PASSKEY_OPTIONS_MAX,
    PASSKEY_OPTIONS_WINDOW,
    PASSKEY_WINDOW,
    TOKEN_MAX,
    TOKEN_WINDOW,
    attempt,
    check,
    clear,
    client_key,
    record,
)
from app.security import hash_password
from app.totp import (
    backup_code_verbrauchen,
    backup_codes_erzeugen,
    backup_codes_uebrig,
    code_pruefen,
    neues_geheimnis,
    qr_svg_data_uri,
    totp_loeschen,
    totp_uri,
)
from app.webauthn import (
    anmelde_optionen,
    anmeldung_pruefen,
    credential_raw_id,
    registrierung_pruefen,
    registrierungs_optionen,
)
from app.zeit import utcnow
from app.zugangsmail import (
    RESET_WARTE_MINUTEN,
    MailFehler,
    benutzer_finden,
    frisches_token,
    smtp_bereit,
    zugangsmail_senden,
    zugangstoken_suchen,
)
from app.domain import (
    berechne,
    bereite_druck,
    kopiere_rechnung,
    format_rechnungsnummer,
    neue_rechnung,
    offene_serie,
    serie_lauf,
    setze_kunde,
    setze_wiedervorlage,
    setze_naechste_nummer,
    setze_zahlung,
    storniere,
    uebernimm_kopf,
    zaehler_holen,
    ersetze_positionen,
)
from app.kategorien import (
    kategorie_aktualisieren,
    kategorie_anlegen,
    kategorie_dict,
    kategorie_loeschen,
    kategorien_lesen,
    versand_optionen_lesen,
    versand_optionen_schreiben,
)
from app.mailer import SmtpFehlt, betreff, senden, smtp_pruefen
from app.models import Benutzer, Kategorie, Kunde, Passkey, Position, Rechnung
from app.pdf import mahnung_pdf, rechnung_pdf
from app.seller import stammdaten_dict, stammdaten_lesen, stammdaten_schreiben
from app.schemas import (
    BenutzerNeuIn,
    BenutzerPatchIn,
    DruckIn,
    KundeIn,
    KundeWahl,
    LoginIn,
    MfaIn,
    PasskeyOptionenIn,
    PasskeyRegistrierenIn,
    PasskeyUmbenennenIn,
    PasskeyVerifyIn,
    PasswortIn,
    TokenSetzenIn,
    TotpAktivierenIn,
    TotpDeaktivierenIn,
    VergessenIn,
    MailIn,
    NeueRechnungIn,
    KategorieIn,
    KategorieNeuIn,
    StammdatenIn,
    VersandOptionenIn,
    NummerIn,
    RechnungIn,
    AzureIn,
    PostfachIn,
    SmtpIn,
    WiedervorlageIn,
    ZahlungIn,
)
from app.serialize import geld, kunde_dict, rechnung_dict
from app.azure_ki import azure_lesen, azure_speichern, azure_testen
from app.mailimport import postfach_lesen, postfach_speichern, postfach_testen
from app.smtp_datei import smtp_lesen, smtp_speichern

router = APIRouter(prefix="/api")


def _kunde(session: Session, kunden_id: int) -> Kunde:
    kunde = session.get(Kunde, kunden_id)
    if kunde is None:
        raise HTTPException(status_code=404, detail="Kunde nicht gefunden.")
    return kunde


def _rechnung(session: Session, rechnungs_id: int) -> Rechnung:
    rechnung = session.scalar(
        select(Rechnung)
        .where(Rechnung.rechnungs_id == rechnungs_id)
        .options(selectinload(Rechnung.positionen), selectinload(Rechnung.kunde))
    )
    if rechnung is None:
        raise HTTPException(status_code=404, detail="Rechnung nicht gefunden.")
    return rechnung


def _storno_nr(session: Session, rechnung: Rechnung) -> str | None:
    if not rechnung.storno_zu_rechnung_id:
        return None
    original = session.get(Rechnung, rechnung.storno_zu_rechnung_id)
    return original.rechnungs_nr if original is not None else None


def _pdf_response(pdf: bytes, dateiname: str) -> Response:
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{dateiname}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/health")
def health() -> dict:
    return {"ok": True}


MFA_PENDING_KEY = "pending_mfa"
MFA_PENDING_TTL = 300  # Sekunden, die die Passwortprüfung vor dem 2FA-Schritt gilt
MFA_MAX_VERSUCHE = 6
WEBAUTHN_AUTH_KEY = "webauthn_auth"
WEBAUTHN_TTL = 300
WEBAUTHN_REG_KEY = "webauthn_reg"
WEBAUTHN_REG_TTL = 300


def _mfa_methoden(db: Session, benutzer: Benutzer) -> list[str]:
    methoden = ["totp"]
    if backup_codes_uebrig(db, benutzer) > 0:
        methoden.append("backup_code")
    return methoden


def _passkeys(db: Session, benutzer: Benutzer) -> list[Passkey]:
    return list(
        db.scalars(
            select(Passkey).where(Passkey.benutzer_id == benutzer.benutzer_id).order_by(Passkey.erstellt)
        )
    )


def _passkey_dict(passkey: Passkey) -> dict:
    return {
        "passkey_id": passkey.passkey_id,
        "name": passkey.name,
        "erstellt": passkey.erstellt.isoformat() if passkey.erstellt else None,
        "zuletzt_benutzt": passkey.zuletzt_benutzt.isoformat() if passkey.zuletzt_benutzt else None,
    }


def _passkey_anzahl(db: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    zeilen = db.execute(
        select(Passkey.benutzer_id, func.count()).where(Passkey.benutzer_id.in_(ids)).group_by(Passkey.benutzer_id)
    ).all()
    return {int(bid): int(anz) for bid, anz in zeilen}


def _jetzt_ts() -> int:
    from datetime import timezone

    return int(utcnow().replace(tzinfo=timezone.utc).timestamp())


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> dict:
    from app.seed import seed_if_empty

    key = client_key(request, "login")
    check(key, LOGIN_MAX, LOGIN_WINDOW)
    try:
        seed_if_empty(db)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    benutzer = authenticate(db, body.benutzername, body.password)
    if benutzer is None:
        record(key, LOGIN_WINDOW)
        raise HTTPException(status_code=401, detail="Anmeldung fehlgeschlagen.")
    clear(key)
    if benutzer.totp_aktiv and benutzer.totp_secret:
        request.session.clear()
        request.session[MFA_PENDING_KEY] = {
            "uid": benutzer.benutzer_id,
            "exp": _jetzt_ts() + MFA_PENDING_TTL,
            "tries": 0,
        }
        return {"mfa_erforderlich": True, "methoden": _mfa_methoden(db, benutzer)}
    request.session.clear()
    write_session(request, benutzer)
    protokollieren(db, "anmeldung", benutzer, "benutzer", benutzer.benutzer_id)
    return benutzer_dict(benutzer)


@router.post("/auth/mfa")
def mfa(body: MfaIn, request: Request, db: Session = Depends(get_db)) -> dict:
    key = client_key(request, "mfa")
    check(key, MFA_MAX, MFA_WINDOW)
    pending = request.session.get(MFA_PENDING_KEY)
    if not isinstance(pending, dict) or not pending.get("uid"):
        raise HTTPException(status_code=401, detail="Keine Anmeldung ausstehend. Bitte neu anmelden.")
    if int(pending.get("exp") or 0) < _jetzt_ts():
        request.session.clear()
        raise HTTPException(status_code=401, detail="Anmeldung abgelaufen. Bitte neu anmelden.")
    benutzer = db.get(Benutzer, int(pending["uid"]))
    if benutzer is None or not benutzer.aktiv or not benutzer.totp_aktiv:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Anmeldung fehlgeschlagen.")

    ok = code_pruefen(benutzer.totp_secret, body.code)
    per_backup = False
    if not ok:
        per_backup = backup_code_verbrauchen(db, benutzer, body.code)
        ok = per_backup
    if not ok:
        record(key, MFA_WINDOW)
        pending["tries"] = int(pending.get("tries") or 0) + 1
        if pending["tries"] >= MFA_MAX_VERSUCHE:
            request.session.clear()
            raise HTTPException(status_code=429, detail="Zu viele Versuche. Bitte neu anmelden.")
        request.session[MFA_PENDING_KEY] = pending
        raise HTTPException(status_code=401, detail="Code ungültig.")

    clear(key)
    request.session.clear()
    write_session(request, benutzer)
    protokollieren(
        db, "anmeldung", benutzer, "benutzer", benutzer.benutzer_id,
        json.dumps({"mfa": "backup_code" if per_backup else "totp"}),
    )
    return benutzer_dict(benutzer)


@router.post("/auth/passkey/optionen")
def passkey_optionen(body: PasskeyOptionenIn, request: Request, db: Session = Depends(get_db)) -> dict:
    attempt(client_key(request, "passkey-options"), PASSKEY_OPTIONS_MAX, PASSKEY_OPTIONS_WINDOW)
    passkeys: list[Passkey] = []
    if body.benutzername:
        key = benutzername_norm(body.benutzername)
        benutzer = db.scalar(select(Benutzer).where(func.lower(Benutzer.benutzername) == key))
        if benutzer is not None and benutzer.aktiv:
            passkeys = _passkeys(db, benutzer)
    optionen, _ = anmelde_optionen(request, passkeys)
    request.session[WEBAUTHN_AUTH_KEY] = {
        "challenge": bytes_to_base64url(optionen.challenge),
        "exp": _jetzt_ts() + WEBAUTHN_TTL,
    }
    return json.loads(options_to_json(optionen))


@router.post("/auth/passkey/verifizieren")
def passkey_verifizieren(body: PasskeyVerifyIn, request: Request, db: Session = Depends(get_db)) -> dict:
    key = client_key(request, "passkey")
    check(key, PASSKEY_MAX, PASSKEY_WINDOW)
    pending = request.session.get(WEBAUTHN_AUTH_KEY)
    if not isinstance(pending, dict) or not pending.get("challenge"):
        raise HTTPException(status_code=401, detail="Keine Passkey-Anmeldung ausstehend.")
    if int(pending.get("exp") or 0) < _jetzt_ts():
        request.session.clear()
        raise HTTPException(status_code=401, detail="Anmeldung abgelaufen. Bitte neu versuchen.")
    roh_id = credential_raw_id(body.credential)
    passkey = db.scalar(select(Passkey).where(Passkey.credential_id == roh_id)) if roh_id else None
    if passkey is None:
        record(key, PASSKEY_WINDOW)
        raise HTTPException(status_code=401, detail="Passkey unbekannt.")
    benutzer = db.get(Benutzer, passkey.benutzer_id)
    if benutzer is None or not benutzer.aktiv:
        record(key, PASSKEY_WINDOW)
        raise HTTPException(status_code=403, detail="Anmeldung nicht möglich.")
    try:
        neuer_zaehler = anmeldung_pruefen(request, body.credential, pending["challenge"], passkey)
    except Exception:
        record(key, PASSKEY_WINDOW)
        raise HTTPException(status_code=401, detail="Passkey-Anmeldung fehlgeschlagen.")
    passkey.sign_count = neuer_zaehler
    passkey.zuletzt_benutzt = utcnow()
    clear(key)
    request.session.clear()
    write_session(request, benutzer)
    protokollieren(
        db, "anmeldung", benutzer, "benutzer", benutzer.benutzer_id, json.dumps({"mfa": "passkey"})
    )
    return benutzer_dict(benutzer)


@router.post("/auth/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request, db: Session = Depends(get_db)) -> dict:
    return benutzer_dict(current_benutzer(request, db, allow_passwort_aendern=True))


@router.put("/auth/passwort")
def passwort_aendern(body: PasswortIn, request: Request, db: Session = Depends(get_db)) -> dict:
    benutzer = current_benutzer(request, db, allow_passwort_aendern=True)
    try:
        eigenes_passwort(db, benutzer, body.alt, body.neu)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    write_session(request, benutzer)
    protokollieren(db, "passwort.aendern", benutzer, "benutzer", benutzer.benutzer_id)
    return benutzer_dict(benutzer)


@router.post("/auth/vergessen")
def passwort_vergessen(body: VergessenIn, request: Request, db: Session = Depends(get_db)) -> dict:
    attempt(client_key(request, "forgot"), FORGOT_MAX, FORGOT_WINDOW)
    benutzer = benutzer_finden(db, body.kennung)
    if benutzer is not None and benutzer.aktiv and benutzer.auth_quelle == "local" and benutzer.email:
        if not frisches_token(db, benutzer, "reset", timedelta(minutes=RESET_WARTE_MINUTEN)):
            try:
                zugangsmail_senden(db, benutzer, "reset")
                protokollieren(db, "passwort.vergessen", None, "benutzer", benutzer.benutzer_id)
            except MailFehler:
                db.rollback()
    return {"ok": True}


@router.get("/auth/passwort-token")
def passwort_token_info(token: str, request: Request, db: Session = Depends(get_db)) -> dict:
    attempt(client_key(request, "password-token"), TOKEN_MAX, TOKEN_WINDOW)
    zeile = zugangstoken_suchen(db, token)
    if zeile is None:
        raise HTTPException(status_code=400, detail="Link ist ungültig oder abgelaufen.")
    benutzer = db.get(Benutzer, zeile.benutzer_id)
    if benutzer is None or not benutzer.aktiv:
        raise HTTPException(status_code=400, detail="Link ist ungültig oder abgelaufen.")
    return {
        "benutzername": benutzer.benutzername,
        "name": benutzer.name or "",
        "zweck": zeile.zweck,
    }


@router.post("/auth/passwort-token")
def passwort_token_einloesen(body: TokenSetzenIn, request: Request, db: Session = Depends(get_db)) -> dict:
    key = client_key(request, "password-token")
    check(key, TOKEN_MAX, TOKEN_WINDOW)
    zeile = zugangstoken_suchen(db, body.token)
    if zeile is None:
        record(key, TOKEN_WINDOW)
        raise HTTPException(status_code=400, detail="Link ist ungültig oder abgelaufen.")
    benutzer = db.get(Benutzer, zeile.benutzer_id)
    if benutzer is None or not benutzer.aktiv or benutzer.auth_quelle != "local":
        record(key, TOKEN_WINDOW)
        raise HTTPException(status_code=400, detail="Link ist ungültig oder abgelaufen.")
    if len(body.passwort or "") < MIN_PASSWORT:
        raise HTTPException(status_code=400, detail=f"Passwort braucht mindestens {MIN_PASSWORT} Zeichen.")
    clear(key)
    benutzer.passwort_hash = hash_password(body.passwort)
    benutzer.passwort_aendern = False
    zeile.benutzt_am = utcnow()
    bump_session_rev(benutzer)
    protokollieren(
        db,
        "passwort.reset" if zeile.zweck == "reset" else "passwort.einladung",
        benutzer,
        "benutzer",
        benutzer.benutzer_id,
    )
    request.session.clear()
    return {"ok": True}


@router.get("/benutzer")
def benutzer_liste(admin: Benutzer = Depends(require_admin), db: Session = Depends(get_db)) -> list:
    zeilen = db.scalars(select(Benutzer).order_by(Benutzer.benutzername)).all()
    anzahlen = _passkey_anzahl(db, [b.benutzer_id for b in zeilen])
    return [
        {**benutzer_dict(b), "passkey_anzahl": anzahlen.get(b.benutzer_id, 0)} for b in zeilen
    ]


@router.post("/benutzer")
def benutzer_neu(body: BenutzerNeuIn, admin: Benutzer = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    try:
        benutzer = benutzer_anlegen(
            db, body.benutzername, body.name, body.email, body.passwort, body.rolle, body.einladung
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    protokollieren(
        db, "benutzer.anlegen", admin, "benutzer", benutzer.benutzer_id,
        json.dumps({"benutzername": benutzer.benutzername, "rolle": benutzer.rolle}),
    )
    db.commit()
    mail_gesendet: bool | None = None
    mail_fehler: str | None = None
    if body.einladung:
        try:
            zugangsmail_senden(db, benutzer, "einladung")
            protokollieren(db, "benutzer.einladung", admin, "benutzer", benutzer.benutzer_id)
            db.commit()
            mail_gesendet = True
        except MailFehler as exc:
            db.rollback()
            mail_gesendet = False
            mail_fehler = str(exc)
    return {**benutzer_dict(benutzer), "mail_gesendet": mail_gesendet, "mail_fehler": mail_fehler}


@router.patch("/benutzer/{benutzer_id}")
def benutzer_patchen(
    benutzer_id: int,
    body: BenutzerPatchIn,
    admin: Benutzer = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        benutzer = benutzer_aktualisieren(
            db, benutzer_id, admin, body.name, body.email, body.rolle, body.aktiv, body.passwort
        )
    except ValueError as exc:
        status = 404 if "nicht gefunden" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from None
    protokollieren(db, "benutzer.aendern", admin, "benutzer", benutzer.benutzer_id)
    return benutzer_dict(benutzer)


@router.delete("/benutzer/{benutzer_id}")
def benutzer_entfernen(benutzer_id: int, admin: Benutzer = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    try:
        benutzer_loeschen(db, benutzer_id, admin)
    except ValueError as exc:
        status = 404 if "nicht gefunden" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from None
    protokollieren(db, "benutzer.loeschen", admin, "benutzer", benutzer_id)
    return {"geloescht": benutzer_id}


@router.post("/benutzer/{benutzer_id}/zugangsmail")
def benutzer_zugangsmail(benutzer_id: int, admin: Benutzer = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    benutzer = db.get(Benutzer, benutzer_id)
    if benutzer is None:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")
    try:
        zugangsmail_senden(db, benutzer, "einladung")
    except MailFehler as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    protokollieren(db, "benutzer.einladung", admin, "benutzer", benutzer.benutzer_id)
    return {"ok": True}


@router.get("/sicherheit")
def sicherheit_status(request: Request, db: Session = Depends(get_db)) -> dict:
    benutzer = current_benutzer(request, db)
    return {
        "totp_aktiv": bool(benutzer.totp_aktiv),
        "backup_codes_uebrig": backup_codes_uebrig(db, benutzer),
        "passwort_moeglich": benutzer.auth_quelle == "local",
        "passkeys": [_passkey_dict(p) for p in _passkeys(db, benutzer)],
    }


@router.post("/sicherheit/totp/einrichten")
def totp_einrichten(request: Request, db: Session = Depends(get_db)) -> dict:
    from app.branding import PRODUCT_NAME

    benutzer = current_benutzer(request, db)
    if benutzer.totp_aktiv:
        raise HTTPException(status_code=400, detail="Zwei-Faktor ist bereits aktiv. Erst deaktivieren.")
    secret = neues_geheimnis()
    benutzer.totp_secret = secret
    benutzer.totp_bestaetigt_am = None
    db.flush()
    uri = totp_uri(secret, benutzer.benutzername, PRODUCT_NAME)
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": qr_svg_data_uri(uri)}


@router.post("/sicherheit/totp/aktivieren")
def totp_aktivieren(body: TotpAktivierenIn, request: Request, db: Session = Depends(get_db)) -> dict:
    benutzer = current_benutzer(request, db)
    if benutzer.totp_aktiv:
        raise HTTPException(status_code=400, detail="Zwei-Faktor ist bereits aktiv.")
    if not benutzer.totp_secret:
        raise HTTPException(status_code=400, detail="Bitte zuerst die Einrichtung starten.")
    if not code_pruefen(benutzer.totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Code stimmt nicht. Bitte erneut versuchen.")
    benutzer.totp_aktiv = True
    benutzer.totp_bestaetigt_am = utcnow()
    codes = backup_codes_erzeugen(db, benutzer)
    protokollieren(db, "totp.aktivieren", benutzer, "benutzer", benutzer.benutzer_id)
    return {"backup_codes": codes}


@router.post("/sicherheit/totp/backup-codes")
def totp_backup_neu(body: MfaIn, request: Request, db: Session = Depends(get_db)) -> dict:
    benutzer = current_benutzer(request, db)
    if not benutzer.totp_aktiv or not benutzer.totp_secret:
        raise HTTPException(status_code=400, detail="Zwei-Faktor ist nicht aktiv.")
    if not (code_pruefen(benutzer.totp_secret, body.code) or backup_code_verbrauchen(db, benutzer, body.code)):
        raise HTTPException(status_code=400, detail="Code stimmt nicht.")
    codes = backup_codes_erzeugen(db, benutzer)
    protokollieren(db, "totp.backup_neu", benutzer, "benutzer", benutzer.benutzer_id)
    return {"backup_codes": codes}


@router.post("/sicherheit/totp/deaktivieren")
def totp_deaktivieren(body: TotpDeaktivierenIn, request: Request, db: Session = Depends(get_db)) -> dict:
    from app.security import verify_password

    benutzer = current_benutzer(request, db)
    if not benutzer.totp_aktiv:
        raise HTTPException(status_code=400, detail="Zwei-Faktor ist nicht aktiv.")
    if benutzer.auth_quelle == "local":
        if not body.passwort or not verify_password(body.passwort, benutzer.passwort_hash):
            raise HTTPException(status_code=400, detail="Aktuelles Passwort stimmt nicht.")
    if not body.code or not (
        code_pruefen(benutzer.totp_secret, body.code) or backup_code_verbrauchen(db, benutzer, body.code)
    ):
        raise HTTPException(status_code=400, detail="Bestätigungscode stimmt nicht.")
    totp_loeschen(db, benutzer)
    protokollieren(db, "totp.deaktivieren", benutzer, "benutzer", benutzer.benutzer_id)
    return {"ok": True}


@router.post("/sicherheit/passkeys/optionen")
def passkey_registrieren_optionen(request: Request, db: Session = Depends(get_db)) -> dict:
    benutzer = current_benutzer(request, db)
    optionen, _ = registrierungs_optionen(
        request, benutzer.benutzer_id, benutzer.benutzername, benutzer.name, _passkeys(db, benutzer)
    )
    request.session[WEBAUTHN_REG_KEY] = {
        "challenge": bytes_to_base64url(optionen.challenge),
        "exp": _jetzt_ts() + WEBAUTHN_REG_TTL,
    }
    return json.loads(options_to_json(optionen))


@router.post("/sicherheit/passkeys/verifizieren")
def passkey_registrieren_verifizieren(
    body: PasskeyRegistrierenIn, request: Request, db: Session = Depends(get_db)
) -> dict:
    benutzer = current_benutzer(request, db)
    pending = request.session.get(WEBAUTHN_REG_KEY)
    if not isinstance(pending, dict) or not pending.get("challenge"):
        raise HTTPException(status_code=400, detail="Keine Passkey-Einrichtung ausstehend.")
    if int(pending.get("exp") or 0) < _jetzt_ts():
        request.session.pop(WEBAUTHN_REG_KEY, None)
        raise HTTPException(status_code=400, detail="Einrichtung abgelaufen. Bitte erneut versuchen.")
    try:
        cred_id, public_key, sign_count, _ = registrierung_pruefen(request, body.credential, pending["challenge"])
    except Exception:
        raise HTTPException(status_code=400, detail="Passkey konnte nicht überprüft werden.")
    request.session.pop(WEBAUTHN_REG_KEY, None)
    if db.scalar(select(Passkey).where(Passkey.credential_id == cred_id)):
        raise HTTPException(status_code=400, detail="Dieser Passkey ist bereits registriert.")
    transports = None
    antwort = body.credential.get("response") if isinstance(body.credential, dict) else None
    if isinstance(antwort, dict) and isinstance(antwort.get("transports"), list):
        transports = ",".join(str(t) for t in antwort["transports"])[:120]
    name = (body.name or "Passkey").strip()[:120] or "Passkey"
    passkey = Passkey(
        benutzer_id=benutzer.benutzer_id,
        credential_id=cred_id,
        public_key=public_key,
        sign_count=sign_count,
        transports=transports,
        name=name,
        erstellt=utcnow(),
    )
    db.add(passkey)
    db.flush()
    protokollieren(db, "passkey.registrieren", benutzer, "benutzer", benutzer.benutzer_id)
    return _passkey_dict(passkey)


@router.get("/sicherheit/passkeys")
def passkey_liste(request: Request, db: Session = Depends(get_db)) -> list:
    benutzer = current_benutzer(request, db)
    return [_passkey_dict(p) for p in _passkeys(db, benutzer)]


@router.patch("/sicherheit/passkeys/{passkey_id}")
def passkey_umbenennen(
    passkey_id: int, body: PasskeyUmbenennenIn, request: Request, db: Session = Depends(get_db)
) -> dict:
    benutzer = current_benutzer(request, db)
    passkey = db.get(Passkey, passkey_id)
    if passkey is None or passkey.benutzer_id != benutzer.benutzer_id:
        raise HTTPException(status_code=404, detail="Passkey nicht gefunden.")
    passkey.name = body.name.strip()[:120] or "Passkey"
    db.flush()
    return _passkey_dict(passkey)


@router.delete("/sicherheit/passkeys/{passkey_id}")
def passkey_loeschen(passkey_id: int, request: Request, db: Session = Depends(get_db)) -> dict:
    benutzer = current_benutzer(request, db)
    passkey = db.get(Passkey, passkey_id)
    if passkey is None or passkey.benutzer_id != benutzer.benutzer_id:
        raise HTTPException(status_code=404, detail="Passkey nicht gefunden.")
    db.delete(passkey)
    protokollieren(db, "passkey.loeschen", benutzer, "benutzer", benutzer.benutzer_id)
    return {"ok": True}


@router.get("/kunden")
def kunden(q: str = "", db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> list:
    stmt = select(Kunde).order_by(Kunde.name1, Kunde.kunden_id)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Kunde.name1.ilike(like), Kunde.ort.ilike(like), Kunde.email.ilike(like)))
    return [kunde_dict(kunde) for kunde in db.scalars(stmt).all()]


@router.post("/kunden")
def kunde_anlegen(body: KundeIn, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    kunde = Kunde(**body.model_dump())
    db.add(kunde)
    db.flush()
    return kunde_dict(kunde)


@router.put("/kunden/{kunden_id}")
def kunde_speichern(kunden_id: int, body: KundeIn, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    kunde = _kunde(db, kunden_id)
    for feld, wert in body.model_dump().items():
        setattr(kunde, feld, wert)
    db.flush()
    return kunde_dict(kunde)


@router.delete("/kunden/{kunden_id}")
def kunde_loeschen(kunden_id: int, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    kunde = _kunde(db, kunden_id)
    try:
        db.delete(kunde)
        db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Kunde hat noch Rechnungen.") from None
    return {"ok": True}


def _entwurf():
    return or_(Rechnung.rechnungs_nr.is_(None), Rechnung.rechnungs_nr == "")


def rechnungen_filtern(ansicht: str, name: str, position: str, kunde_id: int | None):
    stmt = select(Rechnung)
    if kunde_id is not None:
        stmt = stmt.where(Rechnung.kunde_id == kunde_id)
    if name.strip():
        like = f"%{name.strip()}%"
        stmt = stmt.where(or_(Rechnung.name1.ilike(like), Rechnung.rechnungs_nr.ilike(like)))
    if position.strip():
        like = f"%{position.strip()}%"
        treffer = select(Position.rechnung_id).where(or_(Position.bezeichnung.ilike(like), Position.freitext.ilike(like)))
        stmt = stmt.where(Rechnung.rechnungs_id.in_(treffer))
    if ansicht == "archiv":
        stmt = stmt.where(Rechnung.archiv.is_(True))
    elif ansicht != "alle":
        stmt = stmt.where(Rechnung.archiv.is_(False), or_(_entwurf(), Rechnung.bezahlt < Rechnung.brutto))
    return stmt


_SPALTEN = {"", "nummer", "datum", "kunde", "brutto", "bezahlt"}


def rechnungen_sortieren(stmt, ansicht: str, spalte: str, richtung: str):
    absteigend = richtung != "auf"
    felder = {
        "nummer": Rechnung.rechnungs_nr,
        "datum": Rechnung.datum,
        "kunde": Rechnung.name1,
        "brutto": Rechnung.brutto,
        "bezahlt": Rechnung.bezahlt,
    }
    if spalte in felder:
        spalte_sort = felder[spalte].desc() if absteigend else felder[spalte].asc()
        if spalte == "nummer":
            spalte_sort = nulls_last(spalte_sort)
        return stmt.order_by(spalte_sort, Rechnung.rechnungs_id.desc())
    nummer = nulls_last(Rechnung.rechnungs_nr.desc())
    if ansicht == "aktuell":
        entwurf_zuerst = case((_entwurf(), 0), else_=1)
        return stmt.order_by(entwurf_zuerst, nummer, Rechnung.rechnungs_id.desc())
    return stmt.order_by(nummer, Rechnung.rechnungs_id.desc())


@router.get("/optionen/rechnungsnummer")
def rechnungsnummer_lesen(db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    option = zaehler_holen(db)
    return {"naechste": format_rechnungsnummer(date.today(), int(option.e_int) + 1)}


@router.put("/optionen/rechnungsnummer")
def rechnungsnummer_schreiben(body: NummerIn, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    option = zaehler_holen(db)
    try:
        naechste = setze_naechste_nummer(option, body.naechste, date.today())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    db.flush()
    return {"naechste": naechste}


@router.get("/kategorien")
def kategorien(db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> list:
    return [kategorie_dict(kategorie) for kategorie in kategorien_lesen(db)]


@router.put("/kategorien/{schluessel}")
def kategorie_setzen(schluessel: str, body: KategorieIn, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    try:
        kategorie = kategorie_aktualisieren(
            db,
            schluessel,
            body.name,
            body.datev_email,
            body.weiterverarbeitung,
            body.iban,
            body.bic,
            body.neuer_schluessel,
        )
    except ValueError as exc:
        status = 404 if "nicht gefunden" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from None
    return kategorie_dict(kategorie)


@router.post("/kategorien")
def kategorie_neu(body: KategorieNeuIn, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    try:
        kategorie = kategorie_anlegen(
            db,
            body.name,
            body.schluessel,
            body.datev_email,
            body.weiterverarbeitung,
            body.iban,
            body.bic,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return kategorie_dict(kategorie)


@router.get("/optionen/versand")
def versand_optionen_anzeigen(db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    return versand_optionen_lesen(db)


@router.put("/optionen/versand")
def versand_optionen_setzen(body: VersandOptionenIn, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    try:
        return versand_optionen_schreiben(db, body.stb_email, body.ausgang_email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/optionen/stammdaten")
def stammdaten_anzeigen(db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    return stammdaten_dict(stammdaten_lesen(db))


@router.put("/optionen/stammdaten")
def stammdaten_setzen(body: StammdatenIn, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    gespeichert = stammdaten_schreiben(db, body.model_dump())
    return stammdaten_dict(gespeichert)


@router.delete("/kategorien/{schluessel}")
def kategorie_entfernen(schluessel: str, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    try:
        kategorie_loeschen(db, schluessel)
    except ValueError as exc:
        status = 404 if "nicht gefunden" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from None
    return {"geloescht": schluessel}


@router.get("/einstellungen/smtp")
def smtp_anzeigen(_: Benutzer = Depends(require_login)) -> dict:
    return smtp_lesen()


@router.put("/einstellungen/smtp")
def smtp_setzen(body: SmtpIn, _: Benutzer = Depends(require_login)) -> dict:
    try:
        return smtp_speichern(body.host, body.port, body.benutzer, body.absender, body.tls, body.passwort)
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="SMTP-Datei fehlt.") from None
    except PermissionError:
        raise HTTPException(status_code=503, detail="SMTP-Datei ist nicht beschreibbar.") from None
    except OSError:
        raise HTTPException(status_code=503, detail="SMTP-Datei ist nicht beschreibbar.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/einstellungen/azure")
def azure_anzeigen(_: Benutzer = Depends(require_login)) -> dict:
    return azure_lesen()


@router.put("/einstellungen/azure")
def azure_setzen(body: AzureIn, _: Benutzer = Depends(require_login)) -> dict:
    try:
        return azure_speichern(body.endpoint, body.deployment, body.schluessel)
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Azure-Datei fehlt.") from None
    except PermissionError:
        raise HTTPException(status_code=503, detail="Azure-Datei ist nicht beschreibbar.") from None
    except OSError:
        raise HTTPException(status_code=503, detail="Azure-Datei ist nicht beschreibbar.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/einstellungen/azure/test")
def azure_verbindung(_: Benutzer = Depends(require_login)) -> dict:
    try:
        return azure_testen()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.get("/einstellungen/postfach")
def postfach_anzeigen(_: Benutzer = Depends(require_login)) -> dict:
    return postfach_lesen()


@router.put("/einstellungen/postfach")
def postfach_setzen(body: PostfachIn, session: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    from app.belege import _quelle_gueltig

    if not _quelle_gueltig(session, (body.quelle or "").strip() or "eingang"):
        raise HTTPException(status_code=400, detail=f"Unbekannte Quelle {body.quelle}.")
    try:
        return postfach_speichern(
            body.host, body.port, body.benutzer, body.ordner, body.erledigt, body.quelle, body.tls, body.passwort
        )
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Postfach-Datei fehlt.") from None
    except PermissionError:
        raise HTTPException(status_code=503, detail="Postfach-Datei ist nicht beschreibbar.") from None
    except OSError:
        raise HTTPException(status_code=503, detail="Postfach-Datei ist nicht beschreibbar.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/einstellungen/postfach/test")
def postfach_verbindung(_: Benutzer = Depends(require_login)) -> dict:
    try:
        return postfach_testen()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.get("/rechnungen")
def rechnungen(
    ansicht: str = "aktuell",
    name: str = "",
    position: str = "",
    kunde_id: int | None = None,
    spalte: str = "",
    richtung: str = "ab",
    offset: int = 0,
    limit: int = 40,
    db: Session = Depends(get_db),
    _: Benutzer = Depends(require_login),
) -> dict:
    if ansicht not in {"aktuell", "alle", "archiv"}:
        raise HTTPException(status_code=400, detail="Ansicht ist aktuell, alle oder archiv.")
    if spalte not in _SPALTEN or richtung not in {"auf", "ab"}:
        raise HTTPException(status_code=400, detail="Sortierung ist ungültig.")
    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(status_code=400, detail="Seite ist ungültig.")
    basis = rechnungen_filtern(ansicht, name, position, kunde_id)
    unter = basis.subquery()
    gesamt = db.scalar(select(func.count()).select_from(unter)) or 0
    summe, offen_betrag = db.execute(select(
        func.coalesce(func.sum(unter.c.brutto), 0),
        func.coalesce(func.sum(unter.c.brutto - unter.c.bezahlt), 0),
    )).one()
    stmt = (
        rechnungen_sortieren(basis, ansicht, spalte, richtung)
        .options(selectinload(Rechnung.kunde))
        .offset(offset)
        .limit(limit)
    )
    return {
        "zeilen": [rechnung_dict(rechnung) for rechnung in db.scalars(stmt).all()],
        "gesamt": int(gesamt),
        "sichtbar_summe": geld(summe),
        "sichtbar_offen": geld(offen_betrag),
    }


@router.get("/rechnungen/summen")
def rechnungen_summen(
    name: str = "",
    position: str = "",
    kunde_id: int | None = None,
    db: Session = Depends(get_db),
    _: Benutzer = Depends(require_login),
) -> dict:
    basis = rechnungen_filtern("alle", name, position, kunde_id).subquery()
    entwurf = or_(basis.c.rechnungs_nr.is_(None), basis.c.rechnungs_nr == "")
    nicht_archiv = basis.c.archiv.is_(False)
    offen = func.coalesce(func.sum(case(
        (and_(nicht_archiv, ~entwurf), basis.c.brutto - basis.c.bezahlt),
        else_=0,
    )), 0)
    zu_berechnen = func.coalesce(func.sum(case(
        (and_(nicht_archiv, entwurf), basis.c.brutto),
        else_=0,
    )), 0)
    zeile = db.execute(select(offen, zu_berechnen)).one()
    return {"offen": geld(zeile[0]), "zu_berechnen": geld(zeile[1])}


@router.post("/rechnungen")
def rechnung_anlegen(body: NeueRechnungIn, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    kunde = _kunde(db, body.kunde_id) if body.kunde_id else None
    rechnung = neue_rechnung(db, kunde, date.today())
    db.flush()
    return rechnung_dict(rechnung, mit_positionen=True)


@router.get("/rechnungen/{rechnungs_id}/vorschau")
def rechnung_vorschau(rechnungs_id: int, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> Response:
    rechnung = _rechnung(db, rechnungs_id)
    berechne(rechnung)
    original = db.get(Rechnung, rechnung.storno_zu_rechnung_id) if rechnung.storno_zu_rechnung_id else None
    pdf = rechnung_pdf(rechnung, original, stammdaten=stammdaten_lesen(db))
    name = rechnung.rechnungs_nr or f"Entwurf_{rechnung.rechnungs_id}"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="Rechnung_{name}.pdf"', "Cache-Control": "no-store"},
    )


@router.get("/rechnungen/{rechnungs_id}")
def rechnung_lesen(rechnungs_id: int, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    rechnung = _rechnung(db, rechnungs_id)
    return rechnung_dict(rechnung, mit_positionen=True, storno_zu_nr=_storno_nr(db, rechnung))


@router.put("/rechnungen/{rechnungs_id}")
def rechnung_speichern(rechnungs_id: int, body: RechnungIn, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    rechnung = _rechnung(db, rechnungs_id)
    uebernimm_kopf(rechnung, body)
    if body.kunde_id is not None:
        _kunde(db, body.kunde_id)
        rechnung.kunde_id = body.kunde_id
    ersetze_positionen(db, rechnung, body.positionen)
    db.flush()
    rechnung = _rechnung(db, rechnungs_id)
    return rechnung_dict(rechnung, mit_positionen=True, storno_zu_nr=_storno_nr(db, rechnung))


@router.delete("/rechnungen/{rechnungs_id}")
def rechnung_loeschen(rechnungs_id: int, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    rechnung = _rechnung(db, rechnungs_id)
    try:
        db.delete(rechnung)
        db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Rechnung wird noch von einer anderen Rechnung referenziert.") from None
    return {"ok": True}


@router.post("/rechnungen/{rechnungs_id}/kunde")
def rechnung_kunde(rechnungs_id: int, body: KundeWahl, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    rechnung = _rechnung(db, rechnungs_id)
    kunde = _kunde(db, body.kunde_id) if body.kunde_id else None
    setze_kunde(rechnung, kunde, body.ueberschreiben)
    db.flush()
    return rechnung_dict(_rechnung(db, rechnungs_id), mit_positionen=True, storno_zu_nr=_storno_nr(db, rechnung))


@router.post("/rechnungen/{rechnungs_id}/kopie")
def rechnung_kopie(rechnungs_id: int, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    quelle = _rechnung(db, rechnungs_id)
    neu = kopiere_rechnung(db, quelle, date.today(), positionen=True)
    return rechnung_dict(neu, mit_positionen=True)


@router.post("/rechnungen/{rechnungs_id}/storno")
def rechnung_storno(rechnungs_id: int, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    quelle = _rechnung(db, rechnungs_id)
    neu = storniere(db, quelle, date.today())
    return rechnung_dict(neu, mit_positionen=True, storno_zu_nr=quelle.rechnungs_nr)


@router.post("/rechnungen/{rechnungs_id}/zahlung")
def rechnung_zahlung(rechnungs_id: int, body: ZahlungIn, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    rechnung = _rechnung(db, rechnungs_id)
    setze_zahlung(rechnung, body.betrag, body.datum)
    db.flush()
    return rechnung_dict(rechnung, mit_positionen=True, storno_zu_nr=_storno_nr(db, rechnung))


@router.post("/rechnungen/{rechnungs_id}/wiedervorlage")
def rechnung_wiedervorlage(rechnungs_id: int, body: WiedervorlageIn, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    rechnung = _rechnung(db, rechnungs_id)
    setze_wiedervorlage(rechnung, body.termin, body.monate)
    db.flush()
    return rechnung_dict(rechnung, mit_positionen=True, storno_zu_nr=_storno_nr(db, rechnung))


@router.post("/rechnungen/{rechnungs_id}/drucken")
def rechnung_drucken(rechnungs_id: int, body: DruckIn, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> Response:
    rechnung = _rechnung(db, rechnungs_id)
    berechne(rechnung)
    bereite_druck(db, rechnung, date.today(), body.datum_auf_heute)
    original = db.get(Rechnung, rechnung.storno_zu_rechnung_id) if rechnung.storno_zu_rechnung_id else None
    pdf = rechnung_pdf(rechnung, original, stammdaten=stammdaten_lesen(db))
    db.commit()
    return _pdf_response(pdf, f"Rechnung_{rechnung.rechnungs_nr}.pdf")


@router.post("/rechnungen/{rechnungs_id}/mahnung")
def rechnung_mahnung(rechnungs_id: int, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> Response:
    rechnung = _rechnung(db, rechnungs_id)
    berechne(rechnung)
    pdf = mahnung_pdf(rechnung, date.today(), stammdaten=stammdaten_lesen(db))
    name = rechnung.rechnungs_nr or str(rechnung.rechnungs_id)
    return _pdf_response(pdf, f"Mahnung_{name}.pdf")


@router.post("/rechnungen/{rechnungs_id}/senden")
def rechnung_senden(rechnungs_id: int, body: MailIn, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    try:
        smtp_pruefen()
    except SmtpFehlt as exc:
        raise HTTPException(
            status_code=503,
            detail="SMTP ist nicht konfiguriert. Fehlende Variablen: " + ", ".join(exc.namen) + ". Es wurde nichts gespeichert.",
        ) from None
    rechnung = _rechnung(db, rechnungs_id)
    if not rechnung.rechnungs_nr:
        raise HTTPException(status_code=400, detail="Die Rechnung hat noch keine Nummer. Bitte zuerst drucken.")
    email = rechnung.kunde.email if rechnung.kunde is not None else None
    if not (email or "").strip():
        raise HTTPException(status_code=400, detail="Keine E-Mail-Adresse beim Kunden.")
    berechne(rechnung)
    stamm = stammdaten_lesen(db)
    if body.art == "mahnung":
        pdf = mahnung_pdf(rechnung, date.today(), stammdaten=stamm)
        dateiname = f"Mahnung_{rechnung.rechnungs_nr}.pdf"
    else:
        original = db.get(Rechnung, rechnung.storno_zu_rechnung_id) if rechnung.storno_zu_rechnung_id else None
        pdf = rechnung_pdf(rechnung, original, stammdaten=stamm)
        dateiname = f"Rechnung_{rechnung.rechnungs_nr}.pdf"
    try:
        senden(email.strip(), body.art, rechnung.rechnungs_nr, pdf, dateiname)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return {"ok": True, "betreff": betreff(body.art, rechnung.rechnungs_nr), "an": email.strip()}


@router.post("/rechnungen/{rechnungs_id}/datev")
def rechnung_an_datev(rechnungs_id: int, db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    from app.belege import rechnung_an_datev_senden

    try:
        an = rechnung_an_datev_senden(db, rechnungs_id)
    except SmtpFehlt as exc:
        raise HTTPException(status_code=503, detail=f"SMTP fehlt: {exc}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return {"ok": True, "an": an, "rechnung": rechnung_dict(_rechnung(db, rechnungs_id))}


@router.get("/serie/faellig")
def serie_faellig(db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> list:
    return [rechnung_dict(rechnung) for rechnung in offene_serie(db)]


@router.post("/serie/lauf")
def serie_jetzt(db: Session = Depends(get_db), _: Benutzer = Depends(require_login)) -> dict:
    erzeugt = serie_lauf(db, date.today())
    return {"anzahl": len(erzeugt), "rechnungs_ids": [rechnung.rechnungs_id for rechnung in erzeugt]}


