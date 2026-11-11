import { useEffect, useState, type FormEvent } from "react";
import { ApiFehler, api } from "./api";
import { PRODUCT_NAME } from "./brand";
import { LinkIntern } from "./nav";

export function PasswortVergessen() {
  const [kennung, setKennung] = useState("");
  const [fehler, setFehler] = useState("");
  const [fertig, setFertig] = useState(false);

  async function senden(event: FormEvent) {
    event.preventDefault();
    setFehler("");
    try {
      await api("/api/auth/vergessen", { method: "POST", body: JSON.stringify({ kennung }) });
      setFertig(true);
    } catch (exc) {
      setFehler(exc instanceof ApiFehler ? exc.message : "Anfrage fehlgeschlagen.");
    }
  }

  return (
    <div className="login-seite">
      <form className="login" onSubmit={senden}>
        <h1>{PRODUCT_NAME}</h1>
        {fertig ? (
          <>
            <p className="hinweis">Falls ein Konto existiert, ist eine E-Mail mit einem Link unterwegs (1 Stunde gültig).</p>
            <div className="links"><LinkIntern href="/">Zurück zur Anmeldung</LinkIntern></div>
          </>
        ) : (
          <>
            <p className="hinweis">Benutzername oder E-Mail eingeben — es kommt ein Link zum Zurücksetzen.</p>
            <label>Benutzername oder E-Mail
              <input value={kennung} onChange={(event) => setKennung(event.target.value)} autoFocus autoComplete="username" />
            </label>
            {fehler && <p className="fehler">{fehler}</p>}
            <div className="login-knöpfe">
              <button type="submit">Link anfordern</button>
            </div>
            <div className="links"><LinkIntern href="/">Zurück zur Anmeldung</LinkIntern></div>
          </>
        )}
      </form>
    </div>
  );
}

type TokenInfo = { benutzername: string; name: string; zweck: string };

export function PasswortSetzen() {
  const [info, setInfo] = useState<TokenInfo | null | undefined>(undefined);
  const [fehler, setFehler] = useState("");
  const [passwort, setPasswort] = useState("");
  const [wiederholung, setWiederholung] = useState("");
  const [fertig, setFertig] = useState(false);
  const token = new URLSearchParams(window.location.search).get("token") || "";

  useEffect(() => {
    api<TokenInfo>(`/api/auth/passwort-token?token=${encodeURIComponent(token)}`)
      .then(setInfo)
      .catch(() => setInfo(null));
  }, [token]);

  async function senden(event: FormEvent) {
    event.preventDefault();
    setFehler("");
    if (passwort !== wiederholung) {
      setFehler("Die Passwörter stimmen nicht überein.");
      return;
    }
    try {
      await api("/api/auth/passwort-token", { method: "POST", body: JSON.stringify({ token, passwort }) });
      setFertig(true);
    } catch (exc) {
      setFehler(exc instanceof ApiFehler ? exc.message : "Passwort nicht gesetzt.");
    }
  }

  if (info === undefined) return <main className="lade-vollbild">Laden …</main>;

  return (
    <div className="login-seite">
      <form className="login" onSubmit={senden}>
        <h1>{PRODUCT_NAME}</h1>
        {info === null && (
          <>
            <p className="fehler">Link ist ungültig oder abgelaufen.</p>
            <div className="links"><LinkIntern href="/">Zurück zur Anmeldung</LinkIntern></div>
          </>
        )}
        {info !== null && fertig && (
          <>
            <p className="hinweis">Passwort gesetzt. Du kannst dich jetzt anmelden.</p>
            <div className="links"><LinkIntern href="/">Zur Anmeldung</LinkIntern></div>
          </>
        )}
        {info !== null && !fertig && (
          <>
            <p className="hinweis">
              {info.zweck === "einladung" ? "Willkommen" : "Hallo"} {info.name || info.benutzername},
              bitte vergib ein Passwort (mind. 8 Zeichen).
            </p>
            <label>Neues Passwort
              <input type="password" value={passwort} onChange={(event) => setPasswort(event.target.value)} autoFocus autoComplete="new-password" />
            </label>
            <label>Neues Passwort wiederholen
              <input type="password" value={wiederholung} onChange={(event) => setWiederholung(event.target.value)} autoComplete="new-password" />
            </label>
            {fehler && <p className="fehler">{fehler}</p>}
            <div className="login-knöpfe">
              <button type="submit">Passwort speichern</button>
            </div>
          </>
        )}
      </form>
    </div>
  );
}
