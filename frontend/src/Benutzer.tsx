import { useEffect, useState, type FormEvent } from "react";
import { ApiFehler, api } from "./api";

export type Benutzer = {
  benutzer_id: number;
  benutzername: string;
  name: string;
  email: string;
  rolle: string;
  aktiv: boolean;
  passwort_aendern: boolean;
  auth_quelle: string;
  totp_aktiv: boolean;
  passkey_anzahl?: number;
};

const LEER = { benutzername: "", name: "", email: "", passwort: "", rolle: "benutzer", einladung: false };

export function BenutzerSeite({ aktuell, onFehler }: { aktuell: Benutzer; onFehler: (text: string) => void }) {
  const [liste, setListe] = useState<Benutzer[]>([]);
  const [neu, setNeu] = useState(LEER);
  const [wahl, setWahl] = useState<number | null>(null);
  const [form, setForm] = useState({ name: "", email: "", rolle: "benutzer", aktiv: true, passwort: "" });
  const [hinweis, setHinweis] = useState("");

  async function laden() {
    try {
      setListe(await api<Benutzer[]>("/api/benutzer"));
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Benutzer nicht geladen.");
    }
  }

  useEffect(() => {
    void laden();
  }, []);

  function auswaehlen(benutzer: Benutzer) {
    setWahl(benutzer.benutzer_id);
    setForm({ name: benutzer.name, email: benutzer.email, rolle: benutzer.rolle, aktiv: benutzer.aktiv, passwort: "" });
    setHinweis("");
  }

  async function anlegen(event: FormEvent) {
    event.preventDefault();
    try {
      const angelegt = await api<Benutzer & { mail_gesendet: boolean | null; mail_fehler: string | null }>(
        "/api/benutzer",
        { method: "POST", body: JSON.stringify(neu) },
      );
      setListe((bisher) => [...bisher, angelegt]);
      setNeu(LEER);
      if (neu.einladung) {
        setHinweis(
          angelegt.mail_gesendet
            ? `Benutzer ${angelegt.benutzername} angelegt. Einladung ist unterwegs.`
            : `Benutzer ${angelegt.benutzername} angelegt, aber Einladung fehlgeschlagen: ${angelegt.mail_fehler || "unbekannt"}`,
        );
      } else {
        setHinweis(`Benutzer ${angelegt.benutzername} angelegt. Beim ersten Login muss ein eigenes Passwort vergeben werden.`);
      }
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Benutzer nicht angelegt.");
    }
  }

  async function einladungSenden(benutzer: Benutzer) {
    try {
      await api(`/api/benutzer/${benutzer.benutzer_id}/zugangsmail`, { method: "POST" });
      setHinweis(`Einladung an ${benutzer.benutzername} gesendet.`);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Einladung nicht gesendet.");
    }
  }

  async function speichern(event: FormEvent) {
    event.preventDefault();
    if (wahl === null) return;
    try {
      const gespeichert = await api<Benutzer>("/api/benutzer/" + wahl, {
        method: "PATCH",
        body: JSON.stringify({ ...form, passwort: form.passwort || null }),
      });
      setListe((bisher) => bisher.map((eintrag) => (eintrag.benutzer_id === wahl ? gespeichert : eintrag)));
      setForm({ ...form, passwort: "" });
      setHinweis("Benutzer gespeichert.");
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Benutzer nicht gespeichert.");
    }
  }

  async function loeschen(benutzer: Benutzer) {
    if (!window.confirm(`Benutzer „${benutzer.benutzername}“ endgültig löschen?`)) return;
    try {
      await api("/api/benutzer/" + benutzer.benutzer_id, { method: "DELETE" });
      setListe((bisher) => bisher.filter((eintrag) => eintrag.benutzer_id !== benutzer.benutzer_id));
      if (wahl === benutzer.benutzer_id) setWahl(null);
      setHinweis(`Benutzer ${benutzer.benutzername} gelöscht.`);
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Benutzer nicht gelöscht.");
    }
  }

  const gewaehlt = liste.find((eintrag) => eintrag.benutzer_id === wahl) || null;

  return (
    <div className="optionen-stapel">
      {hinweis && <p className="erfolg-hinweis" role="status">{hinweis}</p>}
      <div className="benutzer-layout">
        <div className="card" style={{ marginBottom: 0 }}>
          <div className="karten-kopf">
            <div>
              <h2>Benutzerkonten ({liste.length})</h2>
              <p className="hinweis">Zeile auswählen, um Daten, Rolle oder Passwort zu bearbeiten.</p>
            </div>
            {gewaehlt && (
              <button type="button" className="secondary kompakt-knopf" onClick={() => setWahl(null)}>
                + Neuer Benutzer
              </button>
            )}
          </div>
          <div className="tabelle-rahmen tabelle-scroll">
            <table className="daten-tabelle">
              <thead>
                <tr>
                  <th>Benutzername</th>
                  <th>Name & E-Mail</th>
                  <th>Rolle</th>
                  <th>Sicherheit & Status</th>
                  <th className="zelle-rechts">Aktionen</th>
                </tr>
              </thead>
              <tbody>
                {liste.map((benutzer) => {
                  const sicherheit = [
                    benutzer.totp_aktiv ? "2FA" : null,
                    (benutzer.passkey_anzahl || 0) > 0 ? `${benutzer.passkey_anzahl} Passkey${(benutzer.passkey_anzahl || 0) > 1 ? "s" : ""}` : null,
                  ].filter(Boolean).join(" · ");
                  return (
                    <tr
                      key={benutzer.benutzer_id}
                      className={`click ${benutzer.benutzer_id === wahl ? "aktiv" : ""} ${benutzer.aktiv ? "" : "archiv"}`}
                      onClick={() => auswaehlen(benutzer)}
                    >
                      <td className="zelle-nowrap">
                        {benutzer.benutzername}
                        {benutzer.benutzer_id === aktuell.benutzer_id && <span className="hinweis"> (ich)</span>}
                      </td>
                      <td>
                        <div>{benutzer.name || "—"}</div>
                        {benutzer.email && <div className="hinweis zelle-subtext">{benutzer.email}</div>}
                      </td>
                      <td className="zelle-nowrap">
                        <span className={`status-badge ${benutzer.rolle === "admin" ? "offen" : "gedaempft"}`}>
                          {benutzer.rolle === "admin" ? "Admin" : "Benutzer"}
                        </span>
                        {benutzer.auth_quelle === "ldap" && <span className="hinweis"> · LDAP</span>}
                      </td>
                      <td className="zelle-nowrap">
                        <span className={`status-badge ${!benutzer.aktiv ? "gedaempft" : benutzer.passwort_aendern ? "offen" : "ok"}`}>
                          {!benutzer.aktiv ? "gesperrt" : benutzer.passwort_aendern ? "Passwortwechsel offen" : "aktiv"}
                        </span>
                        {sicherheit && <span className="hinweis"> · {sicherheit}</span>}
                      </td>
                      <td className="zelle-rechts zelle-nowrap">
                        <div className="zeilen-knöpfe">
                          {benutzer.auth_quelle !== "ldap" && (
                            <button
                              type="button"
                              className="secondary kompakt-knopf"
                              onClick={(event) => {
                                event.stopPropagation();
                                void einladungSenden(benutzer);
                              }}
                            >
                              Einladung
                            </button>
                          )}
                          <button
                            type="button"
                            className="danger kompakt-knopf"
                            disabled={benutzer.benutzer_id === aktuell.benutzer_id}
                            title={benutzer.benutzer_id === aktuell.benutzer_id ? "Eigenes Konto kann nicht gelöscht werden" : "Benutzer löschen"}
                            onClick={(event) => {
                              event.stopPropagation();
                              void loeschen(benutzer);
                            }}
                          >
                            Löschen
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        <div>
          {gewaehlt ? (
            <form className="card" style={{ marginBottom: 0 }} onSubmit={(event) => void speichern(event)}>
              <div className="karten-kopf">
                <div>
                  <h2>{gewaehlt.benutzername} bearbeiten</h2>
                  <p className="hinweis">{gewaehlt.auth_quelle === "ldap" ? "LDAP-Konto" : "Lokales Benutzerkonto"}</p>
                </div>
                <button type="button" className="secondary kompakt-knopf" onClick={() => setWahl(null)}>Schließen</button>
              </div>
              <div className="form-stapel">
                <label>Anzeigename
                  <input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
                </label>
                <label>E-Mail-Adresse
                  <input type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} />
                </label>
                <label>Rolle
                  <select value={form.rolle} onChange={(event) => setForm({ ...form, rolle: event.target.value })}>
                    <option value="benutzer">Benutzer</option>
                    <option value="admin">Administrator</option>
                  </select>
                </label>
                {gewaehlt.auth_quelle === "ldap" ? (
                  <p className="hinweis">Das Passwort wird zentral im LDAP-Verzeichnis verwaltet.</p>
                ) : (
                  <label>Neues Passwort (optional)
                    <input
                      type="password"
                      value={form.passwort}
                      placeholder="Leer lassen = unverändert"
                      autoComplete="new-password"
                      onChange={(event) => setForm({ ...form, passwort: event.target.value })}
                    />
                  </label>
                )}
                <label className="check">
                  <input type="checkbox" checked={form.aktiv} onChange={(event) => setForm({ ...form, aktiv: event.target.checked })} />
                  Konto ist aktiv (Anmeldung erlaubt)
                </label>
              </div>
              <div className="karten-fuss">
                <button type="submit">Änderungen speichern</button>
              </div>
            </form>
          ) : (
            <form className="card" style={{ marginBottom: 0 }} onSubmit={(event) => void anlegen(event)}>
              <div className="karten-kopf">
                <div>
                  <h2>Neuer Benutzer</h2>
                  <p className="hinweis">Zugang mit Startpasswort oder Einladungs-Link anlegen.</p>
                </div>
              </div>
              <div className="form-stapel">
                <label>Benutzername
                  <input value={neu.benutzername} onChange={(event) => setNeu({ ...neu, benutzername: event.target.value })} required />
                </label>
                <label>Anzeigename
                  <input value={neu.name} onChange={(event) => setNeu({ ...neu, name: event.target.value })} placeholder="z. B. Maria Beispiel" />
                </label>
                <label>E-Mail-Adresse
                  <input type="email" value={neu.email} onChange={(event) => setNeu({ ...neu, email: event.target.value })} placeholder="name@firma.de" required={neu.einladung} />
                </label>
                <label>Rolle
                  <select value={neu.rolle} onChange={(event) => setNeu({ ...neu, rolle: event.target.value })}>
                    <option value="benutzer">Benutzer</option>
                    <option value="admin">Administrator</option>
                  </select>
                </label>
                <label className="check">
                  <input type="checkbox" checked={neu.einladung} onChange={(event) => setNeu({ ...neu, einladung: event.target.checked })} />
                  Per E-Mail einladen (statt Startpasswort)
                </label>
                {!neu.einladung && (
                  <label>Startpasswort (mind. 8 Zeichen)
                    <input type="password" value={neu.passwort} autoComplete="new-password" onChange={(event) => setNeu({ ...neu, passwort: event.target.value })} required={!neu.einladung} />
                  </label>
                )}
              </div>
              <div className="karten-fuss">
                <button type="submit">Benutzer anlegen</button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
