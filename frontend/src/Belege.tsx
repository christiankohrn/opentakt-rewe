import { useEffect, useState, type DragEvent } from "react";
import { ApiFehler, api, betragEingabe, datumDE, geld, hatExterneDateien } from "./api";
import { AblegenModal, DateiImportKnopf } from "./Ablegen";
import { KontoFilter, useKategorien } from "./konten";
import { DatenListe, zeilenWahl, type Sortierung } from "./liste";
import { LinkIntern, gehe } from "./nav";
import { Teilung } from "./teilen";
import { DateiLink, PdfVorschau } from "./vorschau";

type Position = {
  bezeichnung: string;
  menge: string;
  einheit: string;
  preis: string;
  gesamt: string;
};

type ERechnung = {
  vorhanden: boolean;
  nummer: string;
  datum: string;
  verkaeufer: string;
  kaeufer: string;
  netto: string;
  steuer: string;
  brutto: string;
  positionen: Position[];
};

type Beleg = {
  beleg_id: number;
  dateiname: string;
  art: string;
  quelle: string;
  eingang: string | null;
  betrag: string | null;
  datum: string | null;
  partner: string;
  rechnungsnummer: string;
  betrag_herkunft: string;
  datum_herkunft: string;
  partner_herkunft: string;
  ocr_status: string;
  pruefung: string;
  ohne_bewegung?: boolean;
  bewegung_id?: number | null;
  datev_gesendet?: string | null;
};

function herkunftText(wert: string): string {
  if (wert === "sicher") return "sicher gelesen";
  if (wert === "geraten") return "nur geraten";
  if (wert === "korrigiert") return "korrigiert";
  return "nicht erkannt";
}

function ocrText(status: string): string {
  if (status === "text") return "Text vorhanden";
  if (status === "ocr") return "Text per OCR gelesen";
  if (status === "ohne") return "Kein Text gefunden";
  return "Textstatus unbekannt";
}

export function BelegeSeite({ belegId, onFehler }: { belegId: number | null; onFehler: (text: string) => void }) {
  const kategorien = useKategorien();
  const [liste, setListe] = useState<Beleg[]>([]);
  const [suche, setSuche] = useState("");
  const [konto, setKonto] = useState("");
  const [sortierung, setSortierung] = useState<Sortierung | null>(null);
  const [gewaehlt, setGewaehlt] = useState<number[]>([]);
  const [anker, setAnker] = useState(-1);
  const [ablage, setAblage] = useState<File[]>([]);
  const [ablageGesamt, setAblageGesamt] = useState(0);
  const [partner, setPartner] = useState("");
  const [betrag, setBetrag] = useState("");
  const [datum, setDatum] = useState("");
  const [nummer, setNummer] = useState("");
  const [belegKonto, setBelegKonto] = useState("");
  const [bearbeitung, setBearbeitung] = useState(false);
  const [meldung, setMeldung] = useState("");
  const [menu, setMenu] = useState<{ x: number; y: number; ids: number[]; aktuell: string } | null>(null);

  async function laden(filter: string) {
    try {
      const daten = await api<Beleg[]>("/api/belege" + (filter ? "?konto=" + encodeURIComponent(filter) : ""));
      setListe(daten.filter((beleg) => beleg.art !== "abrechnung"));
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Belege nicht geladen.");
    }
  }

  useEffect(() => { void laden(konto); }, [konto]);

  useEffect(() => {
    const neuLaden = () => { void laden(konto); };
    window.addEventListener("buchhaltung:belege-aktualisiert", neuLaden);
    return () => window.removeEventListener("buchhaltung:belege-aktualisiert", neuLaden);
  }, [konto]);

  useEffect(() => {
    setMeldung("");
    if (belegId && !liste.some((beleg) => beleg.beleg_id === belegId)) {
      void laden(konto);
    }
  }, [belegId]);

  const aktiv = liste.find((beleg) => beleg.beleg_id === belegId) || null;
  useEffect(() => {
    setPartner(aktiv?.partner || "");
    setBetrag(betragEingabe(aktiv?.betrag));
    setDatum(aktiv?.datum || "");
    setNummer(aktiv?.rechnungsnummer || "");
    setBelegKonto(aktiv?.quelle || "");
  }, [aktiv?.beleg_id, aktiv?.partner, aktiv?.betrag, aktiv?.datum, aktiv?.rechnungsnummer, aktiv?.quelle]);

  useEffect(() => {
    if (!menu) return;
    const schliessen = () => setMenu(null);
    window.addEventListener("click", schliessen);
    window.addEventListener("scroll", schliessen, true);
    return () => {
      window.removeEventListener("click", schliessen);
      window.removeEventListener("scroll", schliessen, true);
    };
  }, [menu]);

  async function kontoZuordnen(ids: number[], zielKonto: string) {
    setMenu(null);
    try {
      await api("/api/belege/konto", {
        method: "POST",
        body: JSON.stringify({ beleg_ids: ids, quelle: zielKonto }),
      });
      await laden(konto);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Kategorie konnte nicht geändert werden.");
    }
  }

  async function belegeAnDatevSenden(ids: number[], zielKonto?: string) {
    setMenu(null);
    try {
      for (const id of ids) {
        await api("/api/belege/" + id + "/datev", {
          method: "POST",
          body: JSON.stringify({ adresse: zielKonto || null }),
        });
      }
      await laden(konto);
      setMeldung(ids.length === 1 ? "Beleg an DATEV gesendet." : `${ids.length} Belege an DATEV gesendet.`);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Versand an DATEV fehlgeschlagen.");
    }
  }

  const gefiltert = liste.filter((beleg) => {
    const text = `${beleg.dateiname} ${beleg.partner} ${beleg.rechnungsnummer || ""} ${beleg.betrag || ""} ${beleg.datum || ""}`.toLowerCase();
    return text.includes(suche.trim().toLowerCase());
  });
  const sichtbar = sortierung
    ? gefiltert.slice().sort((links, rechts) => {
      const wert = (beleg: Beleg) => {
        if (sortierung.spalte === "eingang") return beleg.eingang || "";
        if (sortierung.spalte === "datum") return beleg.datum || "";
        if (sortierung.spalte === "partner") return beleg.partner;
        if (sortierung.spalte === "betrag") return Number(beleg.betrag || 0);
        return beleg.dateiname;
      };
      const a = wert(links);
      const b = wert(rechts);
      const faktor = sortierung.richtung === "ab" ? -1 : 1;
      if (a < b) return -1 * faktor;
      if (a > b) return 1 * faktor;
      return 0;
    })
    : gefiltert;

  async function loeschen(einzelId?: number) {
    const ids = einzelId ? [einzelId] : gewaehlt.length ? gewaehlt : belegId ? [belegId] : [];
    if (!ids.length) return;
    const frage = ids.length === 1 ? "Soll dieser Beleg gelöscht werden?" : `Sollen ${ids.length} Belege gelöscht werden?`;
    if (!window.confirm(frage)) return;
    try {
      for (const id of ids) await api("/api/belege/" + id, { method: "DELETE" });
      setGewaehlt([]);
      if (belegId && ids.includes(belegId)) {
        setBearbeitung(false);
        gehe("/belege");
      }
      await laden(konto);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Löschen fehlgeschlagen.");
    }
  }

  async function verfeinern() {
    if (!aktiv) return;
    try {
      const daten = await api<{ partner: string; betrag: string; datum: string; rechnungsnummer: string }>("/api/belege/" + aktiv.beleg_id + "/ki", { method: "POST" });
      if (daten.partner) setPartner(daten.partner);
      if (daten.betrag) setBetrag(betragEingabe(daten.betrag));
      if (daten.datum) setDatum(daten.datum);
      if (daten.rechnungsnummer) setNummer(daten.rechnungsnummer);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "KI nicht erreichbar.");
    }
  }

  async function ocrLaufen() {
    if (!aktiv) return;
    try {
      const daten = await api<Beleg>("/api/belege/" + aktiv.beleg_id + "/ocr", { method: "POST" });
      setPartner(daten.partner || "");
      setBetrag(betragEingabe(daten.betrag));
      setDatum(daten.datum || "");
      setNummer(daten.rechnungsnummer || "");
      await laden(konto);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "OCR fehlgeschlagen.");
    }
  }

  async function speichern(weiter: boolean) {
    if (!aktiv) return;
    try {
      await api("/api/belege/" + aktiv.beleg_id, {
        method: "PUT",
        body: JSON.stringify({
          partner,
          rechnungsnummer: nummer,
          betrag: betrag.trim() ? betrag.replace(",", ".") : null,
          datum: datum || null,
          quelle: belegKonto || null,
        }),
      });
      await laden(konto);
      onFehler("");
      if (weiter) {
        const index = sichtbar.findIndex((beleg) => beleg.beleg_id === aktiv.beleg_id);
        const naechster = sichtbar[index + 1];
        if (naechster) gehe("/belege/" + naechster.beleg_id);
        else setMeldung("Beleg gespeichert (Ende der Liste).");
      } else {
        setMeldung("Beleg gespeichert.");
      }
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Speichern fehlgeschlagen.");
    }
  }

  function dateienDazu(dateien: File[]) {
    if (!dateien.length) return;
    setAblage((bisher) => {
      setAblageGesamt((alt) => (bisher.length === 0 ? dateien.length : alt + dateien.length));
      return [...bisher, ...dateien];
    });
  }

  function fallen(event: DragEvent) {
    event.preventDefault();
    if (!hatExterneDateien(event.dataTransfer)) return;
    dateienDazu([...event.dataTransfer.files]);
  }

  function kontoName(schluessel: string): string {
    return kategorien.find((k) => k.schluessel === schluessel)?.name || schluessel;
  }

  const aktivIndex = aktiv ? sichtbar.findIndex((b) => b.beleg_id === aktiv.beleg_id) : -1;
  const vorigeId = aktivIndex > 0 ? sichtbar[aktivIndex - 1].beleg_id : null;
  const naechsteId = aktivIndex >= 0 && aktivIndex + 1 < sichtbar.length ? sichtbar[aktivIndex + 1].beleg_id : null;
  const hatDetail = Boolean(belegId && aktiv);

  const listePane = (
    <div className="spalte liste-spalte dicht">
      <div className="liste-werkzeug">
        <DateiImportKnopf onFehler={onFehler} className="button" title="Beleg oder Abrechnung importieren" />
        <div className="actions" style={{ margin: 0 }}>
          {(suche.trim() || sortierung || konto) && (
            <button type="button" className="secondary kompakt-knopf" onClick={() => { setSuche(""); setKonto(""); setSortierung(null); setAnker(-1); }}>
              Filter leeren
            </button>
          )}
          {gewaehlt.length > 1 && (
            <button type="button" className="danger kompakt-knopf" onClick={() => void loeschen()}>
              {gewaehlt.length} löschen
            </button>
          )}
        </div>
      </div>
      <KontoFilter wert={konto} onChange={setKonto} />
      <input
        aria-label="Belege suchen"
        placeholder="Partner, Betrag, Rechnungsnr. oder Dateiname …"
        value={suche}
        onChange={(event) => setSuche(event.target.value)}
        style={{ marginBottom: "0.45rem" }}
      />
      <div className="liste-scroll">
        <DatenListe
          zeilen={sichtbar}
          zeilenId={(beleg) => beleg.beleg_id}
          href={(beleg) => "/belege/" + beleg.beleg_id}
          aktivId={belegId}
          gewaehlt={gewaehlt}
          sortierung={sortierung}
          onSort={(spalte) => setSortierung((bisher) => bisher?.spalte === spalte ? { spalte, richtung: bisher.richtung === "ab" ? "auf" : "ab" } : { spalte, richtung: "ab" })}
          onZeile={(event, index) => {
            const ids = sichtbar.map((beleg) => beleg.beleg_id);
            const ergebnis = zeilenWahl(event, index, ids, gewaehlt, anker);
            setGewaehlt(ergebnis.ids);
            setAnker(ergebnis.anker);
            if (window.innerWidth > 1024) setBearbeitung(false);
            gehe("/belege/" + ids[index]);
          }}
          onDoppel={(index) => {
            setBearbeitung(true);
            gehe("/belege/" + sichtbar[index].beleg_id);
          }}
          onKontext={(event, index) => {
            const zeile = sichtbar[index];
            const zielIds = gewaehlt.includes(zeile.beleg_id) ? gewaehlt : [zeile.beleg_id];
            if (!gewaehlt.includes(zeile.beleg_id)) {
              setGewaehlt([zeile.beleg_id]);
              setAnker(index);
            }
            setMenu({ x: event.clientX, y: event.clientY, ids: zielIds, aktuell: zeile.quelle });
          }}
          spalten={[
            { key: "eingang", titel: "Eingang", zelle: (beleg) => datumDE(beleg.eingang) || "—" },
            { key: "partner", titel: "Geschäftspartner", zelle: (beleg) => beleg.partner || beleg.dateiname },
            { key: "betrag", titel: "Betrag", zelle: (beleg) => beleg.betrag ? geld(beleg.betrag) : "—" },
            { key: "datum", titel: "Belegdatum", zelle: (beleg) => datumDE(beleg.datum) || "—" },
            { key: "konto", titel: "Konto", zelle: (beleg) => kontoName(beleg.quelle) },
            { key: "status", titel: "Status", zelle: (beleg) => beleg.datev_gesendet ? `StB ${datumDE(beleg.datev_gesendet)}` : beleg.bewegung_id ? "zugeordnet" : "offen" },
            { key: "dateiname", titel: "Datei", zelle: (beleg) => beleg.dateiname },
          ]}
        />
      </div>
      {menu && (
        <div className="menu" style={{ left: menu.x, top: menu.y }} onClick={(event) => event.stopPropagation()}>
          <div className="menu-titel">
            DATEV-Versand ({menu.ids.length === 1 ? "1 Beleg" : `${menu.ids.length} Belege`})
          </div>
          <button type="button" onClick={() => void belegeAnDatevSenden(menu.ids)}>
            An DATEV senden ({kontoName(menu.aktuell)})
          </button>
          <div className="menu-titel">
            Konto / Kategorie setzen
          </div>
          {kategorien.map((kat) => (
            <button
              key={kat.schluessel}
              type="button"
              className={menu.aktuell === kat.schluessel && menu.ids.length === 1 ? "aktiv" : ""}
              onClick={() => void kontoZuordnen(menu.ids, kat.schluessel)}
            >
              {menu.aktuell === kat.schluessel && menu.ids.length === 1 ? "✓ " : ""}{kat.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );

  const belegSteuerung = aktiv && (
    <div className="beleg-kopf-block">
      <div className="mobil-zurueck-leiste">
        <LinkIntern href="/belege" className="button secondary kompakt-knopf">← Alle Belege</LinkIntern>
        <div className="actions" style={{ margin: 0 }}>
          {vorigeId && <button type="button" className="secondary kompakt-knopf" onClick={() => gehe("/belege/" + vorigeId)} title="Voriger Beleg">‹</button>}
          {naechsteId && <button type="button" className="secondary kompakt-knopf" onClick={() => gehe("/belege/" + naechsteId)} title="Nächster Beleg">›</button>}
        </div>
      </div>
      <div className="detail-kopf">
        <div style={{ minWidth: 0 }}>
          <h2 className="dateiname-zeile">{aktiv.partner || aktiv.dateiname}</h2>
          <p className="hinweis detail-untertitel">
            {aktiv.betrag ? <strong>{geld(aktiv.betrag)}</strong> : "Kein Betrag"} · {datumDE(aktiv.datum) || "Kein Datum"} · {kontoName(aktiv.quelle)}
            {aktiv.datev_gesendet ? ` · StB ${datumDE(aktiv.datev_gesendet)}` : ""}
          </p>
        </div>
        <div className="haupt-aktionen">
          <button type="button" className={bearbeitung ? "secondary" : ""} onClick={() => setBearbeitung(!bearbeitung)}>
            {bearbeitung ? "Nur Vorschau" : "Bearbeiten"}
          </button>
          <button type="button" className="secondary" onClick={() => void belegeAnDatevSenden([aktiv.beleg_id], aktiv.quelle)}>
            An DATEV
          </button>
          <button type="button" className="danger kompakt-knopf" onClick={() => void loeschen(aktiv.beleg_id)}>
            Löschen
          </button>
        </div>
      </div>
      {meldung && <p className="erfolg-hinweis" role="status">{meldung}</p>}
    </div>
  );

  const felder = aktiv && (
    <div className="spalte beleg-felder">
      <div className="nur-desktop-flex liste-werkzeug" style={{ marginBottom: "0.5rem" }}>
        <button type="button" className="secondary kompakt-knopf" onClick={() => setBearbeitung(false)}>← Zur Liste</button>
        <div className="actions" style={{ margin: 0 }}>
          {vorigeId && <button type="button" className="secondary kompakt-knopf" onClick={() => gehe("/belege/" + vorigeId)}>‹ Vorige</button>}
          {naechsteId && <button type="button" className="secondary kompakt-knopf" onClick={() => gehe("/belege/" + naechsteId)}>Nächste ›</button>}
        </div>
      </div>
      <div className="nur-desktop-block">
        <h2 className="dateiname-zeile" style={{ marginTop: 0 }}>{aktiv.dateiname}</h2>
        <p className="hinweis">Belegtyp {aktiv.art} · Konto {kontoName(aktiv.quelle)}</p>
        {meldung && <p className="erfolg-hinweis" role="status">{meldung}</p>}
      </div>
      <p className="hinweis">
        Texterkennung: {ocrText(aktiv.ocr_status || "")}{" "}
        {aktiv.ocr_status !== "text" && aktiv.ocr_status !== "ocr" && (
          <button type="button" className="secondary kompakt-knopf" onClick={() => void ocrLaufen()}>
            {aktiv.ocr_status === "ohne" ? "OCR erneut versuchen" : "Text auslesen (OCR)"}
          </button>
        )}
      </p>
      <div className="form-gruppen">
        <label>Kategorie / Konto
          <select value={belegKonto} onChange={(event) => setBelegKonto(event.target.value)}>
            {!kategorien.some((k) => k.schluessel === belegKonto) && belegKonto && (
              <option value={belegKonto}>{belegKonto}</option>
            )}
            {kategorien.map((kat) => (
              <option key={kat.schluessel} value={kat.schluessel}>{kat.name}</option>
            ))}
          </select>
        </label>
        <label>Rechnungsnummer
          <input value={nummer} onChange={(event) => setNummer(event.target.value)} />
        </label>
        <label>Geschäftspartner
          <input value={partner} onChange={(event) => setPartner(event.target.value)} />
          <span className={"herkunft " + (aktiv.partner_herkunft || "leer")}>{herkunftText(aktiv.partner_herkunft)}</span>
        </label>
        <label>Belegdatum
          <input type="date" value={datum} onChange={(event) => setDatum(event.target.value)} />
          <span className={"herkunft " + (aktiv.datum_herkunft || "leer")}>{herkunftText(aktiv.datum_herkunft)}</span>
        </label>
        <label>Betrag (€)
          <input inputMode="decimal" placeholder="0,00" value={betrag} onChange={(event) => setBetrag(event.target.value)} />
          <span className={"herkunft " + (aktiv.betrag_herkunft || "leer")}>{herkunftText(aktiv.betrag_herkunft)}</span>
        </label>
      </div>
      {aktiv.pruefung && <pre className="pruefung">{aktiv.pruefung}</pre>}
      <div className="actions" style={{ marginTop: "0.85rem" }}>
        <button type="button" onClick={() => void speichern(true)}>Speichern & weiter</button>
        <button type="button" className="secondary" onClick={() => void speichern(false)}>Speichern</button>
        <button type="button" className="secondary" onClick={() => void verfeinern()}>Mit KI verfeinern</button>
        <button type="button" className="secondary nur-desktop-inline" onClick={() => void belegeAnDatevSenden([aktiv.beleg_id], belegKonto || aktiv.quelle)}>
          An DATEV
        </button>
      </div>
    </div>
  );

  return (
    <div className={`seite ${hatDetail ? "hat-detail" : "nur-liste"}`} onDragOver={(event) => event.preventDefault()} onDrop={fallen}>
      {ablage.length > 0 && (
        <AblegenModal
          warteschlange={ablage}
          gesamt={ablageGesamt}
          onDropDateien={dateienDazu}
          onFehler={onFehler}
          onWeiter={async ({ beleg_id, art, rest }) => {
            setAblage((bisher) => bisher.slice(1));
            await laden(konto);
            if (rest <= 0) {
              setAblageGesamt(0);
              if (art === "beleg") gehe("/belege/" + beleg_id);
              else gehe("/kontozeilen");
            }
          }}
          onUeberspringen={() => {
            setAblage((bisher) => {
              const rest = bisher.slice(1);
              if (!rest.length) setAblageGesamt(0);
              return rest;
            });
          }}
          onSchliessen={() => {
            setAblage([]);
            setAblageGesamt(0);
          }}
        />
      )}
      {bearbeitung && aktiv ? (
        <div className="beleg-edit-layout">
          <div className="nur-mobil-block spalte" style={{ paddingBottom: 0 }}>
            {belegSteuerung}
          </div>
          <Teilung
            start={58}
            links={<div className="spalte vorschau-spalte"><BelegAnsicht belegId={aktiv.beleg_id} name={aktiv.dateiname} /></div>}
            rechts={felder}
          />
        </div>
      ) : (
        <Teilung
          start={56}
          links={<div className="master-spalte">{listePane}</div>}
          rechts={
            <div className="detail-spalte spalte">
              {aktiv ? (
                <>
                  {belegSteuerung}
                  <BelegAnsicht belegId={aktiv.beleg_id} name={aktiv.dateiname} />
                </>
              ) : (
                <p className="hinweis vorschau-mitte">Beleg links auswählen oder Datei importieren.</p>
              )}
            </div>
          }
        />
      )}
    </div>
  );
}

export function BelegAnsicht({ belegId, name }: { belegId: number; name: string }) {
  const [kopf, setKopf] = useState<ERechnung | null>(null);

  useEffect(() => {
    let weg = false;
    setKopf(null);
    api<ERechnung>("/api/belege/" + belegId + "/erechnung")
      .then((daten) => { if (!weg) setKopf(daten.vorhanden ? daten : null); })
      .catch(() => { if (!weg) setKopf(null); });
    return () => { weg = true; };
  }, [belegId]);

  return (
    <div className="beleg-ansicht">
      {kopf && (
        <section className="erechnung">
          <h3>Datenvisualisierung E-Rechnung</h3>
          <div className="er-kopf">
            <fieldset className="block"><legend>Verkäufer</legend><p>{kopf.verkaeufer || "—"}</p></fieldset>
            <fieldset className="block er-hervorgehoben"><legend>Rechnungsnummer</legend><p className="er-wert-gross">{kopf.nummer || "—"}</p><p className="hinweis">{kopf.datum}</p></fieldset>
            <fieldset className="block"><legend>Käufer</legend><p>{kopf.kaeufer || "—"}</p></fieldset>
          </div>
          {kopf.positionen.length > 0 && (
            <div className="tabelle-scroll">
              <table>
                <thead><tr><th>Bezeichnung</th><th>Menge</th><th>Preis</th><th>Gesamt</th></tr></thead>
                <tbody>
                  {kopf.positionen.map((zeile, index) => (
                    <tr key={index}>
                      <td>{zeile.bezeichnung}</td>
                      <td>{zeile.menge} {zeile.einheit}</td>
                      <td>{zeile.preis}</td>
                      <td>{zeile.gesamt}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="er-summen">
            <span>Netto {kopf.netto}</span>
            <span>Steuer {kopf.steuer}</span>
            <span className="er-brutto-badge">Brutto <strong>{kopf.brutto}</strong></span>
          </div>
        </section>
      )}
      <DateiVorschau belegId={belegId} name={name} />
    </div>
  );
}

export function DateiVorschau({ belegId, name }: { belegId: number; name: string }) {
  const quelle = "/api/belege/" + belegId + "/datei";
  const bild = /\.(jpe?g|png|gif|webp)$/i.test(name);
  return (
    <div className="vorschau-box">
      {bild ? <img className="vorschau-bild" src={quelle} alt={name} draggable={false} onDragStart={(event) => event.preventDefault()} /> : <PdfVorschau url={quelle} titel={name} />}
      <DateiLink url={quelle} />
    </div>
  );
}
