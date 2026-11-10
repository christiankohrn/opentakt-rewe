"""SDF nach JSON, JSON nach PostgreSQL. Dump und SDF bleiben außerhalb von Git."""

import argparse
import json
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select, text

from app.db import get_session, init_engine
from app.models import Kunde, Option, Position, Rechnung

DEFAULT_DLL = ""
DEFAULT_NATIVE = ""


def export_sdf(sdf: Path, out: Path, dll: Path, native: Path) -> None:
    script = Path(__file__).with_name("export_sdf.ps1")
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Sdf",
            str(sdf),
            "-Dll",
            str(dll),
            "-Native",
            str(native),
            "-Out",
            str(out),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "SDF-Export fehlgeschlagen").strip()
        raise SystemExit(message)
    if proc.stdout.strip():
        print(proc.stdout.strip())


def _read_jsonl(path: Path) -> dict[str, list]:
    buckets = {name: [] for name in ("kunden", "rechnungen", "positionen", "serienpositionen", "optionen")}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            buckets[item["table"]].append(item["row"])
    return buckets


def _text(value) -> str:
    if value is None:
        return ""
    return str(value)


def _optional(value) -> str | None:
    if value is None:
        return None
    text_value = str(value)
    return text_value if text_value.strip() else None


def _blank_nr(value) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _dec(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def _dec_or_none(value) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _flag(value) -> bool:
    if isinstance(value, bool):
        return value
    return value in (1, "1", "true", "True")


def _date(value) -> date | None:
    if value is None or value == "":
        return None
    return date.fromisoformat(str(value)[:10])


def _int_or_none(value) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _leeren(session) -> None:
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        session.execute(text(
            "TRUNCATE positionen, rechnungen, kunden, optionen RESTART IDENTITY CASCADE"
        ))
        return
    session.execute(text("PRAGMA foreign_keys=OFF"))
    session.execute(text("DELETE FROM positionen"))
    session.execute(text("DELETE FROM rechnungen"))
    session.execute(text("DELETE FROM kunden"))
    session.execute(text("DELETE FROM optionen"))
    session.execute(text("PRAGMA foreign_keys=ON"))


def _setval(session, table: str, column: str) -> None:
    bind = session.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    max_id = session.scalar(text(f"SELECT MAX({column}) FROM {table}"))
    sequence = session.scalar(text("SELECT pg_get_serial_sequence(:table, :column)"), {"table": table, "column": column})
    if not sequence:
        return
    if max_id is None:
        session.execute(text("SELECT setval(:sequence, 1, false)"), {"sequence": sequence})
    else:
        session.execute(text("SELECT setval(:sequence, :max_id, true)"), {"sequence": sequence, "max_id": int(max_id)})


def load_json(path: Path, replace: bool) -> None:
    daten = _read_jsonl(path)
    init_engine()
    with get_session() as session:
        vorhanden = session.scalar(select(func.count()).select_from(Rechnung)) or 0
        if vorhanden and not replace:
            raise SystemExit(
                "Datenbank enthält bereits Rechnungen. Import mit --replace erneut ausführen, um sie zu ersetzen."
            )
        _leeren(session)
        for row in daten["kunden"]:
            session.add(Kunde(
                kunden_id=int(row["KundenId"]),
                name1=_text(row.get("Name1")),
                name2=_text(row.get("Name2")),
                name3=_text(row.get("Name3")),
                email=_optional(row.get("Email")),
                tel1=_optional(row.get("Tel1")),
                tel2=_optional(row.get("Tel2")),
                tel3=_optional(row.get("Tel3")),
                fax=_optional(row.get("Fax")),
                strasse=_text(row.get("Strasse")),
                plz=_text(row.get("PLZ")),
                ort=_text(row.get("Ort")),
                stundensatz=_dec(row.get("Stundensatz")),
                umsatzsteuer_id=_text(row.get("UmsatzsteuerID")),
                keine_mehrwertsteuer=_flag(row.get("KeineMehrwertsteuer")),
            ))
        session.flush()
        for row in sorted(daten["rechnungen"], key=lambda item: int(item["RechnungsId"])):
            session.add(Rechnung(
                rechnungs_id=int(row["RechnungsId"]),
                datum=_date(row.get("Datum")),
                kunde_id=_int_or_none(row.get("KundeKundenId")),
                name1=_text(row.get("Name1")),
                name2=_text(row.get("Name2")),
                name3=_text(row.get("Name3")),
                strasse=_text(row.get("Strasse")),
                plz=_text(row.get("PLZ")),
                ort=_text(row.get("Ort")),
                rechnungs_nr=_blank_nr(row.get("RechnungsNr")),
                leistungszeitraum=_text(row.get("Leistungszeitraum")),
                umsatzsteuer_id=_text(row.get("UmsatzsteuerID")),
                keine_mehrwertsteuer=_flag(row.get("KeineMehrwertsteuer")),
                storno_zu_rechnung_id=_int_or_none(row.get("StornoZuRechnung")),
                archiv=_flag(row.get("Archiv")),
                stornierte_rechnung_id=_int_or_none(row.get("StornierteRechnung_RechnungsId")),
                wiedervorlage_termin=_date(row.get("WiedervorlageTermin")),
                wiederholung_monate=_int_or_none(row.get("WiederholungMonate")),
                notizen_intern=_optional(row.get("NotizenIntern")),
                brutto=_dec(row.get("Brutto")),
                netto=_dec(row.get("Netto")),
                bezahlt=_dec(row.get("Bezahlt")),
                bezahlt_am=_date(row.get("BezahltAm")),
                gedruckt_buchhaltung=_flag(row.get("GedrucktBuchhaltung")),
            ))
        session.flush()
        for row in daten["positionen"]:
            session.add(Position(
                positionen_id=int(row["PositionenId"]),
                rechnung_id=int(row["RechnungRechnungsId"]),
                menge=_dec(row.get("Menge")),
                preis=_dec(row.get("Preis")),
                naechster_preis=_dec_or_none(row.get("NaechsterPreis")),
                naechste_menge=_dec_or_none(row.get("NaechsteMenge")),
                einmalig=_flag(row.get("Einmalig")),
                bezeichnung=_text(row.get("Bezeichnung")),
                freitext=_text(row.get("Freitext")),
                mengeneinheit=_text(row.get("Mengeneinheit")),
                pos_nr=_int_or_none(row.get("PosNr")),
            ))
        for row in daten["optionen"]:
            session.add(Option(
                optionen_id=int(row["OptionenId"]),
                einstellung=_text(row.get("Einstellung")),
                e_int=int(row.get("eINT") or 0),
                e_decimal=_dec(row.get("eDECIMAL")),
                e_string=_text(row.get("eSTRING")),
                e_bool=_flag(row.get("eBOOL")),
            ))
        session.flush()
        zaehler = session.get(Option, 1)
        if zaehler is None or zaehler.einstellung != "Rechnungsnummer":
            raise SystemExit("Zähler Rechnungsnummer mit OptionenId 1 fehlt im Import.")
        for table, column in (
            ("kunden", "kunden_id"),
            ("rechnungen", "rechnungs_id"),
            ("positionen", "positionen_id"),
            ("optionen", "optionen_id"),
        ):
            _setval(session, table, column)
        session.commit()
        print(
            "kunden={k} rechnungen={r} positionen={p} optionen={o} zaehler={z}".format(
                k=len(daten["kunden"]),
                r=len(daten["rechnungen"]),
                p=len(daten["positionen"]),
                o=len(daten["optionen"]),
                z=zaehler.e_int,
            )
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.importer")
    sub = parser.add_subparsers(dest="cmd", required=True)
    export = sub.add_parser("export")
    export.add_argument("--sdf", required=True)
    export.add_argument("--out", required=True)
    export.add_argument("--dll", default=DEFAULT_DLL, help="Pfad zu System.Data.SqlServerCe.dll")
    export.add_argument("--native", default=DEFAULT_NATIVE, help="Ordner mit den nativen SQL-CE-DLLs (amd64/x86)")
    load = sub.add_parser("load")
    load.add_argument("--json", required=True)
    load.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "export":
        if not args.dll or not args.native:
            raise SystemExit("Bitte --dll und --native mit den Pfaden der SQL-CE-Bibliothek angeben.")
        export_sdf(Path(args.sdf), Path(args.out), Path(args.dll), Path(args.native))
    else:
        load_json(Path(args.json), args.replace)


if __name__ == "__main__":
    main(sys.argv[1:])
