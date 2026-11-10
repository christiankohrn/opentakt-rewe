import { useEffect, useState, type FocusEvent, type FormEvent, type KeyboardEvent, type MouseEvent } from "react";
import { ApiFehler, api, datumDE, geld, heuteISO, pdfSpeichern } from "./api";
import { DatenListe, zeilenWahl, type Sortierung } from "./liste";
import { gehe } from "./nav";
import { DateiLink, PdfVorschau } from "./vorschau";

type Kunde = { kunden_id: number; name1: string };

type Position = {
  positionen_id: number | null;
  menge: string;
  preis: string;
  naechster_preis: string | null;
  naechste_menge: string | null;
  einmalig: boolean;
  bezeichnung: string;
  freitext: string;
  mengeneinheit: string;
  pos_nr: number | null;
};

type Rechnung = {
  rechnungs_id: number;
  datum: string;
  kunde_id: number | null;
  name1: string;
  name2: string;
  name3: string;
  strasse: string;
  plz: string;
  ort: string;
  rechnungs_nr: string | null;
  leistungszeitraum: string;
  umsatzsteuer_id: string;
  keine_mehrwertsteuer: boolean;
  storno_zu_rechnung_id: number | null;
  storno_zu_nr?: string | null;
  archiv: boolean;
  wiedervorlage_termin: string | null;
  wiederholung_monate: number | null;
  notizen_intern: string | null;
  brutto: string;
  netto: string;
  bezahlt: string;
  bezahlt_am: string | null;
  datev_gesendet?: string | null;
  positionen?: Position[];
};

function cent(wert: string | null | undefined): number {
  return Math.round(Number(wert || 0) * 100);
}

function nummerText(rechnung: Rechnung): string {
  if (rechnung.archiv) return rechnung.rechnungs_nr ? `${rechnung.rechnungs_nr} Archiv` : "Archiv";
  return rechnung.rechnungs_nr || "Entwurf";
}

type Summen = { offen: string; zu_berechnen: string };
type Listenart = "aktuell" | "alle" | "archiv";
type Seite = { zeilen: Rechnung[]; gesamt: number; sichtbar_summe: string; sichtbar_offen: string };
type Marke = { id: number; brutto: string; bezahlt: string };
const SEITE = 40;

export function RechnungenSeite({ rechnungId, onFehler }: { rechnungId: number | null; onFehler: (text: string) => void }) {
  const [liste, setListe] = useState<Rechnung[]>([]);
  const [name, setName] = useState("");
  const [position, setPosition] = useState("");
  const [listenart, setListenart] = useState<Listenart>("aktuell");
  const [summen, setSummen] = useState<Summen>({ offen: "0", zu_berechnen: "0" });
  const [sichtbar, setSichtbar] = useState({ summe: "0", offen: "0" });
  const [gesamt, setGesamt] = useState(0);
  const [seite, setSeite] = useState(0);
  const [sortierung, setSortierung] = useState<Sortierung | null>(null);
  const [markiert, setMarkiert] = useState<Marke[]>([]);
  const [anker, setAnker] = useState(-1);
  const [menu, setMenu] = useState<{ x: number; y: number; rechnung: Rechnung } | null>(null);

  async function laden(kundenname: string, positionsText: string, art: Listenart, blatt: number, sort: Sortierung | null, signal?: AbortSignal) {
    const query = new URLSearchParams({
      ansicht: art,
      name: kundenname,
      position: positionsText,
      offset: String(blatt * SEITE),
      limit: String(SEITE),
    });
    if (sort) {
      query.set("spalte", sort.spalte);
      query.set("richtung", sort.richtung);
    }
    try {
      const [daten, fuss] = await Promise.all([
        api<Seite>("/api/rechnungen?" + query.toString(), { signal }),
        api<Summen>("/api/rechnungen/summen?" + new URLSearchParams({ name: kundenname, position: positionsText }).toString(), { signal }),
      ]);
      setListe(daten.zeilen);
      setGesamt(daten.gesamt);
      setSichtbar({ summe: daten.sichtbar_summe, offen: daten.sichtbar_offen });
      setSummen(fuss);
      onFehler("");
    } catch (exc) {
      if (exc instanceof Error && exc.name === "AbortError") return;
      onFehler(exc instanceof ApiFehler ? exc.message : "Rechnungen konnten nicht geladen werden.");
    }
  }

  useEffect(() => {
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => { void laden(name, position, listenart, seite, sortierung, ctrl.signal); }, 200);
    return () => { window.clearTimeout(timer); ctrl.abort(); };
  }, [name, position, listenart, seite, sortierung]);

  useEffect(() => {
    function zu() { setMenu(null); }
    window.addEventListener("click", zu);
    return () => window.removeEventListener("click", zu);
  }, []);

  const markierteZeilen = markiert;
  const markiertSumme = markierteZeilen.reduce((acc, rechnung) => acc + Number(rechnung.brutto || 0), 0);
  const markiertOffen = markierteZeilen.reduce((acc, rechnung) => acc + Number(rechnung.brutto || 0) - Number(rechnung.bezahlt || 0), 0);

  async function neu() {
    try {
      const rechnung = await api<Rechnung>("/api/rechnungen", {
        method: "POST",
        body: JSON.stringify({ kunde_id: null }),
      });
      gehe("/rechnungen/" + rechnung.rechnungs_id);
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Rechnung konnte nicht angelegt werden.");
    }
  }

  async function alsBezahlt(rechnung: Rechnung) {
    try {
      await api("/api/rechnungen/" + rechnung.rechnungs_id + "/zahlung", {
        method: "POST",
        body: JSON.stringify({ betrag: rechnung.brutto, datum: heuteISO() }),
      });
      await laden(name, position, listenart, seite, sortierung);
      setMenu(null);
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Zahlung fehlgeschlagen.");
    }
  }

  async function rechnungenAnDatev(zielRechnung: Rechnung) {
    setMenu(null);
    const ids = markiert.some((m) => m.id === zielRechnung.rechnungs_id) && markiert.length > 1
      ? markiert.map((m) => m.id)
      : [zielRechnung.rechnungs_id];
    try {
      for (const id of ids) {
        await api("/api/rechnungen/" + id + "/datev", { method: "POST" });
      }
      await laden(name, position, listenart, seite, sortierung);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "DATEV-Versand fehlgeschlagen.");
    }
  }

  function sucheForm(event: FormEvent) {
    event.preventDefault();
    setSeite(0);
    void laden(name, position, listenart, 0, sortierung);
  }

  function waehlen(event: MouseEvent<HTMLTableRowElement>, index: number) {
    const ids = liste.map((rechnung) => rechnung.rechnungs_id);
    const ergebnis = zeilenWahl(event, index, ids, markiert.map((eintrag) => eintrag.id), anker);
    const bekannt = new Map(markiert.map((eintrag) => [eintrag.id, eintrag]));
    for (const rechnung of liste) bekannt.set(rechnung.rechnungs_id, { id: rechnung.rechnungs_id, brutto: rechnung.brutto, bezahlt: rechnung.bezahlt });
    setMarkiert(ergebnis.ids.map((id) => bekannt.get(id)).filter((eintrag): eintrag is Marke => Boolean(eintrag)));
    setAnker(ergebnis.anker);
    gehe("/rechnungen/" + ids[index]);
  }

  async function loeschen() {
    const ids = markiert.length ? markiert.map((eintrag) => eintrag.id) : rechnungId ? [rechnungId] : [];
    if (!ids.length) return;
    const frage = ids.length === 1 ? "Soll diese Rechnung gelöscht werden?" : `Sollen ${ids.length} Rechnungen gelöscht werden?`;
    if (!window.confirm(frage)) return;
    try {
      for (const id of ids) await api("/api/rechnungen/" + id, { method: "DELETE" });
      setMarkiert([]);
      if (rechnungId && ids.includes(rechnungId)) gehe("/rechnungen");
      await laden(name, position, listenart, seite, sortierung);
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Löschen fehlgeschlagen.");
    }
  }

  function sortieren(spalte: string) {
    setSeite(0);
    setAnker(-1);
    setSortierung((bisher) => bisher?.spalte === spalte
      ? { spalte, richtung: bisher.richtung === "ab" ? "auf" : "ab" }
      : { spalte, richtung: "ab" });
  }

  const von = gesamt === 0 ? 0 : seite * SEITE + 1;
  const bis = Math.min(gesamt, (seite + 1) * SEITE);

  return (
    <div className="split">
      <div className="spalte liste-spalte">
        <div className="liste-werkzeug">
          <button type="button" onClick={() => void neu()}>Neue Rechnung</button>
          <button type="button" className="danger" onClick={() => void loeschen()}>Löschen</button>
        </div>
        <form className="suche-schmal" onSubmit={sucheForm}>
          <label>Suche<input value={name} onChange={(event) => { setSeite(0); setAnker(-1); setName(event.target.value); }} /></label>
        </form>
        <div className="actions">
          {(["aktuell", "alle", "archiv"] as const).map((art) => (
            <button key={art} type="button" className={listenart === art ? "" : "secondary"} onClick={() => { setSeite(0); setAnker(-1); setListenart(art); }}>
              {art === "aktuell" ? "Aktuell" : art === "alle" ? "Alle" : "Archiv"}
            </button>
          ))}
          <button type="button" className="secondary" onClick={() => { setSeite(0); setAnker(-1); setSortierung(null); }}>Zurücksetzen</button>
        </div>
        <div className="liste-scroll">
          <DatenListe
            zeilen={liste}
            zeilenId={(rechnung) => rechnung.rechnungs_id}
            href={(rechnung) => "/rechnungen/" + rechnung.rechnungs_id}
            aktivId={rechnungId}
            gewaehlt={markiert.map((eintrag) => eintrag.id)}
            sortierung={sortierung}
            onSort={sortieren}
            onZeile={waehlen}
            onKontext={(event, index) => setMenu({ x: event.clientX, y: event.clientY, rechnung: liste[index] })}
            klasse={(rechnung) => rechnung.archiv ? "archiv" : !rechnung.rechnungs_nr ? "entwurf" : cent(rechnung.bezahlt) === cent(rechnung.brutto) ? "" : "offen"}
            spalten={[
              { key: "nummer", titel: "Nummer", zelle: nummerText },
              { key: "datum", titel: "Datum", zelle: (rechnung) => datumDE(rechnung.datum) },
              { key: "kunde", titel: "Kunde", zelle: (rechnung) => rechnung.name1 },
              { key: "brutto", titel: "Brutto", zelle: (rechnung) => geld(rechnung.brutto) },
              { key: "bezahlt", titel: "Bezahlt", zelle: (rechnung) => geld(rechnung.bezahlt) },
              { key: "stb", titel: "StB", zelle: (rechnung) => rechnung.datev_gesendet ? datumDE(rechnung.datev_gesendet) : (rechnung.rechnungs_nr ? "offen" : "—") },
            ]}
          />
        </div>
        <div className="seiten">
          <button type="button" className="secondary" disabled={seite === 0} onClick={() => { setAnker(-1); setSeite((wert) => wert - 1); }}>Zurück</button>
          <span>{von}–{bis} von {gesamt}</span>
          <button type="button" className="secondary" disabled={bis >= gesamt} onClick={() => { setAnker(-1); setSeite((wert) => wert + 1); }}>Weiter</button>
        </div>
        <footer className="liste-fuss fuss-block">
          <div className="fuss-zeile">
            <fieldset className="block sichtbar-kasten"><legend>Sichtbar</legend><span>Summe: {geld(sichtbar.summe)}</span><span>offen: {geld(sichtbar.offen)}</span></fieldset>
            <fieldset className="block"><legend>Markiert</legend><span>Summe: {geld(markiertSumme)}</span><span>offen: {geld(markiertOffen)}</span></fieldset>
            <fieldset className="block"><legend>Zu berechnen</legend><span>{geld(summen.zu_berechnen)}</span></fieldset>
            <fieldset className="block"><legend>Offen</legend><span>{geld(summen.offen)}</span></fieldset>
          </div>
          <label>Nach Positionen suchen<input value={position} onChange={(event) => { setSeite(0); setAnker(-1); setPosition(event.target.value); }} /></label>
        </footer>
        {menu && (
          <div className="menu" style={{ left: menu.x, top: menu.y }} onClick={(event) => event.stopPropagation()}>
            <button type="button" onClick={() => void alsBezahlt(menu.rechnung)}>Als bezahlt markieren</button>
            {menu.rechnung.rechnungs_nr && (
              <button type="button" onClick={() => void rechnungenAnDatev(menu.rechnung)}>
                An DATEV senden ({markiert.some((m) => m.id === menu.rechnung.rechnungs_id) && markiert.length > 1 ? `${markiert.length} Rechnungen` : menu.rechnung.rechnungs_nr})
              </button>
            )}
          </div>
        )}
      </div>
      <div className="spalte">
        {rechnungId ? <RechnungEditor id={rechnungId} onFehler={onFehler} onGeaendert={() => laden(name, position, listenart, seite, sortierung)} /> : <p className="hinweis vorschau-mitte">Rechnung wählen.</p>}
      </div>
    </div>
  );
}

function leerPos(posNr: number): Position {
  return { positionen_id: null, menge: "1", preis: "0", naechster_preis: null, naechste_menge: null, einmalig: false, bezeichnung: "", freitext: "", mengeneinheit: "", pos_nr: posNr };
}

function istLeer(position: Position): boolean {
  return !position.positionen_id && !position.bezeichnung.trim() && !position.freitext.trim() && !position.mengeneinheit.trim()
    && (position.preis === "" || position.preis === "0")
    && (position.menge === "" || position.menge === "0" || position.menge === "1");
}

function mitLeer(positionen: Position[]): Position[] {
  return positionen.some(istLeer) ? positionen : [...positionen, leerPos(positionen.length)];
}

const POS_FELDER = ["menge", "einheit", "bezeichnung", "preis", "npreis", "nmenge", "einmalig"];

function ganzMarkiert(el: HTMLInputElement): boolean {
  if (el.type === "checkbox") return true;
  const start = el.selectionStart;
  const ende = el.selectionEnd;
  if (start === null || ende === null) return true;
  return start === 0 && ende === el.value.length;
}

function fokus(event: FocusEvent<HTMLInputElement>) {
  if (event.currentTarget.type !== "checkbox") event.currentTarget.select();
}

function taste(event: KeyboardEvent<HTMLInputElement>, index: number, feld: string) {
  if (event.key === "ArrowUp" || event.key === "ArrowDown") {
    event.preventDefault();
    const ziel = index + (event.key === "ArrowDown" ? 1 : -1);
    document.querySelector<HTMLElement>(`[data-pos="${ziel}"][data-feld="${feld}"]`)?.focus();
    return;
  }
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  if (!ganzMarkiert(event.currentTarget)) return;
  const naechstes = POS_FELDER.indexOf(feld) + (event.key === "ArrowLeft" ? -1 : 1);
  if (naechstes < 0 || naechstes >= POS_FELDER.length) return;
  event.preventDefault();
  document.querySelector<HTMLElement>(`[data-pos="${index}"][data-feld="${POS_FELDER[naechstes]}"]`)?.focus();
}

function RechnungEditor({ id, onFehler, onGeaendert }: { id: number; onFehler: (text: string) => void; onGeaendert: () => void }) {
  const [rechnung, setRechnung] = useState<Rechnung | null>(null);
  const [kunden, setKunden] = useState<Kunde[]>([]);
  const [ansicht, setAnsicht] = useState<"felder" | "vorschau">("felder");
  const [betrag, setBetrag] = useState("");
  const [bezahltAm, setBezahltAm] = useState(heuteISO());
  const [termin, setTermin] = useState("");
  const [monate, setMonate] = useState("");
  const [stand, setStand] = useState(0);

  async function laden() {
    const daten = await api<Rechnung>("/api/rechnungen/" + id);
    setRechnung({ ...daten, positionen: mitLeer(daten.positionen || []) });
    setBetrag(daten.brutto);
    setBezahltAm(daten.bezahlt_am || heuteISO());
    setTermin(daten.wiedervorlage_termin || "");
    setMonate(daten.wiederholung_monate ? String(daten.wiederholung_monate) : "");
    setAnsicht(daten.rechnungs_nr && !daten.archiv ? "vorschau" : "felder");
    setStand((wert) => wert + 1);
  }

  useEffect(() => {
    laden().catch((exc) => onFehler(exc instanceof ApiFehler ? exc.message : "Rechnung fehlt."));
    api<Kunde[]>("/api/kunden").then(setKunden).catch(() => undefined);
  }, [id]);

  if (!rechnung) return <div className="vorschau-mitte" role="status"><span className="kreis" aria-label="Laden" /></div>;

  function setKopf<K extends keyof Rechnung>(feld: K, wert: Rechnung[K]) {
    setRechnung({ ...rechnung!, [feld]: wert });
  }
  function setPos(index: number, feld: keyof Position, wert: string | boolean | null) {
    const positionen = [...(rechnung!.positionen || [])];
    positionen[index] = { ...positionen[index], [feld]: wert };
    setRechnung({ ...rechnung!, positionen: mitLeer(positionen) });
  }
  function payload() {
    return {
      datum: rechnung!.datum,
      kunde_id: rechnung!.kunde_id,
      name1: rechnung!.name1,
      name2: rechnung!.name2,
      name3: rechnung!.name3,
      strasse: rechnung!.strasse,
      plz: rechnung!.plz,
      ort: rechnung!.ort,
      leistungszeitraum: rechnung!.leistungszeitraum,
      umsatzsteuer_id: rechnung!.umsatzsteuer_id,
      keine_mehrwertsteuer: rechnung!.keine_mehrwertsteuer,
      archiv: rechnung!.archiv,
      notizen_intern: rechnung!.notizen_intern,
      positionen: (rechnung!.positionen || []).filter((position) => !istLeer(position)).map((position, index) => ({
        ...position,
        menge: position.menge || "0",
        preis: position.preis || "0",
        naechster_preis: position.naechster_preis || null,
        naechste_menge: position.naechste_menge || null,
        pos_nr: index,
      })),
    };
  }
  async function speichern(): Promise<Rechnung> {
    const gespeichert = await api<Rechnung>("/api/rechnungen/" + id, { method: "PUT", body: JSON.stringify(payload()) });
    setRechnung({ ...gespeichert, positionen: mitLeer(gespeichert.positionen || []) });
    setStand((wert) => wert + 1);
    onGeaendert();
    onFehler("");
    return gespeichert;
  }
  async function kundeWechseln(value: string) {
    const gewaehlt = value ? Number(value) : null;
    const ueberschreiben = !rechnung!.name1.trim() || window.confirm("Vorhandene Kundendaten überschreiben?");
    try {
      const gespeichert = await api<Rechnung>("/api/rechnungen/" + id + "/kunde", {
        method: "POST",
        body: JSON.stringify({ kunde_id: gewaehlt, ueberschreiben }),
      });
      setRechnung({ ...gespeichert, positionen: mitLeer(gespeichert.positionen || []) });
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Kunde konnte nicht gesetzt werden.");
    }
  }
  async function drucken() {
    try {
      await speichern();
      let datumAufHeute = false;
      if (!rechnung!.rechnungs_nr) {
        const monat = new Intl.DateTimeFormat("de-DE", { month: "long" }).format(new Date()).toLowerCase();
        if (!rechnung!.leistungszeitraum.toLowerCase().includes(monat) && !window.confirm("Leistungszeitraum geprüft?")) return;
        if (rechnung!.datum !== heuteISO()) datumAufHeute = window.confirm("Rechnungsdatum aktualisieren?");
      }
      await pdfSpeichern("/api/rechnungen/" + id + "/drucken", { datum_auf_heute: datumAufHeute }, "Rechnung.pdf");
      await laden();
      onGeaendert();
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Druck fehlgeschlagen.");
    }
  }
  async function aktion(pfad: string, body?: unknown) {
    try {
      if (body === undefined) await api(pfad, { method: "POST" });
      else await api(pfad, { method: "POST", body: JSON.stringify(body) });
      await laden();
      onGeaendert();
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Aktion fehlgeschlagen.");
    }
  }

  return (
    <div>
      <div className="actions">
        <button type="button" className={ansicht === "felder" ? "" : "secondary"} onClick={() => setAnsicht("felder")}>Felder</button>
        <button type="button" className={ansicht === "vorschau" ? "" : "secondary"} onClick={() => setAnsicht("vorschau")}>Vorschau</button>
        <button type="button" onClick={() => speichern().catch((exc) => onFehler(exc instanceof ApiFehler ? exc.message : "Speichern fehlgeschlagen."))}>Speichern</button>
        <button type="button" onClick={() => void drucken()}>Drucken</button>
        <button type="button" className="secondary" onClick={() => pdfSpeichern("/api/rechnungen/" + id + "/mahnung", {}, "Mahnung.pdf").catch((exc) => onFehler(exc instanceof Error ? exc.message : "Mahnung fehlgeschlagen."))}>Mahnung</button>
        <button type="button" onClick={() => void aktion("/api/rechnungen/" + id + "/senden", { art: "rechnung" })}>Rechnung mailen</button>
        <button type="button" className="secondary" onClick={async () => {
          if (!window.confirm("Soll die Rechnung storniert werden?")) return;
          try {
            const neu = await api<Rechnung>("/api/rechnungen/" + id + "/storno", { method: "POST" });
            gehe("/rechnungen/" + neu.rechnungs_id);
          } catch (exc) {
            onFehler(exc instanceof ApiFehler ? exc.message : "Storno fehlgeschlagen.");
          }
        }}>Storno</button>
        <button type="button" className="secondary" onClick={async () => {
          try {
            const neu = await api<Rechnung>("/api/rechnungen/" + id + "/kopie", { method: "POST" });
            gehe("/rechnungen/" + neu.rechnungs_id);
          } catch (exc) {
            onFehler(exc instanceof ApiFehler ? exc.message : "Kopie fehlgeschlagen.");
          }
        }}>Kopie</button>
      </div>
      <p>{nummerText(rechnung)} · Netto {geld(rechnung.netto)} · Brutto {geld(rechnung.brutto)}</p>
      {ansicht === "vorschau" ? (
        <div className="vorschau-box">
          <PdfVorschau url={"/api/rechnungen/" + id + "/vorschau?stand=" + stand} titel="Rechnung" />
          <DateiLink url={"/api/rechnungen/" + id + "/vorschau?stand=" + stand} />
        </div>
      ) : (
        <>
          {rechnung.storno_zu_rechnung_id && <p className="hinweis">Storno zu {rechnung.storno_zu_nr || rechnung.storno_zu_rechnung_id}</p>}
          <div className="form-gruppen">
            <fieldset className="block anschrift">
              <legend>Anschrift</legend>
              <label>Kunde
                <select value={rechnung.kunde_id || ""} onChange={(event) => void kundeWechseln(event.target.value)}>
                  <option value="">kein Kunde</option>
                  {kunden.map((kunde) => <option key={kunde.kunden_id} value={kunde.kunden_id}>{kunde.name1}</option>)}
                </select>
              </label>
              <label>Name1:<input value={rechnung.name1} onChange={(event) => setKopf("name1", event.target.value)} /></label>
              <label>Name2:<input value={rechnung.name2} onChange={(event) => setKopf("name2", event.target.value)} /></label>
              <label>Name3:<input value={rechnung.name3} onChange={(event) => setKopf("name3", event.target.value)} /></label>
              <label>Strasse:<input value={rechnung.strasse} onChange={(event) => setKopf("strasse", event.target.value)} /></label>
              <div className="plz-ort">
                <label>PLZ:<input value={rechnung.plz} onChange={(event) => setKopf("plz", event.target.value)} /></label>
                <label>Ort:<input value={rechnung.ort} onChange={(event) => setKopf("ort", event.target.value)} /></label>
              </div>
            </fieldset>
            <fieldset className="block">
              <legend>Rechnung</legend>
              <label>Datum<input type="date" value={rechnung.datum} onChange={(event) => setKopf("datum", event.target.value)} /></label>
              <label>Leistungszeitraum<input value={rechnung.leistungszeitraum} onChange={(event) => setKopf("leistungszeitraum", event.target.value)} /></label>
              <label className="check"><input type="checkbox" checked={rechnung.archiv} onChange={(event) => setKopf("archiv", event.target.checked)} /> Archiv</label>
            </fieldset>
            <fieldset className="block">
              <legend>Steuer</legend>
              <label className="check"><input type="checkbox" checked={rechnung.keine_mehrwertsteuer} onChange={(event) => setKopf("keine_mehrwertsteuer", event.target.checked)} /> Keine Mehrwertsteuer</label>
              <label>Umsatzsteuer ID:<input value={rechnung.umsatzsteuer_id} onChange={(event) => setKopf("umsatzsteuer_id", event.target.value)} /></label>
            </fieldset>
          </div>
          <div className="card">
            <h3>Wiedervorlage</h3>
            <div className="row">
              <label>WiedervorlageTermin<input type="date" value={termin} onChange={(event) => setTermin(event.target.value)} /></label>
              <label>WiederholungMonate<input value={monate} onChange={(event) => setMonate(event.target.value)} placeholder="leer = einmalig" /></label>
              <button type="button" onClick={() => void aktion("/api/rechnungen/" + id + "/wiedervorlage", { termin: termin || null, monate: monate ? Number(monate) : null })}>Wiedervorlage speichern</button>
            </div>
          </div>
          {(rechnung.notizen_intern || "").trim() && (
            <label>Notizen intern<textarea value={rechnung.notizen_intern || ""} onChange={(event) => setKopf("notizen_intern", event.target.value)} /></label>
          )}
          <h3>Positionen</h3>
          <table className="pos">
            <thead><tr><th>Menge</th><th>Einheit</th><th>Bezeichnung</th><th>Preis</th><th>n. Preis</th><th>n. Menge</th><th>einmalig</th><th></th></tr></thead>
            <tbody>
              {(rechnung.positionen || []).map((position, index) => (
                <tr key={position.positionen_id || "neu-" + index}>
                  <td><input data-pos={index} data-feld="menge" value={position.menge} onFocus={fokus} onKeyDown={(event) => taste(event, index, "menge")} onChange={(event) => setPos(index, "menge", event.target.value)} /></td>
                  <td><input data-pos={index} data-feld="einheit" value={position.mengeneinheit} onFocus={fokus} onKeyDown={(event) => taste(event, index, "einheit")} onChange={(event) => setPos(index, "mengeneinheit", event.target.value)} /></td>
                  <td>
                    <input data-pos={index} data-feld="bezeichnung" value={position.bezeichnung} onFocus={fokus} onKeyDown={(event) => taste(event, index, "bezeichnung")} onChange={(event) => setPos(index, "bezeichnung", event.target.value)} />
                    <textarea tabIndex={-1} value={position.freitext} placeholder="Beschreibung" onChange={(event) => setPos(index, "freitext", event.target.value)} />
                  </td>
                  <td><input data-pos={index} data-feld="preis" value={position.preis} onFocus={fokus} onKeyDown={(event) => taste(event, index, "preis")} onChange={(event) => setPos(index, "preis", event.target.value)} /></td>
                  <td><input data-pos={index} data-feld="npreis" value={position.naechster_preis || ""} onFocus={fokus} onKeyDown={(event) => taste(event, index, "npreis")} onChange={(event) => setPos(index, "naechster_preis", event.target.value || null)} /></td>
                  <td><input data-pos={index} data-feld="nmenge" value={position.naechste_menge || ""} onFocus={fokus} onKeyDown={(event) => taste(event, index, "nmenge")} onChange={(event) => setPos(index, "naechste_menge", event.target.value || null)} /></td>
                  <td><input data-pos={index} data-feld="einmalig" type="checkbox" checked={position.einmalig} onKeyDown={(event) => taste(event, index, "einmalig")} onChange={(event) => setPos(index, "einmalig", event.target.checked)} /></td>
                  <td>{!istLeer(position) && <button type="button" className="danger" onClick={() => setRechnung({ ...rechnung, positionen: mitLeer((rechnung.positionen || []).filter((_, item) => item !== index)) })}>×</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="card">
            <h3>Zahlung</h3>
            <div className="row">
              <label>Betrag<input value={betrag} onChange={(event) => setBetrag(event.target.value)} /></label>
              <label>Bezahlt am<input type="date" value={bezahltAm} onChange={(event) => setBezahltAm(event.target.value)} /></label>
              <button type="button" onClick={() => void aktion("/api/rechnungen/" + id + "/zahlung", { betrag, datum: bezahltAm })}>Zahlung speichern</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
