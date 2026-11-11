import { useEffect, useState, type FormEvent } from "react";
import { startRegistration } from "@simplewebauthn/browser";
import { ApiFehler, api } from "./api";

type Passkey = {
  passkey_id: number;
  name: string;
  erstellt: string | null;
  zuletzt_benutzt: string | null;
};

type Status = {
  totp_aktiv: boolean;
  backup_codes_uebrig: number;
  passwort_moeglich: boolean;
  passkeys: Passkey[];
};

type Start = { secret: string; otpauth_uri: string; qr_svg: string };

export function SicherheitEinstellungen({ onFehler }: { onFehler: (text: string) => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [start, setStart] = useState<Start | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [deaktivieren, setDeaktivieren] = useState(false);
  const [passwort, setPasswort] = useState("");
  const [neuName, setNeuName] = useState("");
  const [namen, setNamen] = useState<Record<number, string>>({});
  const [fehler, setFehler] = useState("");
  const [hinweis, setHinweis] = useState("");

  async function laden() {
    try {
      setStatus(await api<Status>("/api/sicherheit"));
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Sicherheitseinstellungen nicht geladen.");
    }
  }

  useEffect(() => {
    void laden();
  }, []);

  function meldung(exc: unknown, fallback: string) {
    setFehler(exc instanceof ApiFehler ? exc.message : fallback);
  }

  async function einrichten() {
    setFehler("");
    setHinweis("");
    try {
      setStart(await api<Start>("/api/sicherheit/totp/einrichten", { method: "POST" }));
    } catch (exc) {
      meldung(exc, "Einrichtung fehlgeschlagen.");
    }
  }

  async function aktivieren(event: FormEvent) {
    event.preventDefault();
    setFehler("");
    try {
      const antwort = await api<{ backup_codes: string[] }>("/api/sicherheit/totp/aktivieren", {
        method: "POST",
        body: JSON.stringify({ code }),
      });
      setCodes(antwort.backup_codes);
      setStart(null);
      setCode("");
      setHinweis("Zwei-Faktor ist aktiv. Backup-Codes gut aufbewahren — sie werden nur einmal gezeigt.");
      await laden();
    } catch (exc) {
      meldung(exc, "Code stimmt nicht.");
    }
  }

  async function backupNeu(event: FormEvent) {
    event.preventDefault();
    setFehler("");
    try {
      const antwort = await api<{ backup_codes: string[] }>("/api/sicherheit/totp/backup-codes", {
        method: "POST",
        body: JSON.stringify({ code }),
      });
      setCodes(antwort.backup_codes);
      setCode("");
      setHinweis("Neue Backup-Codes erzeugt. Alte Codes sind ungültig.");
      await laden();
    } catch (exc) {
      meldung(exc, "Code stimmt nicht.");
    }
  }

  async function abschalten(event: FormEvent) {
    event.preventDefault();
    setFehler("");
    try {
      await api("/api/sicherheit/totp/deaktivieren", {
        method: "POST",
        body: JSON.stringify({ passwort, code }),
      });
      setDeaktivieren(false);
      setPasswort("");
      setCode("");
      setHinweis("Zwei-Faktor ist deaktiviert.");
      await laden();
    } catch (exc) {
      meldung(exc, "Deaktivieren fehlgeschlagen.");
    }
  }

  async function passkeyAnlegen(event: FormEvent) {
    event.preventDefault();
    setFehler("");
    setHinweis("");
    try {
      const optionen = await api<Record<string, unknown>>("/api/sicherheit/passkeys/optionen", { method: "POST" });
      const credential = await startRegistration({ optionsJSON: optionen as never });
      await api("/api/sicherheit/passkeys/verifizieren", {
        method: "POST",
        body: JSON.stringify({ credential, name: neuName }),
      });
      setNeuName("");
      setHinweis("Passkey registriert.");
      await laden();
    } catch (exc) {
      if (exc instanceof Error && exc.name === "NotAllowedError") setFehler("Registrierung abgebrochen.");
      else meldung(exc, "Passkey konnte nicht registriert werden.");
    }
  }

  async function umbenennen(passkey: Passkey) {
    const name = (namen[passkey.passkey_id] ?? passkey.name).trim();
    if (!name || name === passkey.name) return;
    try {
      await api(`/api/sicherheit/passkeys/${passkey.passkey_id}`, {
        method: "PATCH",
        body: JSON.stringify({ name }),
      });
      await laden();
    } catch (exc) {
      meldung(exc, "Name nicht gespeichert.");
    }
  }

  async function loeschen(passkey: Passkey) {
    if (!window.confirm(`Passkey „${passkey.name}“ entfernen?`)) return;
    try {
      await api(`/api/sicherheit/passkeys/${passkey.passkey_id}`, { method: "DELETE" });
      setHinweis("Passkey entfernt.");
      await laden();
    } catch (exc) {
      meldung(exc, "Passkey nicht entfernt.");
    }
  }

  function datum(wert: string | null) {
    if (!wert) return "—";
    const d = new Date(wert);
    return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("de-DE");
  }

  if (!status) return <p>Laden …</p>;

  return (
    <>
      {fehler && <p className="fehler">{fehler}</p>}
      {hinweis && <p className="hinweis">{hinweis}</p>}
      <div className="card">
        <h2>Zwei-Faktor (Authenticator-App)</h2>
        {!status.totp_aktiv && !start && (
          <>
            <p className="hinweis">Beim Anmelden wird zusätzlich ein 6-stelliger Code aus einer Authenticator-App verlangt.</p>
            <div className="actions">
              <button type="button" onClick={() => void einrichten()}>Zwei-Faktor einrichten</button>
            </div>
          </>
        )}
        {!status.totp_aktiv && start && (
          <form onSubmit={(event) => void aktivieren(event)}>
            <p className="hinweis">Code scannen oder Geheimnis von Hand eintragen, dann mit einem Code aus der App bestätigen.</p>
            <div className="sicherheit-qr">
              <img src={start.qr_svg} alt="QR-Code für die Authenticator-App" />
            </div>
            <p className="code-box">{start.secret}</p>
            <div className="form-gruppen">
              <label>Code aus der App
                <input value={code} onChange={(event) => setCode(event.target.value)} inputMode="numeric" autoComplete="one-time-code" autoFocus />
              </label>
            </div>
            <div className="actions" style={{ marginTop: "0.8rem" }}>
              <button type="submit">Aktivieren</button>
            </div>
          </form>
        )}
        {status.totp_aktiv && (
          <>
            <p className="hinweis">Aktiv. Noch {status.backup_codes_uebrig} Backup-Codes übrig.</p>
            <form onSubmit={(event) => void backupNeu(event)}>
              <div className="form-gruppen">
                <label>Code aus der App (für neue Backup-Codes)
                  <input value={code} onChange={(event) => setCode(event.target.value)} inputMode="numeric" autoComplete="one-time-code" />
                </label>
              </div>
              <div className="actions" style={{ marginTop: "0.8rem" }}>
                <button type="submit" className="secondary">Neue Backup-Codes</button>
                <button type="button" className="danger" onClick={() => setDeaktivieren(!deaktivieren)}>Deaktivieren</button>
              </div>
            </form>
            {deaktivieren && (
              <form onSubmit={(event) => void abschalten(event)}>
                <div className="form-gruppen">
                  {status.passwort_moeglich && (
                    <label>Aktuelles Passwort
                      <input type="password" value={passwort} onChange={(event) => setPasswort(event.target.value)} autoComplete="current-password" />
                    </label>
                  )}
                  <label>Bestätigungscode (App oder Backup-Code)
                    <input value={code} onChange={(event) => setCode(event.target.value)} inputMode="numeric" autoComplete="one-time-code" />
                  </label>
                </div>
                <div className="actions" style={{ marginTop: "0.8rem" }}>
                  <button type="submit" className="danger">Wirklich deaktivieren</button>
                </div>
              </form>
            )}
          </>
        )}
        {codes && (
          <>
            <h3>Backup-Codes (einmalig)</h3>
            <div className="backup-codes">
              {codes.map((c) => (
                <span key={c}>{c}</span>
              ))}
            </div>
          </>
        )}
      </div>
      <div className="card">
        <h2>Passkeys</h2>
        <p className="hinweis">Anmelden ohne Passwort, z. B. mit Fingerabdruck oder Sicherheitsschlüssel.</p>
        {status.passkeys.length === 0 && <p className="hinweis">Noch keine Passkeys registriert.</p>}
        {status.passkeys.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Erstellt</th>
                <th>Zuletzt benutzt</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {status.passkeys.map((passkey) => (
                <tr key={passkey.passkey_id}>
                  <td>
                    <input
                      value={namen[passkey.passkey_id] ?? passkey.name}
                      onChange={(event) => setNamen({ ...namen, [passkey.passkey_id]: event.target.value })}
                      onBlur={() => void umbenennen(passkey)}
                    />
                  </td>
                  <td>{datum(passkey.erstellt)}</td>
                  <td>{datum(passkey.zuletzt_benutzt)}</td>
                  <td>
                    <button type="button" className="danger" onClick={() => void loeschen(passkey)}>Entfernen</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <form onSubmit={(event) => void passkeyAnlegen(event)}>
          <div className="form-gruppen">
            <label>Name für den neuen Passkey
              <input value={neuName} onChange={(event) => setNeuName(event.target.value)} placeholder="z. B. Laptop" />
            </label>
          </div>
          <div className="actions" style={{ marginTop: "0.8rem" }}>
            <button type="submit">Passkey registrieren</button>
          </div>
        </form>
      </div>
    </>
  );
}
