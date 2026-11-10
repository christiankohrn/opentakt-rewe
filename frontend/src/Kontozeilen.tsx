import { useEffect, useState, type DragEvent } from "react";
import { ApiFehler, api, dateiSpeichern, datumDE, geld, hatExterneDateien } from "./api";
import { AblegenModal } from "./Ablegen";
import { BelegAnsicht } from "./Belege";
import { KontoFilter } from "./konten";
import { DatenListe, zeilenWahl, type Sortierung } from "./liste";
import { gehe } from "./nav";
import { Teilung } from "./teilen";

type Kurz = {
  bewegung_id: number;
  quelle: string;
  datum: string;
  betrag: string;
  waehrung: string;
  gegenpartei: string;
  zweck: string;
  import_beleg_id?: number | null;
  import_dateiname?: string;
  beleg_id: number | null;
  beleg_dateiname: string;
  beleg_anzahl?: number;
  beleg_ids?: number[];
  geprueft: boolean;
  datev_geliefert?: string | null;
};

type AbrechnungDatei = {
  beleg_id: number;
  dateiname: string;
  quelle: string;
  eingang: string | null;
  von: string | null;
  bis: string | null;
  umsaetze: number;
  geprueft: number;
  zugeordnet: number;
  geliefert: number;
  datev_gesendet: string | null;
  datei_vorhanden: boolean;
};

type ExportVorgangEintrag = {
  export_id: number;
  zeitpunkt: string;
  art: string;
  konto: string;
  konten?: string[];
  zusammenfassung: string;
  belege_anzahl: number;
  rechnungen_anzahl: number;
  bewegungen_anzahl: number;
  emails_gesendet: number;
};

type Vorschlag = {
  beleg_id: number;
  dateiname: string;
  partner: string;
  rechnungsnummer?: string;
  quelle?: string;
  betrag: string | null;
  datum: string | null;
  eingang?: string | null;
  grund: string;
  zugeordnet?: boolean;
};

type Zeile = Kurz & {
  sicherheit: string;
  vorschlaege: Vorschlag[];
  uebrige: Vorschlag[];
  beleg_ids: number[];
  ausgeblendet?: number;
  naechste_id: number | null;
  vorige_id?: number | null;
};

export function KontozeilenSeite({ bewegungId, onFehler }: { bewegungId: number | null; onFehler: (text: string) => void }) {
  const [ansicht, setAnsicht] = useState<"umsaetze" | "abrechnungen" | "exporte">("umsaetze");
  const [liste, setListe] = useState<Kurz[]>([]);
  const [abrechnungen, setAbrechnungen] = useState<AbrechnungDatei[]>([]);
  const [exporte, setExporte] = useState<ExportVorgangEintrag[]>([]);
  const [exportLaedt, setExportLaedt] = useState(false);
  const [exportHinweis, setExportHinweis] = useState("");
  const [aktiveAbrechnung, setAktiveAbrechnung] = useState<number | null>(null);
  const [abrMenu, setAbrMenu] = useState<{ x: number; y: number; eintrag: AbrechnungDatei } | null>(null);
  const [konto, setKonto] = useState("");
  const [suche, setSuche] = useState("");
  const [sortierung, setSortierung] = useState<Sortierung | null>(null);
  const [gewaehlt, setGewaehlt] = useState<number[]>([]);
  const [anker, setAnker] = useState(-1);
  const [detail, setDetail] = useState(false);
  const [zeile, setZeile] = useState<Zeile | null>(null);
  const [geprueft, setGeprueft] = useState(false);
  const [belegIds, setBelegIds] = useState<number[]>([]);
  const [anzeige, setAnzeige] = useState<number | null>(null);
  const [belegSuche, setBelegSuche] = useState("");
  const [alleBelege, setAlleBelege] = useState(false);
  const [ablage, setAblage] = useState<File[]>([]);
  const [ablageGesamt, setAblageGesamt] = useState(0);

  async function laden(filter: string) {
    const q = filter ? "?konto=" + encodeURIComponent(filter) : "";
    const [daten, dateien, vorgaenge] = await Promise.all([
      api<Kurz[]>("/api/bewegungen" + q),
      api<AbrechnungDatei[]>("/api/abrechnungen/dateien" + q),
      api<ExportVorgangEintrag[]>("/api/exporte"),
    ]);
    setListe(daten);
    setAbrechnungen(dateien);
    setExporte(vorgaenge);
    onFehler("");
  }

  useEffect(() => {
    laden(konto).catch((exc) => onFehler(exc instanceof ApiFehler ? exc.message : "Kontozeilen fehlen."));
  }, [konto]);

  useEffect(() => {
    const neuLaden = () => {
      laden(konto).catch(() => undefined);
      if (detail && bewegungId) oeffnen(bewegungId, alleBelege).catch(() => undefined);
    };
    window.addEventListener("buchhaltung:belege-aktualisiert", neuLaden);
    return () => window.removeEventListener("buchhaltung:belege-aktualisiert", neuLaden);
  }, [konto, detail, bewegungId, alleBelege]);

  async function oeffnen(id: number, zeigeAlle: boolean = false) {
    const params = new URLSearchParams();
    if (konto) params.set("konto", konto);
    if (zeigeAlle) params.set("alle_belege", "true");
    const query = params.toString() ? "?" + params.toString() : "";
    const daten = await api<Zeile>("/api/bewegungen/" + id + query);
    setZeile(daten);
    setGeprueft(daten.geprueft);
    const ids = daten.beleg_ids || (daten.beleg_id ? [daten.beleg_id] : []);
    setBelegIds(ids);
    const ersteVorschau = ids[0] ?? daten.vorschlaege[0]?.beleg_id ?? daten.uebrige[0]?.beleg_id ?? null;
    setAnzeige((bisher) => (bisher && [...ids, ...daten.vorschlaege.map((v) => v.beleg_id), ...(daten.uebrige || []).map((v) => v.beleg_id)].includes(bisher) ? bisher : ersteVorschau));
  }

  useEffect(() => {
    if (detail && bewegungId) {
      setAlleBelege(false);
      oeffnen(bewegungId, false).catch((exc) => onFehler(exc instanceof ApiFehler ? exc.message : "Zeile fehlt."));
    }
  }, [detail, bewegungId, konto]);

  async function haekchen(id: number, wert: boolean) {
    setListe((bisher) => bisher.map((eintrag) => eintrag.bewegung_id === id ? { ...eintrag, geprueft: wert } : eintrag));
    try {
      await api("/api/bewegungen/" + id + "/geprueft", { method: "POST", body: JSON.stringify({ geprueft: wert }) });
    } catch (exc) {
      setListe((bisher) => bisher.map((eintrag) => eintrag.bewegung_id === id ? { ...eintrag, geprueft: !wert } : eintrag));
      onFehler(exc instanceof ApiFehler ? exc.message : "Geprüft nicht gespeichert.");
    }
  }

  async function zuordnen(zielIds: number[] = belegIds) {
    if (!zeile) return;
    try {
      await api("/api/bewegungen/" + zeile.bewegung_id + "/zuordnung", {
        method: "POST",
        body: JSON.stringify({ beleg_ids: zielIds }),
      });
      await laden(konto);
      await oeffnen(zeile.bewegung_id, alleBelege);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Zuordnen fehlgeschlagen.");
    }
  }

  async function speichern(weiter: boolean = true) {
    if (!zeile) return;
    try {
      const antwort = await api<{ naechste_id: number | null }>("/api/bewegungen/" + zeile.bewegung_id + "/weiter", {
        method: "POST",
        body: JSON.stringify({ geprueft: geprueft || belegIds.length > 0, beleg_ids: belegIds, konto }),
      });
      await laden(konto);
      onFehler("");
      if (weiter && antwort.naechste_id) gehe("/kontozeilen/" + antwort.naechste_id);
      else setDetail(false);
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Speichern fehlgeschlagen.");
    }
  }

  async function umsaetzeLoeschen() {
    const ids = gewaehlt.length ? gewaehlt : bewegungId ? [bewegungId] : [];
    if (!ids.length) return;
    const frage = ids.length === 1
      ? "Soll diese Kontozeile gelöscht werden?"
      : `Sollen ${ids.length} Kontozeilen gelöscht werden?`;
    if (!window.confirm(frage)) return;
    try {
      for (const id of ids) await api("/api/bewegungen/" + id, { method: "DELETE" });
      setGewaehlt([]);
      if (bewegungId && ids.includes(bewegungId)) {
        setDetail(false);
        gehe("/kontozeilen");
      }
      await laden(konto);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Löschen fehlgeschlagen.");
    }
  }

  async function abrechnungLoeschen(belegId?: number) {
    const zielId = belegId ?? aktiveAbrechnung;
    const eintrag = abrechnungen.find((a) => a.beleg_id === zielId);
    if (!eintrag) return;
    if (!window.confirm(`Soll die Abrechnung "${eintrag.dateiname}" inklusive aller ${eintrag.umsaetze} zugehörigen Kontozeilen gelöscht werden?`)) return;
    try {
      await api("/api/belege/" + eintrag.beleg_id, { method: "DELETE" });
      if (aktiveAbrechnung === eintrag.beleg_id) setAktiveAbrechnung(null);
      setDetail(false);
      await laden(konto);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Abrechnung konnte nicht gelöscht werden.");
    }
  }

  async function datevExport(nurUngeliefert: boolean, markieren: boolean) {
    const params = new URLSearchParams();
    if (konto) params.set("konto", konto);
    if (nurUngeliefert) params.set("nur_ungeliefert", "true");
    if (markieren) params.set("markieren", "true");
    const suffix = params.toString() ? "?" + params.toString() : "";
    try {
      await dateiSpeichern("/api/datev/zip" + suffix, `datev-${konto || "alle"}.zip`);
      if (markieren) await laden(konto);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "DATEV-Export fehlgeschlagen.");
    }
  }

  async function weiterverarbeitungDownload(zielKonto: string) {
    if (!zielKonto) return;
    try {
      await dateiSpeichern("/api/datev/weiterverarbeitung?konto=" + encodeURIComponent(zielKonto), `DATEV_Weiterverarbeitung_${zielKonto}.csv`);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Weiterverarbeitungsdatei fehlgeschlagen.");
    }
  }

  async function emailExportStarten(nurUngeliefert: boolean = true) {
    setExportLaedt(true);
    setExportHinweis("");
    try {
      const antwort = await api<{ zusammenfassung: string }>("/api/exporte/email", {
        method: "POST",
        body: JSON.stringify({ konto, nur_ungeliefert: nurUngeliefert }),
      });
      setExportHinweis(antwort.zusammenfassung);
      await laden(konto);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "E-Mail-Export fehlgeschlagen.");
    } finally {
      setExportLaedt(false);
    }
  }

  useEffect(() => {
    if (!abrMenu) return;
    const schliessen = () => setAbrMenu(null);
    window.addEventListener("click", schliessen);
    window.addEventListener("scroll", schliessen, true);
    return () => {
      window.removeEventListener("click", schliessen);
      window.removeEventListener("scroll", schliessen, true);
    };
  }, [abrMenu]);

  async function abrechnungAnDatevSenden(eintrag: AbrechnungDatei) {
    setAbrMenu(null);
    try {
      const antwort = await api<{ gesendet_an: string }>("/api/belege/" + eintrag.beleg_id + "/datev", {
        method: "POST",
        body: JSON.stringify({ adresse: eintrag.quelle }),
      });
      setExportHinweis(`Abrechnung ${eintrag.dateiname} an ${antwort.gesendet_an} gesendet.`);
      await laden(konto);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Abrechnungsversand fehlgeschlagen.");
    }
  }

  async function exportWiederholen(exportId: number, zielKonto: string = "") {
    setExportLaedt(true);
    setExportHinweis("");
    try {
      const antwort = await api<{ zusammenfassung: string }>("/api/exporte/" + exportId + "/wiederholen", {
        method: "POST",
        body: JSON.stringify({ konto: zielKonto }),
      });
      setExportHinweis(`Erneut versendet${zielKonto ? ` (${zielKonto.toUpperCase()})` : ""}: ${antwort.zusammenfassung}`);
      await laden(konto);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Erneuter Versand fehlgeschlagen.");
    } finally {
      setExportLaedt(false);
    }
  }

  const gefiltert = liste.filter((eintrag) => {
    const q = suche.trim().toLowerCase();
    if (!q) return true;
    const text = `${eintrag.gegenpartei} ${eintrag.zweck} ${eintrag.betrag} ${eintrag.datum} ${eintrag.beleg_dateiname} ${eintrag.import_dateiname || ""}`.toLowerCase();
    return text.includes(q);
  });

  const sichtbar = sortierung
    ? gefiltert.slice().sort((links, rechts) => {
      const wert = (eintrag: Kurz) => sortierung.spalte === "betrag" ? Number(eintrag.betrag) : sortierung.spalte === "gegenpartei" ? eintrag.gegenpartei : sortierung.spalte === "zweck" ? eintrag.zweck : eintrag.datum;
      const faktor = sortierung.richtung === "ab" ? -1 : 1;
      const a = wert(links);
      const b = wert(rechts);
      if (a < b) return -1 * faktor;
      if (a > b) return 1 * faktor;
      return 0;
    })
    : gefiltert;

  const gewaehltZeile = liste.find((eintrag) => eintrag.bewegung_id === bewegungId) || null;
  const index = sichtbar.findIndex((eintrag) => eintrag.bewegung_id === bewegungId);
  const vorschau = detail ? zeile : gewaehltZeile;
  const alle = [...(zeile?.vorschlaege || []), ...(zeile?.uebrige || [])];
  const gewaehlterName = alle.find((vorschlag) => vorschlag.beleg_id === anzeige)?.dateiname;
  const aktiveAbrObj = abrechnungen.find((a) => a.beleg_id === aktiveAbrechnung) || null;
  const vorschauName = ansicht === "abrechnungen" && !detail
    ? (aktiveAbrObj?.dateiname || "abrechnung.pdf")
    : (detail ? gewaehlterName : null) || vorschau?.beleg_dateiname || vorschau?.import_dateiname || "beleg.pdf";
  const vorschauId = ansicht === "abrechnungen" && !detail
    ? aktiveAbrechnung
    : detail
      ? anzeige
      : (vorschau?.beleg_id || vorschau?.import_beleg_id || null);
  const stapelIds = ansicht === "abrechnungen" && !detail
    ? []
    : detail
      ? (belegIds.length > 1 ? belegIds : [])
      : ((vorschau?.beleg_ids?.length || 0) > 1 ? vorschau?.beleg_ids || [] : []);

  function nameFuer(id: number): string {
    const treffer = alle.find((vorschlag) => vorschlag.beleg_id === id);
    if (treffer?.dateiname) return treffer.dateiname;
    if (vorschau?.beleg_id === id && vorschau.beleg_dateiname) return vorschau.beleg_dateiname;
    if (vorschau?.import_beleg_id === id && vorschau.import_dateiname) return vorschau.import_dateiname;
    return "beleg.pdf";
  }

  function umschalten(id: number) {
    setBelegIds((bisher) => {
      const neu = bisher.includes(id) ? bisher.filter((eintrag) => eintrag !== id) : [...bisher, id];
      if (neu.length > 0) setGeprueft(true);
      return neu;
    });
    setAnzeige(id);
  }

  function filterBelege(eintraege: Vorschlag[]): Vorschlag[] {
    const q = belegSuche.trim().toLowerCase();
    if (!q) return eintraege;
    return eintraege.filter((v) => {
      const text = `${v.dateiname} ${v.partner} ${v.rechnungsnummer || ""} ${v.betrag || ""} ${v.datum || ""} ${v.grund || ""}`.toLowerCase();
      return text.includes(q);
    });
  }

  function belegTabelle(titel: string, eintraege: Vorschlag[]) {
    const gefiltert = filterBelege(eintraege);
    return (
      <>
        <h2>{titel} ({gefiltert.length})</h2>
        {gefiltert.length === 0 && <p className="hinweis">Keine Belege.</p>}
        {gefiltert.length > 0 && (
          <DatenListe
            zeilen={gefiltert}
            zeilenId={(vorschlag) => vorschlag.beleg_id}
            href={(vorschlag) => "/belege/" + vorschlag.beleg_id}
            aktivId={anzeige}
            gewaehlt={belegIds}
            sortierung={null}
            onSort={() => undefined}
            onZeile={(_event, indexZeile) => setAnzeige(gefiltert[indexZeile].beleg_id)}
            onDoppel={(indexZeile) => umschalten(gefiltert[indexZeile].beleg_id)}
            vorn={(vorschlag) => (
              <input
                type="checkbox"
                aria-label={vorschlag.zugeordnet ? "zugeordnet" : "Beleg"}
                checked={belegIds.includes(vorschlag.beleg_id)}
                onClick={(event) => event.stopPropagation()}
                onDoubleClick={(event) => event.stopPropagation()}
                onChange={() => umschalten(vorschlag.beleg_id)}
              />
            )}
            spalten={[
              { key: "datum", titel: "Belegdatum", zelle: (vorschlag) => datumDE(vorschlag.datum) || "—" },
              { key: "partner", titel: "Geschäftspartner", zelle: (vorschlag) => vorschlag.partner || "—" },
              { key: "betrag", titel: "Rechnungsbetrag", zelle: (vorschlag) => vorschlag.betrag ? geld(vorschlag.betrag) : "—" },
              { key: "grund", titel: "Treffer", zelle: (vorschlag) => vorschlag.grund || "—" },
              { key: "dateiname", titel: "Dateiname", zelle: (vorschlag) => vorschlag.dateiname },
            ]}
          />
        )}
      </>
    );
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

  const listePane = (
    <div className="liste-spalte dicht">
      <div className="liste-werkzeug">
        <h2>
          {ansicht === "umsaetze"
            ? `Kontoumsatz ${index >= 0 ? index + 1 : 0} / ${sichtbar.length}`
            : ansicht === "abrechnungen"
              ? `Abrechnungen (${abrechnungen.length})`
              : `Export-Vorgänge (${exporte.length})`}
        </h2>
        <div className="actions">
          <button type="button" className={ansicht === "umsaetze" ? "" : "secondary"} onClick={() => setAnsicht("umsaetze")}>
            Umsätze ({liste.length})
          </button>
          <button
            type="button"
            className={ansicht === "abrechnungen" ? "" : "secondary"}
            onClick={() => {
              setAnsicht("abrechnungen");
              if (!aktiveAbrechnung && abrechnungen[0]) setAktiveAbrechnung(abrechnungen[0].beleg_id);
            }}
          >
            Abrechnungen ({abrechnungen.length})
          </button>
          <button
            type="button"
            className={ansicht === "exporte" ? "" : "secondary"}
            onClick={() => setAnsicht("exporte")}
          >
            Exporte ({exporte.length})
          </button>
        </div>
      </div>
      <KontoFilter wert={konto} onChange={setKonto} />
      {exportHinweis && <p className="hinweis"><strong>{exportHinweis}</strong></p>}
      {ansicht === "umsaetze" ? (
        <>
          <label>
            Suche
            <input
              value={suche}
              placeholder="Empfänger, Verwendungszweck, Betrag …"
              onChange={(event) => setSuche(event.target.value)}
            />
          </label>
          <div className="actions">
            <button type="button" disabled={exportLaedt} onClick={() => void emailExportStarten(true)}>
              {exportLaedt ? "Sende E-Mails …" : "E-Mail-Export starten (ungeliefert)"}
            </button>
            {konto && (
              <button type="button" className="secondary" onClick={() => void weiterverarbeitungDownload(konto)}>
                Datev-Datei
              </button>
            )}
            <button type="button" className="secondary" onClick={() => { setSortierung(null); setSuche(""); setAnker(-1); }}>Zurücksetzen</button>
            <button type="button" className="danger" onClick={() => void umsaetzeLoeschen()}>Kontozeile löschen</button>
          </div>
          <div className="liste-scroll">
            <DatenListe
              zeilen={sichtbar}
              zeilenId={(eintrag) => eintrag.bewegung_id}
              href={(eintrag) => "/kontozeilen/" + eintrag.bewegung_id}
              aktivId={bewegungId}
              gewaehlt={gewaehlt}
              sortierung={sortierung}
              onSort={(spalte) => setSortierung((bisher) => bisher?.spalte === spalte ? { spalte, richtung: bisher.richtung === "ab" ? "auf" : "ab" } : { spalte, richtung: "ab" })}
              onZeile={(event, indexZeile) => {
                const ids = sichtbar.map((eintrag) => eintrag.bewegung_id);
                const ergebnis = zeilenWahl(event, indexZeile, ids, gewaehlt, anker);
                setGewaehlt(ergebnis.ids);
                setAnker(ergebnis.anker);
                setDetail(false);
                gehe("/kontozeilen/" + ids[indexZeile]);
              }}
              onDoppel={(indexZeile) => {
                setDetail(true);
                gehe("/kontozeilen/" + sichtbar[indexZeile].bewegung_id);
              }}
              vorn={(eintrag) => (
                <input
                  type="checkbox"
                  aria-label="geprüft"
                  checked={eintrag.geprueft}
                  onClick={(event) => event.stopPropagation()}
                  onDoubleClick={(event) => event.stopPropagation()}
                  onChange={(event) => void haekchen(eintrag.bewegung_id, event.target.checked)}
                />
              )}
              klasse={(eintrag) => eintrag.geprueft ? "" : "offen"}
              spalten={[
                { key: "beleg", titel: "Beleg", zelle: (eintrag) => (eintrag.beleg_anzahl || 0) > 1 ? eintrag.beleg_anzahl + " Belege" : eintrag.beleg_id ? "Beleg" : "" },
                { key: "datum", titel: "Datum", zelle: (eintrag) => datumDE(eintrag.datum) },
                { key: "gegenpartei", titel: "Empfänger/Auftraggeber", zelle: (eintrag) => eintrag.gegenpartei },
                { key: "zweck", titel: "Verwendungszweck", zelle: (eintrag) => eintrag.zweck },
                { key: "betrag", titel: "Betrag", zelle: (eintrag) => <span className={Number(eintrag.betrag) < 0 ? "betrag-negativ" : ""}>{geld(eintrag.betrag)}</span> },
                { key: "geliefert", titel: "StB", zelle: (eintrag) => eintrag.datev_geliefert ? datumDE(eintrag.datev_geliefert) : "offen" },
              ]}
            />
          </div>
        </>
      ) : ansicht === "abrechnungen" ? (
        <>
          <div className="actions">
            <button type="button" disabled={exportLaedt} onClick={() => void emailExportStarten(true)}>
              {exportLaedt ? "Sende E-Mails …" : "E-Mail-Export starten (ungeliefert)"}
            </button>
            <button type="button" className="danger" disabled={!aktiveAbrechnung} onClick={() => void abrechnungLoeschen()}>
              Ganze Abrechnung löschen
            </button>
          </div>
          <div className="liste-scroll">
            <DatenListe
              zeilen={abrechnungen}
              zeilenId={(eintrag) => eintrag.beleg_id}
              href={(eintrag) => "/belege/" + eintrag.beleg_id}
              aktivId={aktiveAbrechnung}
              gewaehlt={aktiveAbrechnung ? [aktiveAbrechnung] : []}
              sortierung={null}
              onSort={() => undefined}
              onZeile={(_event, indexZeile) => setAktiveAbrechnung(abrechnungen[indexZeile].beleg_id)}
              onKontext={(event, indexZeile) => {
                const eintrag = abrechnungen[indexZeile];
                setAktiveAbrechnung(eintrag.beleg_id);
                setAbrMenu({ x: event.clientX, y: event.clientY, eintrag });
              }}
              spalten={[
                { key: "quelle", titel: "Konto", zelle: (eintrag) => eintrag.quelle.toUpperCase() },
                { key: "dateiname", titel: "Abrechnungsdatei", zelle: (eintrag) => eintrag.dateiname },
                { key: "zeitraum", titel: "Zeitraum", zelle: (eintrag) => eintrag.von && eintrag.bis ? `${datumDE(eintrag.von)} – ${datumDE(eintrag.bis)}` : datumDE(eintrag.eingang) || "—" },
                { key: "umsaetze", titel: "Umsätze", zelle: (eintrag) => `${eintrag.zugeordnet}/${eintrag.umsaetze} Belege · ${eintrag.geprueft} gepr.` },
                { key: "stb", titel: "StB-Lieferung", zelle: (eintrag) => eintrag.datev_gesendet ? datumDE(eintrag.datev_gesendet) : `${eintrag.geliefert}/${eintrag.umsaetze}` },
              ]}
            />
          </div>
          {abrMenu && (
            <div className="menu" style={{ left: abrMenu.x, top: abrMenu.y }} onClick={(event) => event.stopPropagation()}>
              <div className="menu-titel">{abrMenu.eintrag.dateiname}</div>
              <button type="button" onClick={() => void abrechnungAnDatevSenden(abrMenu.eintrag)}>
                An DATEV senden ({abrMenu.eintrag.quelle.toUpperCase()})
              </button>
              <button type="button" onClick={() => { const id = abrMenu.eintrag.beleg_id; setAbrMenu(null); void abrechnungLoeschen(id); }}>
                Ganze Abrechnung löschen
              </button>
            </div>
          )}
        </>
      ) : (
        <>
          <div className="actions">
            <button type="button" disabled={exportLaedt} onClick={() => void emailExportStarten(true)}>
              {exportLaedt ? "Sende E-Mails …" : "E-Mail-Export starten (ungeliefert)"}
            </button>
            {konto && (
              <button type="button" className="secondary" onClick={() => void weiterverarbeitungDownload(konto)}>
                Datev-Datei
              </button>
            )}
            <button type="button" className="secondary" onClick={() => void datevExport(true, true)}>
              XML-ZIP (ungeliefert)
            </button>
          </div>
          <div className="liste-scroll">
            {exporte.length === 0 ? (
              <p className="hinweis">Noch keine Export-Vorgänge durchgeführt.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Zeitpunkt</th>
                    <th>Art</th>
                    <th>Konto</th>
                    <th>Umfang</th>
                    <th>Erneut per E-Mail senden</th>
                  </tr>
                </thead>
                <tbody>
                  {exporte.map((vorgang) => (
                    <tr key={vorgang.export_id}>
                      <td>{datumDE(vorgang.zeitpunkt)} {vorgang.zeitpunkt.slice(11, 16)}</td>
                      <td>{vorgang.art === "email" ? "E-Mail" : "ZIP"}</td>
                      <td>{vorgang.konto ? vorgang.konto.toUpperCase() : "Alle"}</td>
                      <td>{vorgang.zusammenfassung}</td>
                      <td>
                        <div className="actions" style={{ gap: "0.3rem", flexWrap: "wrap" }}>
                          <button
                            type="button"
                            className="secondary"
                            disabled={exportLaedt}
                            onClick={() => void exportWiederholen(vorgang.export_id, konto)}
                          >
                            {konto ? `Nur ${konto.toUpperCase()}` : "Alle erneut senden"}
                          </button>
                          {!konto && (vorgang.konten || []).length > 1 && (vorgang.konten || []).map((k) => (
                            <button
                              key={k}
                              type="button"
                              className="secondary"
                              disabled={exportLaedt}
                              onClick={() => void exportWiederholen(vorgang.export_id, k)}
                            >
                              {k === "ausgang" ? "Ausgangsrechn." : k.toUpperCase()}
                            </button>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );

  const gewaehlteSumme = belegIds.reduce((sum, id) => {
    const treffer = alle.find((v) => v.beleg_id === id);
    return sum + (treffer?.betrag ? Math.abs(Number(treffer.betrag)) : 0);
  }, 0);
  const zielBetrag = zeile ? Math.abs(Number(zeile.betrag)) : 0;
  const differenz = Math.round((zielBetrag - gewaehlteSumme) * 100) / 100;

  const umsatz = zeile && (
    <div className="liste-spalte dicht">
      <div className="actions">
        <button type="button" className="secondary" onClick={() => setDetail(false)}>Zur Liste</button>
        {zeile.vorige_id && (
          <button type="button" className="secondary" onClick={() => gehe("/kontozeilen/" + zeile.vorige_id)}>← Vorige</button>
        )}
        {zeile.naechste_id && (
          <button type="button" className="secondary" onClick={() => gehe("/kontozeilen/" + zeile.naechste_id)}>Nächste →</button>
        )}
      </div>
      <fieldset className="block">
        <legend>Kontoumsatz ({zeile.quelle.toUpperCase()})</legend>
        <p>
          <strong>{datumDE(zeile.datum)}</strong> · <strong>{zeile.gegenpartei || "—"}</strong> ·{" "}
          <strong className={Number(zeile.betrag) < 0 ? "betrag-negativ" : ""}>{geld(zeile.betrag)} {zeile.waehrung}</strong>
        </p>
        {zeile.zweck && <p className="hinweis">{zeile.zweck}</p>}
        {zeile.import_dateiname && (
          <p className="hinweis">
            Abrechnungsdatei:{" "}
            <button type="button" className="sort" onClick={() => { if (zeile.import_beleg_id) setAnzeige(zeile.import_beleg_id); }}>
              {zeile.import_dateiname}
            </button>
          </p>
        )}
      </fieldset>
      <p>
        {belegIds.length
          ? `${belegIds.length} ${belegIds.length === 1 ? "Beleg" : "Belege"} gewählt (${geld(gewaehlteSumme.toFixed(2))} EUR${Math.abs(differenz) > 0.005 ? ` · Differenz ${geld(differenz.toFixed(2))} EUR` : " · Betrag passt"})`
          : "Kein Beleg zugeordnet (Zeile anklicken für Vorschau, Doppelklick oder Häkchen zum Auswählen)"}
      </p>
      <label>
        Belege filtern
        <input
          value={belegSuche}
          placeholder="Partner, Betrag, Rechnungsnr. oder Dateiname …"
          onChange={(event) => setBelegSuche(event.target.value)}
        />
      </label>
      <div className="liste-scroll">
        {belegTabelle("Vorschläge", zeile.vorschlaege)}
        {belegTabelle(alleBelege ? "Alle übrigen" : "Weitere (bis 30 Tage vor Buchung)", zeile.uebrige || [])}
        {!alleBelege && (zeile.ausgeblendet || 0) > 0 && (
          <p style={{ marginTop: "0.6rem" }}>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setAlleBelege(true);
                void oeffnen(zeile.bewegung_id, true);
              }}
            >
              Ältere / alle Belege laden ({zeile.ausgeblendet} weitere)
            </button>
          </p>
        )}
      </div>
      <label className="check">
        <input type="checkbox" checked={geprueft} onChange={(event) => setGeprueft(event.target.checked)} />
        Geprüft
      </label>
      <div className="actions">
        <button type="button" onClick={() => void zuordnen()}>Zuordnen</button>
        {belegIds.length > 0 && (
          <button type="button" className="secondary" onClick={() => { setBelegIds([]); void zuordnen([]); }}>
            Zuordnung lösen
          </button>
        )}
        <button type="button" onClick={() => void speichern(false)}>Speichern und schließen</button>
        <button type="button" onClick={() => void speichern(true)}>Speichern und weiter</button>
        <button type="button" className="danger" onClick={() => void umsaetzeLoeschen()}>Zeile löschen</button>
      </div>
    </div>
  );

  return (
    <div className="seite" onDragOver={(event) => event.preventDefault()} onDrop={fallen}>
      {ablage.length > 0 && (
        <AblegenModal
          warteschlange={ablage}
          gesamt={ablageGesamt}
          onDropDateien={dateienDazu}
          onFehler={onFehler}
          onWeiter={async ({ beleg_id, art, rest }) => {
            setAblage((bisher) => bisher.slice(1));
            if (detail && zeile && art === "beleg") {
              const neueIds = belegIds.includes(beleg_id) ? belegIds : [...belegIds, beleg_id];
              await zuordnen(neueIds);
              setAnzeige(beleg_id);
            } else {
              await laden(konto);
            }
            if (rest <= 0) setAblageGesamt(0);
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
      <Teilung
        start={detail ? 44 : 58}
        links={detail ? (umsatz || <div className="vorschau-mitte" role="status"><span className="kreis" aria-label="Laden" /></div>) : listePane}
        rechts={stapelIds.length > 1 ? (
          <div className="beleg-stapel">
            {stapelIds.map((id, index) => (
              <section key={id} className="beleg-stapel-teil">
                <h3>Beleg {index + 1} von {stapelIds.length}: {nameFuer(id)}</h3>
                <BelegAnsicht belegId={id} name={nameFuer(id)} />
              </section>
            ))}
          </div>
        ) : vorschauId ? <BelegAnsicht belegId={vorschauId} name={vorschauName} /> : <p className="hinweis vorschau-mitte">Kein Beleg ausgewählt. Beleg in der Liste anklicken oder per Drag & Drop hineinziehen.</p>}
      />
    </div>
  );
}
