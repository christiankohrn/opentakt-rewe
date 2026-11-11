import { useState, type FormEvent } from "react";
import { ApiFehler, api } from "./api";
import type { Benutzer } from "./Benutzer";
import { SicherheitEinstellungen } from "./Sicherheit";

export function KontoSeite({ benutzer, onFehler }: { benutzer: Benutzer; onFehler: (text: string) => void }) {
  const [alt, setAlt] = useState("");
  const [neu, setNeu] = useState("");
  const [wiederholung, setWiederholung] = useState("");
  const [fehler, setFehler] = useState("");
  const [hinweis, setHinweis] = useState("");
  const [beschaeftigt, setBeschaeftigt] = useState(false);
  const ldap = benutzer.auth_quelle === "ldap";
  const neuOk = neu.length >= 8;
  const treffer = neu.length > 0 && neu === wiederholung;

  async function senden(event: FormEvent) {
    event.preventDefault();
    setFehler("");
    setHinweis("");
    if (!neuOk) {
      setFehler("Mindestens 8 Zeichen.");
      return;
    }
    if (!treffer) {
      setFehler("Die neuen Passwörter stimmen nicht überein.");
      return;
    }
    setBeschaeftigt(true);
    try {
      await api("/api/auth/passwort", { method: "PUT", body: JSON.stringify({ alt, neu }) });
      setAlt("");
      setNeu("");
      setWiederholung("");
      setHinweis("Passwort gespeichert.");
      onFehler("");
    } catch (exc) {
      setFehler(exc instanceof ApiFehler ? exc.message : "Passwort nicht geändert.");
    } finally {
      setBeschaeftigt(false);
    }
  }

  return (
    <div className="optionen-seite konto-seite">
      <header className="optionen-kopf">
        <h1>Konto</h1>
      </header>
      <p className="hinweis">{benutzer.name ? `${benutzer.name} · ${benutzer.benutzername}` : benutzer.benutzername}</p>
      {ldap ? (
        <div className="card">
          <h2>Passwort ändern</h2>
          <p className="hinweis">LDAP-Konto: Das Passwort wird im Verzeichnis geändert.</p>
        </div>
      ) : (
        <form className="card" onSubmit={(event) => void senden(event)}>
          <h2>Passwort ändern</h2>
          <div className="form-gruppen">
            <label>Aktuelles Passwort
              <input type="password" value={alt} onChange={(event) => setAlt(event.target.value)} autoComplete="current-password" required />
            </label>
            <label>Neues Passwort (mind. 8 Zeichen)
              <input type="password" value={neu} onChange={(event) => setNeu(event.target.value)} autoComplete="new-password" minLength={8} required />
            </label>
            <label>Neues Passwort wiederholen
              <input type="password" value={wiederholung} onChange={(event) => setWiederholung(event.target.value)} autoComplete="new-password" minLength={8} required />
            </label>
          </div>
          {neu.length > 0 && !neuOk && <p className="fehler">Mindestens 8 Zeichen.</p>}
          {wiederholung.length > 0 && neu !== wiederholung && <p className="fehler">Die Passwörter stimmen nicht überein.</p>}
          {fehler && <p className="fehler">{fehler}</p>}
          {hinweis && <p className="hinweis">{hinweis}</p>}
          <div className="actions" style={{ marginTop: "0.8rem" }}>
            <button type="submit" disabled={beschaeftigt}>{beschaeftigt ? "…" : "Passwort speichern"}</button>
          </div>
        </form>
      )}
      <h2 className="konto-sicherheit-titel">Sicherheit</h2>
      <p className="hinweis">Zwei-Faktor-Authentisierung und Passkeys für dein Konto.</p>
      <SicherheitEinstellungen onFehler={onFehler} />
    </div>
  );
}
