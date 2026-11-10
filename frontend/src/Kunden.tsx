import { useEffect, useRef, useState, type FormEvent, type MouseEvent } from "react";
import { ApiFehler, api, datumDE, geld } from "./api";
import { DatenListe, zeilenWahl, type Sortierung } from "./liste";
import { LinkIntern, gehe } from "./nav";
import { PdfVorschau } from "./vorschau";

type Kunde = {
  kunden_id: number;
  name1: string;
  name2: string;
  name3: string;
  email: string | null;
  tel1: string | null;
  tel2: string | null;
  tel3: string | null;
  fax: string | null;
  strasse: string;
  plz: string;
  ort: string;
  stundensatz: string;
  umsatzsteuer_id: string;
  keine_mehrwertsteuer: boolean;
};

type RechnungKurz = {
  rechnungs_id: number;
  datum: string;
  name1: string;
  rechnungs_nr: string | null;
  archiv: boolean;
  netto: string;
  brutto: string;
  bezahlt: string;
  bezahlt_am: string | null;
  wiedervorlage_termin: string | null;
  wiederholung_monate: number | null;
};

const leer = (): Kunde => ({
  kunden_id: 0,
  name1: "",
  name2: "",
  name3: "",
  email: "",
  tel1: "",
  tel2: "",
  tel3: "",
  fax: "",
  strasse: "",
  plz: "",
  ort: "",
  stundensatz: "85",
  umsatzsteuer_id: "",
  keine_mehrwertsteuer: false,
});

export function KundenSeite({ kundeId, neu, onFehler }: { kundeId: number | null; neu: boolean; onFehler: (text: string) => void }) {
  const [liste, setListe] = useState<Kunde[]>([]);
  const [suche, setSuche] = useState("");
  const [sortierung, setSortierung] = useState<Sortierung | null>(null);
  const [gewaehlt, setGewaehlt] = useState<number[]>([]);
  const [anker, setAnker] = useState(-1);
  const [aktiv, setAktiv] = useState<Kunde | null>(null);
  const [rechnungen, setRechnungen] = useState<RechnungKurz[]>([]);
  const [vorschauId, setVorschauId] = useState<number | null>(null);
  const [tipp, setTipp] = useState<{ x: number; y: number; text: string } | null>(null);
  const tippCache = useRef(new Map<number, string>());

  async function laden(q: string) {
    try {
      setListe(await api<Kunde[]>("/api/kunden?q=" + encodeURIComponent(q)));
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Kunden konnten nicht geladen werden.");
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => { void laden(suche); }, 200);
    return () => window.clearTimeout(timer);
  }, [suche]);

  useEffect(() => { setVorschauId(null); }, [kundeId]);

  useEffect(() => {
    if (neu) {
      setAktiv(leer());
      setRechnungen([]);
      return;
    }
    if (!kundeId) {
      setAktiv(null);
      setRechnungen([]);
      return;
    }
    let abbruch = false;
    api<Kunde[]>("/api/kunden")
      .then((alle) => {
        if (abbruch) return;
        const gefunden = alle.find((kunde) => kunde.kunden_id === kundeId);
        if (gefunden) setAktiv(gefunden);
      })
      .catch((exc) => onFehler(exc instanceof ApiFehler ? exc.message : "Kunde fehlt."));
    api<{ zeilen: RechnungKurz[] }>("/api/rechnungen?ansicht=alle&kunde_id=" + kundeId + "&limit=200")
      .then((daten) => { if (!abbruch) setRechnungen(daten.zeilen); })
      .catch((exc) => onFehler(exc instanceof ApiFehler ? exc.message : "Rechnungen fehlen."));
    return () => { abbruch = true; };
  }, [kundeId, neu]);

  function sucheForm(event: FormEvent) {
    event.preventDefault();
    void laden(suche);
  }

  async function speichern() {
    if (!aktiv) return;
    const body = { ...aktiv, kunden_id: undefined };
    try {
      const gespeichert = aktiv.kunden_id
        ? await api<Kunde>("/api/kunden/" + aktiv.kunden_id, { method: "PUT", body: JSON.stringify(body) })
        : await api<Kunde>("/api/kunden", { method: "POST", body: JSON.stringify(body) });
      setAktiv(gespeichert);
      await laden(suche);
      gehe("/kunden/" + gespeichert.kunden_id);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Speichern fehlgeschlagen.");
    }
  }

  async function loeschen() {
    if (!aktiv?.kunden_id) return;
    if (!window.confirm("Soll dieser Kunde gelöscht werden?")) return;
    try {
      await api("/api/kunden/" + aktiv.kunden_id, { method: "DELETE" });
      await laden(suche);
      gehe("/kunden");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Löschen fehlgeschlagen.");
    }
  }

  function feld<K extends keyof Kunde>(name: K, wert: Kunde[K]) {
    if (!aktiv) return;
    setAktiv({ ...aktiv, [name]: wert });
  }

  const gefiltert = liste.filter((kunde) => {
    const text = `${kunde.name1} ${kunde.name2} ${kunde.ort} ${kunde.email || ""}`.toLowerCase();
    return text.includes(suche.trim().toLowerCase());
  });
  const sichtbar = sortierung
    ? gefiltert.slice().sort((links, rechts) => {
      const wert = (kunde: Kunde) => sortierung.spalte === "name" ? kunde.name1 : sortierung.spalte === "ort" ? kunde.ort : kunde.kunden_id;
      const faktor = sortierung.richtung === "ab" ? -1 : 1;
      const a = wert(links);
      const b = wert(rechts);
      if (a < b) return -1 * faktor;
      if (a > b) return 1 * faktor;
      return 0;
    })
    : gefiltert;

  return (
    <div className="split">
      <div className="spalte">
        {vorschauId ? (
          <>
            <div className="vorschau-kopf">
              <button type="button" onClick={() => setVorschauId(null)}>Schließen</button>
              <button type="button" onClick={() => gehe("/rechnungen/" + vorschauId)}>In Rechnungen öffnen</button>
            </div>
            <PdfVorschau url={"/api/rechnungen/" + vorschauId + "/vorschau"} titel="Rechnung" />
            <a className="button datei-link" href={"/api/rechnungen/" + vorschauId + "/vorschau"} target="_blank" rel="noreferrer">Datei öffnen</a>
          </>
        ) : (
        <>
        <form className="row" onSubmit={sucheForm}>
          <label>Suche<input value={suche} onChange={(event) => setSuche(event.target.value)} /></label>
        </form>
        <div className="liste-werkzeug">
          <LinkIntern href="/kunden/neu" className="button">Neu</LinkIntern>
          <button type="button" className="secondary" onClick={() => { setSortierung(null); setAnker(-1); }}>Zurücksetzen</button>
        </div>
        <DatenListe
          zeilen={sichtbar}
          zeilenId={(kunde) => kunde.kunden_id}
          href={(kunde) => "/kunden/" + kunde.kunden_id}
          aktivId={kundeId}
          gewaehlt={gewaehlt}
          sortierung={sortierung}
          onSort={(spalte) => setSortierung((bisher) => bisher?.spalte === spalte ? { spalte, richtung: bisher.richtung === "ab" ? "auf" : "ab" } : { spalte, richtung: "ab" })}
          onZeile={(event, index) => {
            const ids = sichtbar.map((kunde) => kunde.kunden_id);
            const ergebnis = zeilenWahl(event, index, ids, gewaehlt, anker);
            setGewaehlt(ergebnis.ids);
            setAnker(ergebnis.anker);
            gehe("/kunden/" + ids[index]);
          }}
          spalten={[
            { key: "nummer", titel: "Kunde Nr.", zelle: (kunde) => kunde.kunden_id },
            { key: "name", titel: "Name", zelle: (kunde) => kunde.name1 },
            { key: "ort", titel: "Ort", zelle: (kunde) => `${kunde.plz} ${kunde.ort}` },
          ]}
        />
        </>
        )}
      </div>
      <div className="spalte">
        {!aktiv && <p className="hinweis">Kunde wählen oder neu anlegen.</p>}
        {aktiv && (
          <>
            <h2>{aktiv.kunden_id ? `Kunde ${aktiv.kunden_id}` : "Neuer Kunde"}</h2>
            <div className="form-gruppen">
              <fieldset className="block">
                <legend>Name</legend>
                <label>Name1:<input value={aktiv.name1} onChange={(event) => feld("name1", event.target.value)} /></label>
                <label>Name2:<input value={aktiv.name2} onChange={(event) => feld("name2", event.target.value)} /></label>
                <label>Name3:<input value={aktiv.name3} onChange={(event) => feld("name3", event.target.value)} /></label>
                <label>Stundensatz:<input value={aktiv.stundensatz} onChange={(event) => feld("stundensatz", event.target.value)} /></label>
              </fieldset>
              <fieldset className="block">
                <legend>Anschrift</legend>
                <label>Strasse:<input value={aktiv.strasse} onChange={(event) => feld("strasse", event.target.value)} /></label>
                <div className="plz-ort">
                  <label>PLZ:<input value={aktiv.plz} onChange={(event) => feld("plz", event.target.value)} /></label>
                  <label>Ort:<input value={aktiv.ort} onChange={(event) => feld("ort", event.target.value)} /></label>
                </div>
              </fieldset>
              <fieldset className="block">
                <legend>Kontakt:</legend>
                <label>Tel G:<input value={aktiv.tel1 || ""} onChange={(event) => feld("tel1", event.target.value)} /></label>
                <label>Tel P:<input value={aktiv.tel2 || ""} onChange={(event) => feld("tel2", event.target.value)} /></label>
                <label>Tel M:<input value={aktiv.tel3 || ""} onChange={(event) => feld("tel3", event.target.value)} /></label>
                <label>Fax:<input value={aktiv.fax || ""} onChange={(event) => feld("fax", event.target.value)} /></label>
                <label>Email:<input value={aktiv.email || ""} onChange={(event) => feld("email", event.target.value)} /></label>
              </fieldset>
              <fieldset className="block">
                <legend>Steuer</legend>
                <label className="check">
                  <input type="checkbox" checked={aktiv.keine_mehrwertsteuer} onChange={(event) => feld("keine_mehrwertsteuer", event.target.checked)} />
                  Keine MwSt. berechnen
                </label>
                <label>Umsatzsteuer ID:<input value={aktiv.umsatzsteuer_id} onChange={(event) => feld("umsatzsteuer_id", event.target.value)} /></label>
              </fieldset>
            </div>
            <div className="actions">
              <button type="button" onClick={() => void speichern()}>Speichern</button>
              {aktiv.kunden_id > 0 && <button type="button" className="danger" onClick={() => void loeschen()}>Löschen</button>}
            </div>
            {aktiv.kunden_id > 0 && (
              <>
                <h3>Rechnungen</h3>
                <table>
                  <thead>
                    <tr>
                      <th>Datum</th><th>Name</th><th>Re-Nr</th><th>Netto</th><th>Bezahlt</th><th>Zahlung</th><th>Brutto</th><th>Wh. Mon</th><th>Wh. Termin</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rechnungen.map((rechnung) => (
                      <tr
                        key={rechnung.rechnungs_id}
                        className="click"
                        onClick={() => setVorschauId(rechnung.rechnungs_id)}
                        onDoubleClick={() => gehe("/rechnungen/" + rechnung.rechnungs_id)}
                        onMouseEnter={(event) => void positionenZeigen(event, rechnung.rechnungs_id)}
                        onMouseLeave={() => setTipp(null)}
                      >
                        <td>{datumDE(rechnung.datum)}</td>
                        <td>{rechnung.name1}</td>
                        <td>{rechnung.archiv ? (rechnung.rechnungs_nr ? `${rechnung.rechnungs_nr} Archiv` : "Archiv") : (rechnung.rechnungs_nr || "Entwurf")}</td>
                        <td>{geld(rechnung.netto)}</td>
                        <td>{geld(rechnung.bezahlt)}</td>
                        <td>{datumDE(rechnung.bezahlt_am)}</td>
                        <td>{geld(rechnung.brutto)}</td>
                        <td>{rechnung.wiederholung_monate ?? ""}</td>
                        <td>{datumDE(rechnung.wiedervorlage_termin)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </>
        )}
      </div>
      {tipp && <div className="tooltip" style={{ left: tipp.x, top: tipp.y }}>{tipp.text}</div>}
    </div>
  );

  async function positionenZeigen(event: MouseEvent, id: number) {
    const x = event.clientX + 12;
    const y = event.clientY + 16;
    const bekannt = tippCache.current.get(id);
    if (bekannt) {
      setTipp({ x, y, text: bekannt });
      return;
    }
    setTipp({ x, y, text: "Laden …" });
    try {
      const daten = await api<{ positionen?: { menge: string; bezeichnung: string }[] }>("/api/rechnungen/" + id);
      const text = (daten.positionen || []).map((position) => `${position.menge} ${position.bezeichnung}`.trim()).filter(Boolean).join("\n") || "Keine Positionen";
      tippCache.current.set(id, text);
      setTipp({ x, y, text });
    } catch {
      setTipp(null);
    }
  }
}
