import json
import sys
from datetime import date
from pathlib import Path

from app.belege import importiere_ordner
from app.db import get_session, init_engine
from app.domain import serie_lauf
from app.migration import migrationen_anwenden


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"serie", "belege", "mailimport"}:
        raise SystemExit("Verwendung: python -m app.cli serie | belege ORDNER | mailimport")
    migrationen_anwenden()
    init_engine()
    if sys.argv[1] == "serie":
        with get_session() as session:
            erzeugt = serie_lauf(session, date.today())
            session.commit()
            print(f"{len(erzeugt)} Rechnungen erzeugt")
        return
    if sys.argv[1] == "mailimport":
        from app.belege import zuordnen
        from app.config import get_settings
        from app.mailimport import abrufen

        if not get_settings().imap_host.strip():
            raise SystemExit("Kein Postfach konfiguriert (IMAP_HOST fehlt).")
        with get_session() as session:
            try:
                ergebnis = abrufen(session)
            except (ValueError, RuntimeError) as exc:
                raise SystemExit(str(exc)) from None
            ergebnis["zugeordnet"] = zuordnen(session)
            session.commit()
            print(json.dumps(ergebnis, ensure_ascii=False))
        return
    if len(sys.argv) < 3:
        raise SystemExit("Verwendung: python -m app.cli belege ORDNER")
    wurzel = Path(sys.argv[2])
    with get_session() as session:
        ergebnis = importiere_ordner(session, wurzel)
        session.commit()
        print(json.dumps(ergebnis, ensure_ascii=False))


if __name__ == "__main__":
    main()
