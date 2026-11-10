import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent } from "react";
import { createPortal } from "react-dom";
import { ApiFehler, betragEingabe, dateiSenden, hatExterneDateien } from "./api";
import { useKategorien } from "./konten";
import { LokaleDateiVorschau } from "./vorschau";

type Erkannt = {
  art?: string;
  quelle?: string;
  partner: string;
  betrag: string;
  datum: string;
  rechnungsnummer: string;
};

export function AblegenModal({
  warteschlange,
  gesamt,
  onWeiter,
  onUeberspringen,
  onSchliessen,
  onDropDateien,
  onFehler,
}: {
  warteschlange: File[];
  gesamt: number;
  onWeiter: (ergebnis: { beleg_id: number; art: "beleg" | "abrechnung"; rest: number }) => void;
  onUeberspringen: () => void;
  onSchliessen: () => void;
  onDropDateien: (dateien: File[]) => void;
  onFehler: (text: string) => void;
}) {
  const kategorien = useKategorien();
  const datei = warteschlange[0] || null;
  const [art, setArt] = useState<"beleg" | "abrechnung">("beleg");
  const [quelle, setQuelle] = useState("");
  const [partner, setPartner] = useState("");
  const [betrag, setBetrag] = useState("");
  const [datum, setDatum] = useState("");
  const [nummer, setNummer] = useState("");
  const [laedt, setLaedt] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  const anfrage = useRef(0);

  useEffect(() => {
    if (!quelle && kategorien[0]) setQuelle(kategorien[0].schluessel);
  }, [kategorien, quelle]);

  useEffect(() => {
    if (datei) {
      dialog.current?.focus();
      void erkennen(datei);
    }
  }, [datei]);

  async function erkennen(file: File) {
    const nr = ++anfrage.current;
    setPartner("");
    setBetrag("");
    setDatum("");
    setNummer("");
    try {
      const daten = await dateiSenden<Erkannt>("/api/belege/erkennen", file, {});
      if (nr !== anfrage.current) return;
      if (daten.art === "abrechnung" || daten.art === "beleg") setArt(daten.art);
      else setArt("beleg");
      if (daten.quelle) setQuelle(daten.quelle);
      setPartner(daten.partner || "");
      setBetrag(betragEingabe(daten.betrag));
      setDatum(daten.datum || "");
      setNummer(daten.rechnungsnummer || "");
      onFehler("");
    } catch (exc) {
      if (nr !== anfrage.current) return;
      onFehler(exc instanceof ApiFehler ? exc.message : "Erkennung fehlgeschlagen.");
    }
  }

  async function verfeinern() {
    if (!datei) return;
    setLaedt(true);
    try {
      const daten = await dateiSenden<Erkannt>("/api/belege/ki", datei, {});
      if (daten.partner) setPartner(daten.partner);
      if (daten.betrag) setBetrag(betragEingabe(daten.betrag));
      if (daten.datum) setDatum(daten.datum);
      if (daten.rechnungsnummer) setNummer(daten.rechnungsnummer);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "KI nicht erreichbar.");
    } finally {
      setLaedt(false);
    }
  }

  async function speichern() {
    if (!datei || !quelle || laedt) return;
    setLaedt(true);
    const felder: Record<string, string> = { art, quelle };
    if (art === "beleg") {
      felder.partner = partner;
      felder.betrag = betrag;
      felder.datum = datum;
      felder.rechnungsnummer = nummer;
    }
    try {
      const antwort = await dateiSenden<{ beleg_id: number }>("/api/belege", datei, felder);
      onFehler("");
      onWeiter({ beleg_id: antwort.beleg_id, art, rest: warteschlange.length - 1 });
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Import fehlgeschlagen.");
    } finally {
      setLaedt(false);
    }
  }

  function fallen(event: DragEvent) {
    event.preventDefault();
    if (!hatExterneDateien(event.dataTransfer)) return;
    const liste = [...event.dataTransfer.files];
    if (liste.length) onDropDateien(liste);
  }

  function einfuegen(event: ClipboardEvent) {
    const ausDateien = [...event.clipboardData.files];
    const ausItems = [...event.clipboardData.items]
      .map((item) => (item.kind === "file" ? item.getAsFile() : null))
      .filter((f): f is File => Boolean(f));
    const liste = ausDateien.length ? ausDateien : ausItems;
    if (!liste.length) return;
    event.preventDefault();
    onDropDateien(liste);
  }

  if (!datei) return null;
  const aktuellNr = Math.max(1, gesamt - warteschlange.length + 1);
  const hatWeitere = warteschlange.length > 1;

  const modal = (
    <div className="fenster-grund" onDragOver={(event) => event.preventDefault()} onDrop={fallen}>
      <div className="fenster fenster-breit" role="dialog" aria-label="Ablegen" tabIndex={-1} ref={dialog} onPaste={einfuegen}>
        <div className="ablage-split">
          <div className="ablage-links">
            <div className="vorschau-kopf">
              <h2>Ablegen</h2>
              {gesamt > 1 && <span className="hinweis">Datei {aktuellNr} von {gesamt} ({warteschlange.length} offen)</span>}
            </div>
            <p className="hinweis">{datei.name}</p>
            <div className="actions">
              <button type="button" className={art === "abrechnung" ? "" : "secondary"} onClick={() => setArt("abrechnung")}>Kontoauszug</button>
              <button type="button" className={art === "beleg" ? "" : "secondary"} onClick={() => { setArt("beleg"); void erkennen(datei); }}>Beleg</button>
            </div>
            <div className="actions">
              {kategorien.map((konto) => (
                <button key={konto.schluessel} type="button" className={quelle === konto.schluessel ? "" : "secondary"} onClick={() => setQuelle(konto.schluessel)}>
                  {konto.name}
                </button>
              ))}
            </div>
            {art === "beleg" && (
              <div className="grid">
                <label>Geschäftspartner<input value={partner} onChange={(event) => setPartner(event.target.value)} /></label>
                <label>Betrag<input inputMode="decimal" placeholder="0,00" value={betrag} onChange={(event) => setBetrag(event.target.value)} /></label>
                <label>Datum<input type="date" value={datum} onChange={(event) => setDatum(event.target.value)} /></label>
                <label>Rechnungsnummer<input value={nummer} onChange={(event) => setNummer(event.target.value)} /></label>
                <button type="button" className="secondary" disabled={laedt} onClick={() => void verfeinern()}>Mit KI verfeinern</button>
              </div>
            )}
            <div className="actions">
              <button type="button" disabled={!datei || !quelle || laedt} onClick={() => void speichern()}>
                {hatWeitere ? `Importieren & weiter (${warteschlange.length - 1} weitere)` : "Importieren"}
              </button>
              {hatWeitere && (
                <button type="button" className="secondary" disabled={laedt} onClick={onUeberspringen}>
                  Überspringen
                </button>
              )}
              <button type="button" className="secondary" onClick={onSchliessen}>Abbrechen</button>
            </div>
          </div>
          <div className="ablage-vorschau">
            <LokaleDateiVorschau datei={datei} />
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}

export function Ablegen({ onFehler }: { onFehler: (text: string) => void }) {
  const [warteschlange, setWarteschlange] = useState<File[]>([]);
  const [gesamt, setGesamt] = useState(0);
  const dateiInput = useRef<HTMLInputElement>(null);

  function dazu(dateien: File[]) {
    if (!dateien.length) return;
    setWarteschlange((bisher) => {
      const neu = [...bisher, ...dateien];
      setGesamt((alt) => (bisher.length === 0 ? dateien.length : alt + dateien.length));
      return neu;
    });
  }

  function fallen(event: DragEvent) {
    event.preventDefault();
    if (!hatExterneDateien(event.dataTransfer)) return;
    dazu([...event.dataTransfer.files]);
  }

  function einfuegen(event: ClipboardEvent) {
    const ausDateien = [...event.clipboardData.files];
    const ausItems = [...event.clipboardData.items]
      .map((item) => (item.kind === "file" ? item.getAsFile() : null))
      .filter((f): f is File => Boolean(f));
    const liste = ausDateien.length ? ausDateien : ausItems;
    if (!liste.length) return;
    event.preventDefault();
    dazu(liste);
  }

  return (
    <>
      <div
        className="ablage-nav"
        tabIndex={0}
        onClick={() => dateiInput.current?.click()}
        onDragEnter={(event) => event.preventDefault()}
        onDragOver={(event) => event.preventDefault()}
        onDrop={fallen}
        onPaste={einfuegen}
      >
        Dokumente ablegen
        <input
          ref={dateiInput}
          type="file"
          multiple
          accept="image/*,application/pdf,.csv,.xml,.sta,.mt940,.txt"
          style={{ display: "none" }}
          onChange={(event) => {
            if (event.target.files?.length) dazu([...event.target.files]);
            event.target.value = "";
          }}
        />
      </div>
      {warteschlange.length > 0 && (
        <AblegenModal
          warteschlange={warteschlange}
          gesamt={gesamt}
          onDropDateien={dazu}
          onFehler={onFehler}
          onWeiter={({ beleg_id, art, rest }) => {
            setWarteschlange((bisher) => bisher.slice(1));
            window.dispatchEvent(new CustomEvent("buchhaltung:belege-aktualisiert", { detail: { beleg_id, art } }));
            if (rest <= 0) {
              setGesamt(0);
            }
          }}
          onUeberspringen={() => {
            setWarteschlange((bisher) => {
              const rest = bisher.slice(1);
              if (!rest.length) setGesamt(0);
              return rest;
            });
          }}
          onSchliessen={() => {
            setWarteschlange([]);
            setGesamt(0);
          }}
        />
      )}
    </>
  );
}
