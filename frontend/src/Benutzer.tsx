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
        setHinweis(`Benutzer ${angelegt.benutzername} angelegt. Er muss beim ersten Login ein eigenes Passwort vergeben.`);
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
      <div className="optionen-zwei">
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Benutzerkonten ({liste.length})</h2>
          <p className="hinweis">Zeile antippen, um Namen, E-Mail, Rolle oder Passwort zu bearbeiten.</p>
          <div className="tabelle-scroll">
            <table>
              <thead>
                <tr>
                  <th>Benutzername</th>
                  <th>Name</th>
                  <th>Rolle</th>
                  <th>Quelle</th>
                  <th>2FA</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {liste.map((benutzer) => (
                  <tr
                    key={benutzer.benutzer_id}
                    className={`click ${benutzer.benutzer_id === wahl ? "aktiv" : ""} ${benutzer.aktiv ? "" : "archiv"}`}
                    onClick={() => auswaehlen(benutzer)}
                  >
                    <td>
                      <strong>{benutzer.benutzername}</strong>
                      {benutzer.benutzer_id === aktuell.benutzer_id && <span className="hinweis"> (ich)</span>}
                    </td>
                    <td>{benutzer.name || "—"}</td>
                    <td>{benutzer.rolle === "admin" ? "Admin" : "Benutzer"}</td>
                    <td>{benutzer.auth_quelle === "ldap" ? "LDAP" : "Lokal"}</td>
                    <td>
                      {[
                        benutzer.totp_aktiv ? "App" : null,
                        (benutzer.passkey_anzahl || 0) > 0 ? `${benutzer.passkey_anzahl} Key${(benutzer.passkey_anzahl || 0) > 1 ? "s" : ""}` : null,
                      ].filter(Boolean).join(" · ") || "—"}
                    </td>
                    <td>
                      {!benutzer.aktiv ? "gesperrt" : benutzer.passwort_aendern ? "muss Passwort ändern" : "aktiv"}
                    </td>
                    <td>
                      <div className="actions" style={{ margin: 0, flexWrap: "nowrap" }}>
                        {benutzer.auth_quelle !== "ldap" && (
                          <button type="button" className="secondary kompakt-knopf" onClick={(event) => { event.stopPropagation(); void einladungSenden(benutzer); }}>
                            Einladung
                          </button>
                        )}
                        <button type="button" className="danger kompakt-knopf" onClick={(event) => { event.stopPropagation(); void loeschen(benutzer); }}>
                          Löschen
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="optionen-stapel">
          {gewaehlt && (
            <form className="card" onSubmit={(event) => void speichern(event)}>
              <div className="liste-werkzeug">
                <h2 style={{ margin: 0 }}>{gewaehlt.benutzername} bearbeiten</h2>
                <button type="button" className="secondary kompakt-knopf" onClick={() => setWahl(null)}>Schließen</button>
              </div>
              <div className="form-gruppen" style={{ marginTop: "0.6rem" }}>
                <label>Name
                  <input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
                </label>
                <label>E-Mail
                  <input type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} />
                </label>
                <label>Rolle
                  <select value={form.rolle} onChange={(event) => setForm({ ...form, rolle: event.target.value })}>
                    <option value="benutzer">Benutzer</option>
                    <option value="admin">Admin</option>
                  </select>
                </label>
                {gewaehlt.auth_quelle === "ldap" ? (
                  <p className="hinweis">LDAP-Konto: Passwort wird im Verzeichnis geändert.</p>
                ) : (
                  <label>Neues Passwort (leer = unverändert)
                    <input type="password" value={form.passwort} autoComplete="new-password" onChange={(event) => setForm({ ...form, passwort: event.target.value })} />
                  </label>
                )}
              </div>
              <div className="actions" style={{ marginTop: "0.8rem" }}>
                <label className="check" style={{ marginRight: "1rem" }}>
                  <input type="checkbox" checked={form.aktiv} onChange={(event) => setForm({ ...form, aktiv: event.target.checked })} />
                  Aktiv
                </label>
                <button type="submit">Änderungen speichern</button>
              </div>
            </form>
          )}
          <form className="card" onSubmit={(event) => void anlegen(event)}>
            <h2 style={{ marginTop: 0 }}>Neuen Benutzer anlegen</h2>
            <div className="form-gruppen">
              <label>Benutzername
                <input value={neu.benutzername} onChange={(event) => setNeu({ ...neu, benutzername: event.target.value })} required />
              </label>
              <label>Name
                <input value={neu.name} onChange={(event) => setNeu({ ...neu, name: event.target.value })} />
              </label>
              <label>E-Mail
                <input type="email" value={neu.email} onChange={(event) => setNeu({ ...neu, email: event.target.value })} />
              </label>
              {!neu.einladung && (
                <label>Startpasswort (mind. 8 Zeichen)
                  <input type="password" value={neu.passwort} autoComplete="new-password" onChange={(event) => setNeu({ ...neu, passwort: event.target.value })} required={!neu.einladung} />
                </label>
              )}
              <label>Rolle
                <select value={neu.rolle} onChange={(event) => setNeu({ ...neu, rolle: event.target.value })}>
                  <option value="benutzer">Benutzer</option>
                  <option value="admin">Admin</option>
                </select>
              </label>
              <label className="check">
                <input type="checkbox" checked={neu.einladung} onChange={(event) => setNeu({ ...neu, einladung: event.target.checked })} />
                Per E-Mail einladen (statt Startpasswort)
              </label>
            </div>
            <div className="actions" style={{ marginTop: "0.8rem" }}>
              <button type="submit">Benutzer anlegen</button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
