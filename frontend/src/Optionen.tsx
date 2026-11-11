import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiFehler, api } from "./api";
import { BenutzerSeite, type Benutzer } from "./Benutzer";
import type { Kategorie } from "./konten";

type Smtp = {
  host: string;
  port: number;
  benutzer: string;
  absender: string;
  tls: boolean;
  passwort_gesetzt: boolean;
};

type VersandOptionen = { stb_email: string; ausgang_email: string };
type Stammdaten = {
  name: string;
  strasse_brief: string;
  strasse_xml: string;
  plz: string;
  ort: string;
  land: string;
  telefon: string;
  email: string;
  steuernummer: string;
  ust_id: string;
  bank_name: string;
  bank_iban: string;
  bank_bic: string;
  fusszeile: string;
  zahlungstext: string;
  zahlungsziel_tage: number;
  einleitungstext: string;
  auftrag_referenz: string;
  layout_vorlage: string;
};
type EditierbareKategorie = Kategorie & { original_schluessel: string };
type Azure = { endpoint: string; deployment: string; schluessel_gesetzt: boolean };
type Postfach = {
  host: string;
  port: number;
  benutzer: string;
  ordner: string;
  erledigt: string;
  quelle: string;
  tls: boolean;
  passwort_gesetzt: boolean;
};
type PostfachProtokoll = {
  import_id: number;
  betreff: string;
  absender: string;
  dateien: number;
  beleg_ids: number[];
  zeitpunkt: string | null;
};
type Kriterium = { kriterium_id: number; schluessel: string; art: string; muster: string };
type Partner = {
  partner_id: number;
  name: string;
  ust_id: string;
  steuernummer: string;
  iban: string;
  datum_muster: string;
  nummer_muster: string;
  betrag_muster: string;
};

type Reiter = "stammdaten" | "allgemein" | "verbindung" | "abrechnungen" | "partner" | "update" | "benutzer";

type UpdateInstalliert = {
  version: string;
  commit: string | null;
  commit_kurz: string | null;
  commit_datum: string | null;
  nachricht: string;
};

type UpdateRemote = {
  commit: string;
  commit_kurz: string;
  datum: string | null;
  nachricht: string;
  url: string;
};

type UpdateLauf = {
  zustand: "idle" | "running" | "done" | "failed";
  gestartet_von?: string | null;
  gestartet_am?: string | null;
  beendet_am?: string | null;
  von_commit?: string | null;
  nach_commit?: string | null;
  fehler?: string | null;
  protokoll?: string[];
};

type UpdateStand = {
  unterstuetzt: boolean;
  grund: string | null;
  installiert: UpdateInstalliert;
  quelle: { repo: string; branch: string; url: string };
  remote: UpdateRemote | null;
  vergleich: "unbekannt" | "aktuell" | "dahinter" | "voraus" | "abgewichen";
  dahinter: number | null;
  letzte_pruefung: string | null;
  update: UpdateLauf;
};

const KRITERIUM_ARTEN = [
  { wert: "dateiname", label: "Dateiname" },
  { wert: "iban", label: "IBAN" },
  { wert: "absender", label: "Absender / Text" },
  { wert: "kartentext", label: "Kartennummer" },
];

function datumZeit(wert: string | null | undefined) {
  if (!wert) return "—";
  const d = new Date(wert);
  return Number.isNaN(d.getTime()) ? wert : d.toLocaleString("de-DE", { dateStyle: "medium", timeStyle: "short" });
}

function vergleichText(stand: UpdateStand): string {
  if (!stand.remote) return "Noch nicht geprüft.";
  switch (stand.vergleich) {
    case "aktuell":
      return "Auf dem neuesten Stand.";
    case "dahinter":
      return stand.dahinter ? `${stand.dahinter} Commits dahinter.` : "Neuere Version verfügbar.";
    case "voraus":
      return "Installierter Stand ist neuer als GitHub.";
    case "abgewichen":
      return stand.dahinter ? `Abgewichen, ${stand.dahinter} Commits dahinter.` : "Abgewichen.";
    default:
      return "Vergleich unbekannt.";
  }
}

function UpdateKarte() {
  const [stand, setStand] = useState<UpdateStand | null>(null);
  const [meldung, setMeldung] = useState("");
  const [fehler, setFehler] = useState("");
  const [beschaeftigt, setBeschaeftigt] = useState(false);
  const [bereit, setBereit] = useState(false);
  const [phase, setPhase] = useState<"ruhig" | "aktualisiert" | "verbindet">("ruhig");
  const zeitgeber = useRef<number | null>(null);

  function abfrageStoppen() {
    if (zeitgeber.current !== null) {
      window.clearInterval(zeitgeber.current);
      zeitgeber.current = null;
    }
  }

  useEffect(() => {
    api<UpdateStand>("/api/update/status")
      .then(setStand)
      .catch(() => setFehler("Update-Status konnte nicht geladen werden."))
      .finally(() => setBereit(true));
    return () => {
      if (zeitgeber.current !== null) window.clearInterval(zeitgeber.current);
    };
  }, []);

  function verbindungAbfragen() {
    abfrageStoppen();
    let versuche = 0;
    zeitgeber.current = window.setInterval(() => {
      void (async () => {
        versuche += 1;
        try {
          await api<{ ok: boolean }>("/api/health");
          abfrageStoppen();
          try {
            setStand(await api<UpdateStand>("/api/update/status"));
          } catch {
            /* Status folgt beim nächsten Laden */
          }
          setPhase("ruhig");
          setBeschaeftigt(false);
          setMeldung("Dienst ist wieder da.");
        } catch {
          if (versuche > 120) {
            abfrageStoppen();
            setPhase("ruhig");
            setBeschaeftigt(false);
            setFehler("Der Dienst meldet sich nicht zurück. Server prüfen.");
          }
        }
      })();
    }, 3000);
  }

  function statusAbfragen() {
    abfrageStoppen();
    let versuche = 0;
    zeitgeber.current = window.setInterval(() => {
      void (async () => {
        versuche += 1;
        try {
          const neu = await api<UpdateStand>("/api/update/status");
          setStand(neu);
          if (neu.update.zustand !== "running") {
            abfrageStoppen();
            setPhase("ruhig");
            setBeschaeftigt(false);
            if (neu.update.zustand === "done") {
              setMeldung("Update fertig. Seite lädt neu …");
              window.setTimeout(() => window.location.reload(), 2500);
            } else if (neu.update.zustand === "failed") {
              setFehler(neu.update.fehler || "Update fehlgeschlagen.");
            }
          }
        } catch {
          abfrageStoppen();
          setPhase("verbindet");
          verbindungAbfragen();
          return;
        }
        if (versuche > 120) {
          abfrageStoppen();
          setPhase("ruhig");
          setBeschaeftigt(false);
          setFehler("Update dauert ungewöhnlich lange. Status später erneut laden.");
        }
      })();
    }, 3000);
  }

  async function pruefen() {
    setMeldung("");
    setFehler("");
    setBeschaeftigt(true);
    try {
      setStand(await api<UpdateStand>("/api/update/check", { method: "POST" }));
      setMeldung("Stand abgefragt.");
    } catch (exc) {
      setFehler(exc instanceof ApiFehler ? exc.message : "Fehler");
    } finally {
      setBeschaeftigt(false);
    }
  }

  async function installieren() {
    if (!window.confirm("Update jetzt installieren? Der Server holt den neuesten Stand von GitHub, sichert die Datenbank, baut neu und startet den Dienst. Die Oberfläche ist kurz nicht erreichbar.")) return;
    setMeldung("");
    setFehler("");
    setBeschaeftigt(true);
    try {
      const neu = await api<UpdateStand>("/api/update/apply", { method: "POST" });
      setStand(neu);
      setPhase("aktualisiert");
      setMeldung("Update läuft …");
      statusAbfragen();
    } catch (exc) {
      setBeschaeftigt(false);
      setFehler(exc instanceof ApiFehler ? exc.message : "Fehler");
    }
  }

  if (!bereit || !stand) {
    return (
      <div>
        <p className="hinweis">Update-Check und One-Button-Update, Quelle ist GitHub.</p>
        {fehler ? <p className="fehler">{fehler}</p> : <p>Laden …</p>}
      </div>
    );
  }

  const laeuft = stand.update.zustand === "running" || phase !== "ruhig";
  const darfInstallieren =
    stand.unterstuetzt && !beschaeftigt && !laeuft && stand.vergleich !== "aktuell" && stand.remote !== null;
  const protokoll = stand.update.protokoll ?? [];
  const letzterLauf =
    stand.update.zustand === "running"
      ? "läuft …"
      : stand.update.zustand === "done"
        ? `fertig${stand.update.nach_commit ? ` (${stand.update.nach_commit})` : ""}`
        : "fehlgeschlagen";

  return (
    <div>
      <p className="hinweis">
        Quelle ist GitHub ({stand.quelle.repo}, Branch {stand.quelle.branch}). Prüfen fragt den neuesten Stand
        ab, Installieren sichert die Datenbank, holt den Code, baut neu und startet den Dienst.
      </p>
      {fehler && <p className="fehler">{fehler}</p>}
      {meldung && <p className="hinweis">{meldung}</p>}
      <div className="card">
        <h2>Stand</h2>
        <table>
          <tbody>
            <tr>
              <td>Installiert</td>
              <td>
                Version {stand.installiert.version}
                {stand.installiert.commit_kurz ? ` (${stand.installiert.commit_kurz})` : " (unbekannt)"}
              </td>
            </tr>
            {stand.installiert.commit_datum && (
              <tr>
                <td>Installierter Commit</td>
                <td>{datumZeit(stand.installiert.commit_datum)}</td>
              </tr>
            )}
            <tr>
              <td>GitHub</td>
              <td>
                {stand.remote ? (
                  <a href={stand.remote.url} target="_blank" rel="noreferrer">
                    {stand.remote.commit_kurz}
                  </a>
                ) : (
                  "—"
                )}
                {stand.remote?.datum ? ` · ${datumZeit(stand.remote.datum)}` : ""}
              </td>
            </tr>
            {stand.remote?.nachricht && (
              <tr>
                <td>Neueste Änderung</td>
                <td>{stand.remote.nachricht}</td>
              </tr>
            )}
            <tr>
              <td>Vergleich</td>
              <td>{vergleichText(stand)}</td>
            </tr>
            <tr>
              <td>Letzte Prüfung</td>
              <td>{datumZeit(stand.letzte_pruefung)}</td>
            </tr>
            {stand.update.zustand !== "idle" && (
              <tr>
                <td>Letztes Update</td>
                <td>
                  {letzterLauf}
                  {stand.update.beendet_am ? ` · ${datumZeit(stand.update.beendet_am)}` : ""}
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {!stand.unterstuetzt && stand.grund && <p className="hinweis">{stand.grund}</p>}
        {phase === "verbindet" && <p className="hinweis">Dienst startet neu … Verbindung wird wieder aufgebaut.</p>}
        {stand.update.zustand === "failed" && stand.update.fehler && <p className="fehler">{stand.update.fehler}</p>}
        {stand.update.zustand === "failed" && protokoll.length > 0 && (
          <details>
            <summary>Protokoll der letzten Zeilen</summary>
            <pre className="pruefung">{protokoll.join("\n")}</pre>
          </details>
        )}
        <div className="actions" style={{ marginTop: "0.8rem" }}>
          <button type="button" className="secondary" disabled={beschaeftigt || laeuft} onClick={() => void pruefen()}>
            {beschaeftigt && phase === "ruhig" ? "…" : "Jetzt prüfen"}
          </button>
          <button type="button" disabled={!darfInstallieren} onClick={() => void installieren()}>
            Update installieren
          </button>
        </div>
        {stand.unterstuetzt && !stand.remote && !laeuft && <p className="hinweis">Erst prüfen, dann installieren.</p>}
      </div>
    </div>
  );
}

export function EinstellungenSeite({ onFehler, istAdmin, aktuell }: { onFehler: (text: string) => void; istAdmin: boolean; aktuell: Benutzer }) {
  const [reiter, setReiter] = useState<Reiter>("stammdaten");
  const [naechste, setNaechste] = useState("");
  const [gespeichert, setGespeichert] = useState("");
  const [nummerHinweis, setNummerHinweis] = useState("");
  const [smtp, setSmtp] = useState<Smtp | null>(null);
  const [passwort, setPasswort] = useState("");
  const [smtpHinweis, setSmtpHinweis] = useState("");
  const [kategorien, setKategorien] = useState<EditierbareKategorie[]>([]);
  const [kategorienHinweis, setKategorienHinweis] = useState("");
  const [versand, setVersand] = useState<VersandOptionen>({ stb_email: "", ausgang_email: "" });
  const [versandHinweis, setVersandHinweis] = useState("");
  const [stammdaten, setStammdaten] = useState<Stammdaten | null>(null);
  const [stammdatenHinweis, setStammdatenHinweis] = useState("");
  const [neuName, setNeuName] = useState("");
  const [neuSchluessel, setNeuSchluessel] = useState("");
  const [neuEmail, setNeuEmail] = useState("");
  const [neuWv, setNeuWv] = useState(false);
  const [neuIban, setNeuIban] = useState("");
  const [neuBic, setNeuBic] = useState("");
  const [azure, setAzure] = useState<Azure | null>(null);
  const [schluessel, setSchluessel] = useState("");
  const [azureHinweis, setAzureHinweis] = useState("");
  const [postfach, setPostfach] = useState<Postfach | null>(null);
  const [postfachPasswort, setPostfachPasswort] = useState("");
  const [postfachHinweis, setPostfachHinweis] = useState("");
  const [postfachProtokoll, setPostfachProtokoll] = useState<PostfachProtokoll[]>([]);
  const [postfachLaeuft, setPostfachLaeuft] = useState(false);
  const [kriterien, setKriterien] = useState<Kriterium[]>([]);
  const [kriterienGeladen, setKriterienGeladen] = useState(false);
  const [kriterienHinweis, setKriterienHinweis] = useState("");
  const [partner, setPartner] = useState<Partner[]>([]);
  const [partnerGeladen, setPartnerGeladen] = useState(false);
  const [partnerSuche, setPartnerSuche] = useState("");
  const [partnerWahl, setPartnerWahl] = useState<number>(0);
  const [partnerHinweis, setPartnerHinweis] = useState("");

  useEffect(() => {
    api<{ naechste: string }>("/api/optionen/rechnungsnummer")
      .then((daten) => {
        setNaechste(daten.naechste);
        setGespeichert(daten.naechste);
        onFehler("");
      })
      .catch((exc) => onFehler(exc instanceof ApiFehler ? exc.message : "Nummer nicht geladen."));
    api<Smtp>("/api/einstellungen/smtp")
      .then((daten) => setSmtp(daten))
      .catch((exc) => onFehler(exc instanceof ApiFehler ? exc.message : "SMTP nicht geladen."));
    api<Kategorie[]>("/api/kategorien")
      .then((liste) => setKategorien(liste.map((k) => ({ ...k, original_schluessel: k.schluessel }))))
      .catch((exc) => onFehler(exc instanceof ApiFehler ? exc.message : "Kategorien nicht geladen."));
    api<VersandOptionen>("/api/optionen/versand")
      .then(setVersand)
      .catch(() => undefined);
    api<Stammdaten>("/api/optionen/stammdaten")
      .then(setStammdaten)
      .catch((exc) => onFehler(exc instanceof ApiFehler ? exc.message : "Stammdaten nicht geladen."));
    api<Azure>("/api/einstellungen/azure")
      .then(setAzure)
      .catch((exc) => onFehler(exc instanceof ApiFehler ? exc.message : "Azure nicht geladen."));
    api<Postfach>("/api/einstellungen/postfach")
      .then(setPostfach)
      .catch((exc) => onFehler(exc instanceof ApiFehler ? exc.message : "Postfach nicht geladen."));
    api<PostfachProtokoll[]>("/api/mailimport/protokoll")
      .then(setPostfachProtokoll)
      .catch(() => undefined);
  }, []);

  async function nummerSpeichern(event: FormEvent) {
    event.preventDefault();
    try {
      const daten = await api<{ naechste: string }>("/api/optionen/rechnungsnummer", {
        method: "PUT",
        body: JSON.stringify({ naechste }),
      });
      setNaechste(daten.naechste);
      setGespeichert(daten.naechste);
      setNummerHinweis("Rechnungsnummer gespeichert.");
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Nummer nicht gespeichert.");
    }
  }

  async function smtpSpeichern(event: FormEvent) {
    event.preventDefault();
    if (!smtp) return;
    try {
      const daten = await api<Smtp>("/api/einstellungen/smtp", {
        method: "PUT",
        body: JSON.stringify({
          host: smtp.host,
          port: Number(smtp.port),
          benutzer: smtp.benutzer,
          absender: smtp.absender,
          tls: smtp.tls,
          passwort,
        }),
      });
      setSmtp(daten);
      setPasswort("");
      setSmtpHinweis(passwort ? "Passwort gespeichert." : "Gespeichert. Das Passwort bleibt unverändert.");
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "SMTP nicht gespeichert.");
    }
  }

  async function azureSpeichern(event: FormEvent) {
    event.preventDefault();
    if (!azure) return;
    try {
      const daten = await api<Azure>("/api/einstellungen/azure", {
        method: "PUT",
        body: JSON.stringify({ endpoint: azure.endpoint, deployment: azure.deployment, schluessel }),
      });
      setAzure(daten);
      setSchluessel("");
      setAzureHinweis(schluessel ? "Schlüssel gespeichert." : "Gespeichert. Der Schlüssel bleibt unverändert.");
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Azure nicht gespeichert.");
    }
  }

  async function azureTest() {
    try {
      const daten = await api<{ status: number }>("/api/einstellungen/azure/test", { method: "POST" });
      setAzureHinweis("Verbindung steht. Status " + daten.status);
      onFehler("");
    } catch (exc) {
      const text = exc instanceof ApiFehler ? exc.message : "Verbindung fehlgeschlagen.";
      setAzureHinweis(text);
      onFehler(text);
    }
  }

  async function postfachSpeichern(event: FormEvent) {
    event.preventDefault();
    if (!postfach) return;
    try {
      const daten = await api<Postfach>("/api/einstellungen/postfach", {
        method: "PUT",
        body: JSON.stringify({
          host: postfach.host,
          port: Number(postfach.port),
          benutzer: postfach.benutzer,
          ordner: postfach.ordner,
          erledigt: postfach.erledigt,
          quelle: postfach.quelle,
          tls: postfach.tls,
          passwort: postfachPasswort,
        }),
      });
      setPostfach(daten);
      setPostfachPasswort("");
      setPostfachHinweis(postfachPasswort ? "Postfach und Passwort gespeichert." : "Gespeichert. Das Passwort bleibt unverändert.");
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Postfach nicht gespeichert.");
    }
  }

  async function postfachTest() {
    try {
      const daten = await api<{ ordner: string; gesamt: number; ungesehen: number }>("/api/einstellungen/postfach/test", { method: "POST" });
      setPostfachHinweis(`Verbindung steht. Ordner ${daten.ordner}: ${daten.ungesehen} von ${daten.gesamt} ungesehen.`);
      onFehler("");
    } catch (exc) {
      const text = exc instanceof ApiFehler ? exc.message : "Verbindung fehlgeschlagen.";
      setPostfachHinweis(text);
      onFehler(text);
    }
  }

  async function postfachAbrufen() {
    setPostfachLaeuft(true);
    try {
      const daten = await api<{ mails: number; dateien: number; neu: number; uebersprungen: number; fehler: string[] }>(
        "/api/mailimport/abrufen",
        { method: "POST" },
      );
      const teile = [`${daten.mails} Mails gelesen, ${daten.neu} neue Belege.`];
      if (daten.uebersprungen) teile.push(`${daten.uebersprungen} bereits verarbeitet.`);
      if (daten.fehler.length) teile.push("Fehler: " + daten.fehler.join(" "));
      setPostfachHinweis(teile.join(" "));
      setPostfachProtokoll(await api<PostfachProtokoll[]>("/api/mailimport/protokoll"));
      onFehler("");
    } catch (exc) {
      const text = exc instanceof ApiFehler ? exc.message : "Abruf fehlgeschlagen.";
      setPostfachHinweis(text);
      onFehler(text);
    } finally {
      setPostfachLaeuft(false);
    }
  }

  async function abrechnungenLaden() {
    setReiter("abrechnungen");
    if (kriterienGeladen) return;
    try {
      setKriterien(await api<Kriterium[]>("/api/abrechnungen"));
      setKriterienGeladen(true);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Abrechnungen nicht geladen.");
    }
  }

  async function partnerLaden() {
    setReiter("partner");
    if (partnerGeladen) return;
    try {
      const geladen = await api<Partner[]>("/api/geschaeftspartner");
      setPartner(geladen);
      setPartnerGeladen(true);
      setPartnerWahl(0);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Geschäftspartner nicht geladen.");
    }
  }

  async function kriterienSpeichern(event: FormEvent) {
    event.preventDefault();
    try {
      setKriterien(await api<Kriterium[]>("/api/abrechnungen", { method: "PUT", body: JSON.stringify(kriterien) }));
      setKriterienHinweis("Abrechnungskriterien gespeichert.");
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Abrechnungen nicht gespeichert.");
    }
  }

  async function partnerSpeichern(event: FormEvent) {
    event.preventDefault();
    try {
      const gespeichert = await api<Partner[]>("/api/geschaeftspartner", {
        method: "PUT",
        body: JSON.stringify(partner.map((eintrag) => ({ ...eintrag, partner_id: eintrag.partner_id || null }))),
      });
      setPartner(gespeichert);
      setPartnerHinweis("Geschäftspartner gespeichert.");
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Geschäftspartner nicht gespeichert.");
    }
  }

  async function versandSpeichern(event: FormEvent) {
    event.preventDefault();
    try {
      const gespeichert = await api<VersandOptionen>("/api/optionen/versand", {
        method: "PUT",
        body: JSON.stringify(versand),
      });
      setVersand(gespeichert);
      setVersandHinweis("E-Mail-Adressen für Versand gespeichert.");
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Versand-E-Mails nicht gespeichert.");
    }
  }

  async function stammdatenSpeichern(event: FormEvent) {
    event.preventDefault();
    if (!stammdaten) return;
    try {
      const gespeichert = await api<Stammdaten>("/api/optionen/stammdaten", {
        method: "PUT",
        body: JSON.stringify(stammdaten),
      });
      setStammdaten(gespeichert);
      setStammdatenHinweis("Stammdaten und Rechnungslayout gespeichert.");
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Stammdaten nicht gespeichert.");
    }
  }

  async function kategorienSpeichern(event: FormEvent) {
    event.preventDefault();
    try {
      const gespeichert: EditierbareKategorie[] = [];
      for (const kategorie of kategorien) {
        const antwort = await api<Kategorie>("/api/kategorien/" + encodeURIComponent(kategorie.original_schluessel), {
          method: "PUT",
          body: JSON.stringify({
            name: kategorie.name,
            datev_email: kategorie.datev_email,
            weiterverarbeitung: Boolean(kategorie.weiterverarbeitung),
            iban: kategorie.iban || "",
            bic: kategorie.bic || "",
            neuer_schluessel: kategorie.schluessel !== kategorie.original_schluessel ? kategorie.schluessel : "",
          }),
        });
        gespeichert.push({ ...antwort, original_schluessel: antwort.schluessel });
      }
      setKategorien(gespeichert);
      setKategorienHinweis("Konten gespeichert.");
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Kategorien nicht gespeichert.");
    }
  }

  async function kategorieAnlegen(event: FormEvent) {
    event.preventDefault();
    try {
      const angelegt = await api<Kategorie>("/api/kategorien", {
        method: "POST",
        body: JSON.stringify({
          name: neuName,
          schluessel: neuSchluessel,
          datev_email: neuEmail,
          weiterverarbeitung: neuWv,
          iban: neuIban,
          bic: neuBic,
        }),
      });
      setKategorien((bisher) => [...bisher, { ...angelegt, original_schluessel: angelegt.schluessel }]);
      setNeuName("");
      setNeuSchluessel("");
      setNeuEmail("");
      setNeuWv(false);
      setNeuIban("");
      setNeuBic("");
      setKategorienHinweis(`Konto ${angelegt.name} angelegt.`);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Konto nicht angelegt.");
    }
  }

  async function kategorieLoeschen(kategorie: EditierbareKategorie) {
    if (!window.confirm(`Konto „${kategorie.name}“ löschen?`)) return;
    try {
      await api("/api/kategorien/" + encodeURIComponent(kategorie.original_schluessel), { method: "DELETE" });
      setKategorien((bisher) => bisher.filter((eintrag) => eintrag.original_schluessel !== kategorie.original_schluessel));
      setKategorienHinweis(`Konto ${kategorie.name} gelöscht.`);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Konto nicht gelöscht.");
    }
  }

  function partnerAktualisieren<K extends keyof Partner>(index: number, feld: K, wert: Partner[K]) {
    setPartner((bisher) => bisher.map((zeile, item) => (item === index ? { ...zeile, [feld]: wert } : zeile)));
  }

  const gefiltertePartner = partner
    .map((eintrag, index) => ({ eintrag, index }))
    .filter(({ eintrag }) => {
      const q = partnerSuche.trim().toLowerCase();
      if (!q) return true;
      return `${eintrag.name} ${eintrag.ust_id} ${eintrag.iban} ${eintrag.steuernummer}`.toLowerCase().includes(q);
    });

  const aktiverPartner = partner[partnerWahl] || null;

  return (
    <div className="optionen-seite">
      <header className="optionen-kopf">
        <h1>Einstellungen</h1>
      </header>
      <div className="reiter" role="tablist" aria-label="Einstellungen">
        <button type="button" role="tab" aria-selected={reiter === "stammdaten"} className={reiter === "stammdaten" ? "reiter-knopf aktiv" : "reiter-knopf"} onClick={() => setReiter("stammdaten")}>
          Stammdaten
        </button>
        <button type="button" role="tab" aria-selected={reiter === "allgemein"} className={reiter === "allgemein" ? "reiter-knopf aktiv" : "reiter-knopf"} onClick={() => setReiter("allgemein")}>
          Rechnungen & Konten
        </button>
        <button type="button" role="tab" aria-selected={reiter === "verbindung"} className={reiter === "verbindung" ? "reiter-knopf aktiv" : "reiter-knopf"} onClick={() => setReiter("verbindung")}>
          E-Mail & KI
        </button>
        <button type="button" role="tab" aria-selected={reiter === "abrechnungen"} className={reiter === "abrechnungen" ? "reiter-knopf aktiv" : "reiter-knopf"} onClick={() => void abrechnungenLaden()}>
          Erkennung
        </button>
        <button type="button" role="tab" aria-selected={reiter === "partner"} className={reiter === "partner" ? "reiter-knopf aktiv" : "reiter-knopf"} onClick={() => void partnerLaden()}>
          Partner
        </button>
        {istAdmin && (
          <button type="button" role="tab" aria-selected={reiter === "update"} className={reiter === "update" ? "reiter-knopf aktiv" : "reiter-knopf"} onClick={() => setReiter("update")}>
            Update
          </button>
        )}
        {istAdmin && (
          <button type="button" role="tab" aria-selected={reiter === "benutzer"} className={reiter === "benutzer" ? "reiter-knopf aktiv" : "reiter-knopf"} onClick={() => setReiter("benutzer")}>
            Benutzer
          </button>
        )}
      </div>

      {reiter === "stammdaten" && stammdaten && (
        <form className="card" onSubmit={(event) => void stammdatenSpeichern(event)}>
          <h2>Unternehmens-Stammdaten & Rechnungslayout</h2>
          <p className="hinweis">
            Diese Angaben werden für die Erstellung von Ausgangsrechnungen (PDF, E-Rechnung/ZUGFeRD, EPC-Zahlcode, Mahnungen) sowie für das Ausfiltern eigener Kennungen bei der Belegerkennung verwendet.
          </p>
          <div className="optionen-zwei" style={{ marginTop: "0.8rem" }}>
            <div className="form-gruppen">
              <h3>Absender & Kontakt</h3>
              <label>Name / Firma
                <input value={stammdaten.name} onChange={(event) => setStammdaten({ ...stammdaten, name: event.target.value })} required />
              </label>
              <label>Straße & Hausnummer (Brief)
                <input value={stammdaten.strasse_brief} onChange={(event) => setStammdaten({ ...stammdaten, strasse_brief: event.target.value })} />
              </label>
              <label>Straße & Hausnummer (XRechnung-XML)
                <input value={stammdaten.strasse_xml} onChange={(event) => setStammdaten({ ...stammdaten, strasse_xml: event.target.value })} placeholder="wird sonst aus Straße gebildet" />
              </label>
              <div className="row">
                <label style={{ width: "7rem" }}>PLZ
                  <input value={stammdaten.plz} onChange={(event) => setStammdaten({ ...stammdaten, plz: event.target.value })} />
                </label>
                <label style={{ flex: 1 }}>Ort
                  <input value={stammdaten.ort} onChange={(event) => setStammdaten({ ...stammdaten, ort: event.target.value })} />
                </label>
                <label style={{ width: "5rem" }}>Land
                  <input value={stammdaten.land} onChange={(event) => setStammdaten({ ...stammdaten, land: event.target.value })} />
                </label>
              </div>
              <label>Telefon
                <input value={stammdaten.telefon} onChange={(event) => setStammdaten({ ...stammdaten, telefon: event.target.value })} />
              </label>
              <label>E-Mail
                <input value={stammdaten.email} onChange={(event) => setStammdaten({ ...stammdaten, email: event.target.value })} />
              </label>
            </div>

            <div className="form-gruppen">
              <h3>Steuern & Bankverbindung (für Rechnung / ZUGFeRD / QR-Code)</h3>
              <div className="row">
                <label style={{ flex: 1 }}>Steuernummer
                  <input value={stammdaten.steuernummer} onChange={(event) => setStammdaten({ ...stammdaten, steuernummer: event.target.value })} />
                </label>
                <label style={{ flex: 1 }}>USt-IdNr.
                  <input value={stammdaten.ust_id} onChange={(event) => setStammdaten({ ...stammdaten, ust_id: event.target.value })} />
                </label>
              </div>
              <label>Bankname (auf Rechnung)
                <input value={stammdaten.bank_name} onChange={(event) => setStammdaten({ ...stammdaten, bank_name: event.target.value })} />
              </label>
              <div className="row">
                <label style={{ flex: 2 }}>IBAN
                  <input value={stammdaten.bank_iban} onChange={(event) => setStammdaten({ ...stammdaten, bank_iban: event.target.value })} />
                </label>
                <label style={{ flex: 1 }}>BIC
                  <input value={stammdaten.bank_bic} onChange={(event) => setStammdaten({ ...stammdaten, bank_bic: event.target.value })} />
                </label>
              </div>
              <h3>Rechnungstexte & Layout</h3>
              <label>Fußzeile / Tätigkeitszeile
                <input value={stammdaten.fusszeile} onChange={(event) => setStammdaten({ ...stammdaten, fusszeile: event.target.value })} />
              </label>
              <label>Einleitungstext
                <input value={stammdaten.einleitungstext} onChange={(event) => setStammdaten({ ...stammdaten, einleitungstext: event.target.value })} />
              </label>
              <div className="row">
                <label style={{ flex: 2 }}>Zahlungshinweis
                  <input value={stammdaten.zahlungstext} onChange={(event) => setStammdaten({ ...stammdaten, zahlungstext: event.target.value })} />
                </label>
                <label style={{ width: "8rem" }}>Fälligkeit (Tage)
                  <input
                    type="number"
                    min={0}
                    max={365}
                    value={stammdaten.zahlungsziel_tage}
                    onChange={(event) => setStammdaten({ ...stammdaten, zahlungsziel_tage: Number(event.target.value) || 0 })}
                  />
                </label>
              </div>
              <div className="row">
                <label style={{ flex: 1 }}>Auftragsreferenz (XRechnung)
                  <input value={stammdaten.auftrag_referenz} onChange={(event) => setStammdaten({ ...stammdaten, auftrag_referenz: event.target.value })} />
                </label>
                <label style={{ flex: 1 }}>Layout-Vorlage
                  <select value={stammdaten.layout_vorlage} onChange={(event) => setStammdaten({ ...stammdaten, layout_vorlage: event.target.value })}>
                    <option value="standard">Standard (Schwarz-Weiß, ohne Briefpapier)</option>
                  </select>
                </label>
              </div>
            </div>
          </div>
          <div className="actions" style={{ marginTop: "0.9rem" }}>
            <button type="submit">Stammdaten speichern</button>
          </div>
          {stammdatenHinweis && <p className="hinweis">{stammdatenHinweis}</p>}
        </form>
      )}

      {reiter === "allgemein" && (
        <div className="optionen-stapel">
          <div className="optionen-zwei">
            <form className="card" onSubmit={(event) => void nummerSpeichern(event)}>
              <h2>Nächste Rechnungsnummer</h2>
              <p>Aktuell vergeben wird als Nächstes: <strong>{gespeichert || "…"}</strong></p>
              <p className="hinweis">Format yy.nnnn. Die Jahreszahl wird beim Vergeben aus dem Rechnungsdatum gebildet.</p>
              <div className="row">
                <label style={{ flex: 1 }}>Nächste Nummer
                  <input value={naechste} onChange={(event) => setNaechste(event.target.value)} inputMode="decimal" />
                </label>
                <button type="submit">Speichern</button>
              </div>
              {nummerHinweis && <p className="hinweis">{nummerHinweis}</p>}
            </form>

            <form className="card" onSubmit={(event) => void versandSpeichern(event)}>
              <h2>Zentrale E-Mail-Adressen (Steuerberater & Ausgangsrechnungen)</h2>
              <p className="hinweis">
                An die <strong>Steuerberater-E-Mail</strong> werden die Bankumsätze als DATEV-Weiterverarbeitungsdatei (Dok.-Nr. 9226961) geschickt, sofern beim Konto der Haken gesetzt ist.
                An die <strong>Ausgangsrechnungen-E-Mail</strong> gehen die erstellten Ausgangsrechnungen (je Rechnung eine E-Mail ohne Briefpapier).
              </p>
              <div className="form-gruppen">
                <label>E-Mail Steuerberater (für Weiterverarbeitungsdateien)
                  <input
                    value={versand.stb_email}
                    placeholder="z.B. steuerberater@example.org"
                    onChange={(event) => setVersand({ ...versand, stb_email: event.target.value })}
                  />
                </label>
                <label>DATEV-Upload-E-Mail für Ausgangsrechnungen
                  <input
                    value={versand.ausgang_email}
                    placeholder="...@uploadmail.datev.de"
                    onChange={(event) => setVersand({ ...versand, ausgang_email: event.target.value })}
                  />
                </label>
              </div>
              <div className="actions">
                <button type="submit">Versand-Adressen speichern</button>
              </div>
              {versandHinweis && <p className="hinweis">{versandHinweis}</p>}
            </form>
          </div>

          <form className="card" onSubmit={(event) => void kategorienSpeichern(event)}>
            <h2>Konten / Kategorien verwalten</h2>
            <p className="hinweis">
              Beliebig viele Konten mit frei wählbarem Namen und Schlüssel. Pro Konto kann eine DATEV-Upload-E-Mail für Abrechnungen & Belege (je Beleg 1 E-Mail) hinterlegt werden sowie per Haken festgelegt werden, ob für dieses Konto eine Weiterverarbeitungsdatei (Dok.-Nr. 9226961) an den Steuerberater geschickt wird.
            </p>
            <div className="tabelle-scroll">
              <table className="optionen-tabelle optionen-konten-tabelle">
                <thead>
                  <tr>
                    <th style={{ width: "8.5rem" }}>Schlüssel</th>
                    <th style={{ width: "11rem" }}>Anzeigename</th>
                    <th style={{ minWidth: "22rem" }}>DATEV-Upload-E-Mail (Belege & Abrechnung)</th>
                    <th style={{ width: "13rem" }}>IBAN (für Dok. 9226961)</th>
                    <th style={{ width: "8.5rem" }}>BIC</th>
                    <th style={{ width: "9rem", textAlign: "center" }}>Weiterverarb. an StB</th>
                    <th style={{ width: "5.5rem" }} />
                  </tr>
                </thead>
                <tbody>
                  {kategorien.map((kategorie, index) => (
                    <tr key={kategorie.original_schluessel}>
                      <td>
                        <input
                          aria-label={`Schlüssel ${kategorie.original_schluessel}`}
                          value={kategorie.schluessel}
                          onChange={(event) => setKategorien(kategorien.map((eintrag, item) => item === index ? { ...eintrag, schluessel: event.target.value } : eintrag))}
                        />
                      </td>
                      <td>
                        <input
                          aria-label={`Name ${kategorie.original_schluessel}`}
                          value={kategorie.name}
                          onChange={(event) => setKategorien(kategorien.map((eintrag, item) => item === index ? { ...eintrag, name: event.target.value } : eintrag))}
                        />
                      </td>
                      <td>
                        <input
                          aria-label={`DATEV-Adresse ${kategorie.original_schluessel}`}
                          value={kategorie.datev_email}
                          placeholder="keine direkte DATEV-Upload-Adresse"
                          onChange={(event) => setKategorien(kategorien.map((eintrag, item) => item === index ? { ...eintrag, datev_email: event.target.value } : eintrag))}
                        />
                      </td>
                      <td>
                        <input
                          aria-label={`IBAN ${kategorie.original_schluessel}`}
                          value={kategorie.iban || ""}
                          placeholder="DE..."
                          onChange={(event) => setKategorien(kategorien.map((eintrag, item) => item === index ? { ...eintrag, iban: event.target.value } : eintrag))}
                        />
                      </td>
                      <td>
                        <input
                          aria-label={`BIC ${kategorie.original_schluessel}`}
                          value={kategorie.bic || ""}
                          placeholder="BIC..."
                          onChange={(event) => setKategorien(kategorien.map((eintrag, item) => item === index ? { ...eintrag, bic: event.target.value } : eintrag))}
                        />
                      </td>
                      <td style={{ textAlign: "center" }}>
                        <input
                          type="checkbox"
                          aria-label={`Weiterverarbeitung ${kategorie.original_schluessel}`}
                          checked={Boolean(kategorie.weiterverarbeitung)}
                          onChange={(event) => setKategorien(kategorien.map((eintrag, item) => item === index ? { ...eintrag, weiterverarbeitung: event.target.checked } : eintrag))}
                        />
                      </td>
                      <td>
                        <button type="button" className="danger" onClick={() => void kategorieLoeschen(kategorie)}>Löschen</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="actions" style={{ marginTop: "0.75rem" }}>
              <button type="submit">Konten speichern</button>
            </div>
            {kategorienHinweis && <p className="hinweis">{kategorienHinweis}</p>}
          </form>

          <form className="card" onSubmit={(event) => void kategorieAnlegen(event)}>
            <h2>Neues Konto anlegen</h2>
            <div className="optionen-neues-konto">
              <label>Anzeigename<input value={neuName} onChange={(event) => setNeuName(event.target.value)} placeholder="z.B. PayPal oder Sparkasse" required /></label>
              <label>Schlüssel (optional)<input value={neuSchluessel} onChange={(event) => setNeuSchluessel(event.target.value)} placeholder="wird sonst aus Namen gebildet" /></label>
              <label>DATEV-Upload-E-Mail<input value={neuEmail} onChange={(event) => setNeuEmail(event.target.value)} placeholder="...@uploadmail.datev.de (optional)" /></label>
              <label>IBAN (optional)<input value={neuIban} onChange={(event) => setNeuIban(event.target.value)} placeholder="DE..." /></label>
              <label>BIC (optional)<input value={neuBic} onChange={(event) => setNeuBic(event.target.value)} placeholder="BIC..." /></label>
              <label className="check" style={{ alignSelf: "end", paddingBottom: "0.45rem" }}>
                <input type="checkbox" checked={neuWv} onChange={(event) => setNeuWv(event.target.checked)} />
                Weiterverarbeitungsdatei (9226961) an StB senden
              </label>
            </div>
            <div className="actions" style={{ marginTop: "0.6rem" }}>
              <button type="submit">Konto anlegen</button>
            </div>
          </form>
        </div>
      )}

      {reiter === "verbindung" && (
        <div className="optionen-grid">
          {smtp && (
            <form className="card" onSubmit={(event) => void smtpSpeichern(event)}>
              <h2>SMTP (E-Mail-Versand)</h2>
              <div className="form-gruppen">
                <label>Host<input value={smtp.host} onChange={(event) => setSmtp({ ...smtp, host: event.target.value })} /></label>
                <label>Port<input value={smtp.port} inputMode="numeric" onChange={(event) => setSmtp({ ...smtp, port: Number(event.target.value) || 0 })} /></label>
                <label>Benutzer<input value={smtp.benutzer} onChange={(event) => setSmtp({ ...smtp, benutzer: event.target.value })} autoComplete="off" /></label>
                <label>Passwort
                  <input
                    type="password"
                    name="smtp-passwort"
                    autoComplete="new-password"
                    value={passwort}
                    placeholder={smtp.passwort_gesetzt ? "gesetzt, nur zum Ändern ausfüllen" : ""}
                    onChange={(event) => setPasswort(event.target.value)}
                  />
                </label>
                <label>Absender<input value={smtp.absender} onChange={(event) => setSmtp({ ...smtp, absender: event.target.value })} /></label>
              </div>
              <div className="actions" style={{ marginTop: "0.8rem" }}>
                <label className="check" style={{ marginRight: "1rem" }}>
                  <input type="checkbox" checked={smtp.tls} onChange={(event) => setSmtp({ ...smtp, tls: event.target.checked })} />
                  TLS verschlüsseln
                </label>
                <button type="submit">SMTP speichern</button>
              </div>
              {smtpHinweis && <p className="hinweis">{smtpHinweis}</p>}
            </form>
          )}

          {postfach && (
            <form className="card" onSubmit={(event) => void postfachSpeichern(event)}>
              <h2>Beleg-Postfach (IMAP)</h2>
              <p className="hinweis">
                Eigenes Postfach nur für Belege. Der Abruf holt ungesehene Mails, importiert PDF- und Bild-Anhänge
                und markiert die Mails als gelesen. Auf dem Server läuft der Abruf automatisch alle 15 Minuten.
              </p>
              <div className="form-gruppen">
                <label>Host<input value={postfach.host} placeholder="imap.beispiel.de" onChange={(event) => setPostfach({ ...postfach, host: event.target.value })} autoComplete="off" /></label>
                <label>Port<input value={postfach.port} inputMode="numeric" onChange={(event) => setPostfach({ ...postfach, port: Number(event.target.value) || 0 })} /></label>
                <label>Benutzer<input value={postfach.benutzer} onChange={(event) => setPostfach({ ...postfach, benutzer: event.target.value })} autoComplete="off" /></label>
                <label>Passwort
                  <input
                    type="password"
                    name="imap-passwort"
                    autoComplete="new-password"
                    value={postfachPasswort}
                    placeholder={postfach.passwort_gesetzt ? "gesetzt, nur zum Ändern ausfüllen" : ""}
                    onChange={(event) => setPostfachPasswort(event.target.value)}
                  />
                </label>
                <label>Ordner<input value={postfach.ordner} onChange={(event) => setPostfach({ ...postfach, ordner: event.target.value })} /></label>
                <label>Erledigt-Ordner (optional)<input value={postfach.erledigt} placeholder="leer = nur als gelesen markieren" onChange={(event) => setPostfach({ ...postfach, erledigt: event.target.value })} /></label>
                <label>Quelle für Mail-Belege
                  <select value={postfach.quelle} onChange={(event) => setPostfach({ ...postfach, quelle: event.target.value })}>
                    {!kategorien.some((k) => k.schluessel === postfach.quelle) && !["eingang", "scan", "datei"].includes(postfach.quelle) && (
                      <option value={postfach.quelle}>{postfach.quelle}</option>
                    )}
                    <option value="eingang">Eingang</option>
                    <option value="scan">Scan</option>
                    <option value="datei">Datei</option>
                    {kategorien.map((kat) => (
                      <option key={kat.schluessel} value={kat.schluessel}>{kat.name}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="actions" style={{ marginTop: "0.8rem" }}>
                <label className="check" style={{ marginRight: "1rem" }}>
                  <input type="checkbox" checked={postfach.tls} onChange={(event) => setPostfach({ ...postfach, tls: event.target.checked })} />
                  TLS verschlüsseln
                </label>
                <button type="submit">Postfach speichern</button>
                <button type="button" className="secondary" onClick={() => void postfachTest()}>Verbindung testen</button>
                <button type="button" className="secondary" disabled={postfachLaeuft} onClick={() => void postfachAbrufen()}>
                  {postfachLaeuft ? "Abruf läuft …" : "Jetzt abrufen"}
                </button>
              </div>
              {postfachHinweis && <p className="hinweis">{postfachHinweis}</p>}
              {postfachProtokoll.length > 0 && (
                <div className="tabelle-scroll">
                  <table className="optionen-tabelle dicht">
                    <thead>
                      <tr>
                        <th>Zeitpunkt</th>
                        <th>Absender</th>
                        <th>Betreff</th>
                        <th>Dateien</th>
                        <th>Belege</th>
                      </tr>
                    </thead>
                    <tbody>
                      {postfachProtokoll.slice(0, 10).map((zeile) => (
                        <tr key={zeile.import_id}>
                          <td>{zeile.zeitpunkt ? zeile.zeitpunkt.replace("T", " ") : "—"}</td>
                          <td>{zeile.absender || "—"}</td>
                          <td>{zeile.betreff || "—"}</td>
                          <td>{zeile.dateien}</td>
                          <td>{zeile.beleg_ids.length}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </form>
          )}

          {azure && (
            <form className="card" onSubmit={(event) => void azureSpeichern(event)}>
              <h2>Azure KI (Belegerkennung)</h2>
              <div className="form-gruppen">
                <label>Endpoint<input value={azure.endpoint} onChange={(event) => setAzure({ ...azure, endpoint: event.target.value })} autoComplete="off" /></label>
                <label>Deployment / Modell<input value={azure.deployment} onChange={(event) => setAzure({ ...azure, deployment: event.target.value })} autoComplete="off" /></label>
                <label>Schlüssel
                  <input
                    type="password"
                    name="azure-schluessel"
                    autoComplete="new-password"
                    value={schluessel}
                    placeholder={azure.schluessel_gesetzt ? "gesetzt, nur zum Ändern ausfüllen" : ""}
                    onChange={(event) => setSchluessel(event.target.value)}
                  />
                </label>
              </div>
              <div className="actions" style={{ marginTop: "0.8rem" }}>
                <button type="submit">Azure speichern</button>
                <button type="button" className="secondary" onClick={() => void azureTest()}>Verbindung testen</button>
              </div>
              {azureHinweis && <p className="hinweis">{azureHinweis}</p>}
            </form>
          )}
        </div>
      )}

      {reiter === "abrechnungen" && (
        <form className="card" onSubmit={(event) => void kriterienSpeichern(event)}>
          <div className="liste-werkzeug">
            <div>
              <h2>Abrechnungskriterien</h2>
              <p className="hinweis">Anhand dieser Merkmale erkennt das System automatisch Kontoauszüge und Kreditkartenabrechnungen.</p>
            </div>
            <div className="actions">
              <button
                type="button"
                className="secondary"
                onClick={() => setKriterien([...kriterien, { kriterium_id: 0, schluessel: kategorien[0]?.schluessel || "n26", art: "dateiname", muster: "" }])}
              >
                Kriterium hinzufügen
              </button>
              <button type="submit">Abrechnungen speichern</button>
            </div>
          </div>
          {kriterienHinweis && <p className="hinweis">{kriterienHinweis}</p>}
          <table className="optionen-tabelle">
            <thead>
              <tr>
                <th style={{ width: "11rem" }}>Konto</th>
                <th style={{ width: "13rem" }}>Prüfart</th>
                <th>Suchmuster (Dateiname, IBAN, BIC oder Kartennummer)</th>
                <th style={{ width: "4rem" }} />
              </tr>
            </thead>
            <tbody>
              {kriterien.map((kriterium, index) => (
                <tr key={kriterium.kriterium_id || `neu-${index}`}>
                  <td>
                    <input
                      aria-label="Konto"
                      list="konten-liste"
                      value={kriterium.schluessel}
                      onChange={(event) => setKriterien(kriterien.map((eintrag, item) => item === index ? { ...eintrag, schluessel: event.target.value } : eintrag))}
                    />
                  </td>
                  <td>
                    <select
                      aria-label="Art"
                      value={kriterium.art}
                      onChange={(event) => setKriterien(kriterien.map((eintrag, item) => item === index ? { ...eintrag, art: event.target.value } : eintrag))}
                    >
                      {KRITERIUM_ARTEN.map((art) => (
                        <option key={art.wert} value={art.wert}>{art.label}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      aria-label="Muster"
                      value={kriterium.muster}
                      placeholder="z. B. statement, DE89..., xxxx-12345"
                      onChange={(event) => setKriterien(kriterien.map((eintrag, item) => item === index ? { ...eintrag, muster: event.target.value } : eintrag))}
                    />
                  </td>
                  <td>
                    <button
                      type="button"
                      className="danger"
                      title="Kriterium entfernen"
                      onClick={() => setKriterien(kriterien.filter((_, item) => item !== index))}
                    >
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <datalist id="konten-liste">
            {kategorien.map((k) => <option key={k.schluessel} value={k.schluessel}>{k.name}</option>)}
          </datalist>
        </form>
      )}

      {reiter === "partner" && (
        <form className="card" onSubmit={(event) => void partnerSpeichern(event)}>
          <div className="liste-werkzeug">
            <div>
              <h2>Geschäftspartner & Erkennungsmuster ({partner.length})</h2>
              <p className="hinweis">Wird ein Beleg korrigiert, ergänzt das System USt-Id, IBAN und reguläre Ausdrücke automatisch.</p>
            </div>
            <div className="actions">
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  const neu = [...partner, { partner_id: 0, name: "Neuer Partner", ust_id: "", steuernummer: "", iban: "", datum_muster: "", nummer_muster: "", betrag_muster: "" }];
                  setPartner(neu);
                  setPartnerWahl(neu.length - 1);
                }}
              >
                Partner hinzufügen
              </button>
              <button type="submit">Geschäftspartner speichern</button>
            </div>
          </div>
          {partnerHinweis && <p className="hinweis">{partnerHinweis}</p>}
          <div className="partner-layout">
            <div className="partner-liste">
              <input
                value={partnerSuche}
                placeholder="Partner suchen (Name, USt-Id, IBAN) …"
                onChange={(event) => setPartnerSuche(event.target.value)}
              />
              <div className="partner-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>USt-Id / IBAN</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gefiltertePartner.map(({ eintrag, index }) => (
                      <tr
                        key={eintrag.partner_id || `p-${index}`}
                        className={`click ${index === partnerWahl ? "aktiv" : ""}`}
                        onClick={() => setPartnerWahl(index)}
                      >
                        <td><strong>{eintrag.name || "Unbenannt"}</strong></td>
                        <td className="hinweis">{eintrag.ust_id || eintrag.iban || eintrag.steuernummer || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            {aktiverPartner ? (
              <div className="partner-detail">
                <fieldset className="block">
                  <legend>{aktiverPartner.name || "Partner"}</legend>
                  <div className="form-gruppen">
                    <label>Name
                      <input value={aktiverPartner.name} onChange={(event) => partnerAktualisieren(partnerWahl, "name", event.target.value)} />
                    </label>
                    <label>USt-Id
                      <input value={aktiverPartner.ust_id} onChange={(event) => partnerAktualisieren(partnerWahl, "ust_id", event.target.value)} />
                    </label>
                    <label>Steuernummer
                      <input value={aktiverPartner.steuernummer} onChange={(event) => partnerAktualisieren(partnerWahl, "steuernummer", event.target.value)} />
                    </label>
                    <label>IBAN
                      <input value={aktiverPartner.iban} onChange={(event) => partnerAktualisieren(partnerWahl, "iban", event.target.value)} />
                    </label>
                  </div>
                </fieldset>
                <fieldset className="block" style={{ marginTop: "0.8rem" }}>
                  <legend>Reguläre Ausdrücke für Belegfelder (optional)</legend>
                  <div className="grid" style={{ gridTemplateColumns: "1fr" }}>
                    <label>Datum-Muster (Regex mit einer Capture-Group)
                      <input value={aktiverPartner.datum_muster} onChange={(event) => partnerAktualisieren(partnerWahl, "datum_muster", event.target.value)} />
                    </label>
                    <label>Rechnungsnummer-Muster (Regex mit einer Capture-Group)
                      <input value={aktiverPartner.nummer_muster} onChange={(event) => partnerAktualisieren(partnerWahl, "nummer_muster", event.target.value)} />
                    </label>
                    <label>Betrag-Muster (Regex mit einer Capture-Group)
                      <input value={aktiverPartner.betrag_muster} onChange={(event) => partnerAktualisieren(partnerWahl, "betrag_muster", event.target.value)} />
                    </label>
                  </div>
                </fieldset>
                <div className="actions" style={{ marginTop: "0.8rem" }}>
                  <button
                    type="button"
                    className="danger"
                    onClick={() => {
                      setPartner(partner.filter((_, item) => item !== partnerWahl));
                      setPartnerWahl(0);
                    }}
                  >
                    Partner aus Liste entfernen
                  </button>
                </div>
              </div>
            ) : (
              <p className="hinweis">Links einen Geschäftspartner auswählen.</p>
            )}
          </div>
        </form>
      )}

      {reiter === "update" && istAdmin && <UpdateKarte />}

      {reiter === "benutzer" && istAdmin && <BenutzerSeite aktuell={aktuell} onFehler={onFehler} />}
    </div>
  );
}
