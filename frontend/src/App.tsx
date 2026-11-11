import { useEffect, useState, type FormEvent } from "react";
import { startAuthentication } from "@simplewebauthn/browser";
import { ApiFehler, api } from "./api";
import { BelegeSeite } from "./Belege";
import { BenutzerSeite, type Benutzer } from "./Benutzer";
import { KundenSeite } from "./Kunden";
import { KontozeilenSeite } from "./Kontozeilen";
import { EinstellungenSeite } from "./Optionen";
import { RechnungenSeite } from "./Rechnungen";
import { Ablegen } from "./Ablegen";
import { ScanSeite } from "./Scan";
import { KontoSeite } from "./Konto";
import { PasswortSetzen, PasswortVergessen } from "./Zugang";
import { IconBeleg, IconBenutzer, IconGear, IconKontozeilen, IconKunden, IconMoon, IconRechnung, IconScan, IconSun } from "./icons";
import { PRODUCT_NAME } from "./brand";
import { LinkIntern, routeLesen } from "./nav";
import { useTheme } from "./theme";

function Fehler({ text }: { text: string }) {
  if (!text) return null;
  return <p className="fehler">{text}</p>;
}

export function App() {
  const [benutzer, setBenutzer] = useState<Benutzer | null | undefined>(undefined);
  const [route, setRoute] = useState(routeLesen);
  const [fehler, setFehler] = useState("");
  const { theme, dark, cycle } = useTheme();
  const themeTitel = theme === "system" ? "Farbschema: System" : theme === "light" ? "Farbschema: Hell" : "Farbschema: Dunkel";

  useEffect(() => {
    api<Benutzer>("/api/auth/me").then(setBenutzer).catch(() => setBenutzer(null));
  }, []);

  useEffect(() => {
    const neu = () => setRoute(routeLesen());
    window.addEventListener("popstate", neu);
    return () => window.removeEventListener("popstate", neu);
  }, []);

  if (benutzer === undefined) return <main>Laden …</main>;
  if (benutzer === null) {
    if (route.seite === "passwort-vergessen") return <PasswortVergessen />;
    if (route.seite === "passwort-setzen") return <PasswortSetzen />;
    return <Login onOk={(neu) => { setBenutzer(neu); setFehler(""); }} />;
  }
  if (benutzer.passwort_aendern) {
    return <PasswortAendern benutzer={benutzer} onOk={setBenutzer} />;
  }
  const istAdmin = benutzer.rolle === "admin";

  return (
    <div className="shell">
      <nav className="navi">
        <div className="navi-scroll">
          <div className="navi-kopf">
            <strong>{PRODUCT_NAME}</strong>
            <span className="navi-benutzer">{benutzer.name || benutzer.benutzername}</span>
          </div>
          <LinkIntern href="/rechnungen" className={`navi-link ${route.seite === "rechnungen" ? "active" : ""}`}><IconRechnung className="navi-icon" />Rechnungen</LinkIntern>
          <LinkIntern href="/kunden" className={`navi-link ${route.seite === "kunden" ? "active" : ""}`}><IconKunden className="navi-icon" />Kunden</LinkIntern>
          <LinkIntern href="/belege" className={`navi-link ${route.seite === "belege" ? "active" : ""}`}><IconBeleg className="navi-icon" />Belegbearbeitung</LinkIntern>
          <LinkIntern href="/scan" className={`navi-link ${route.seite === "scan" ? "active" : ""}`}><IconScan className="navi-icon" />Scannen</LinkIntern>
          <LinkIntern href="/kontozeilen" className={`navi-link ${route.seite === "kontozeilen" ? "active" : ""}`}><IconKontozeilen className="navi-icon" />Kontozeilen</LinkIntern>
          <LinkIntern href="/einstellungen" className={`navi-link ${route.seite === "einstellungen" ? "active" : ""}`}><IconGear className="navi-icon" />Einstellungen</LinkIntern>
          {istAdmin && (
            <LinkIntern href="/benutzer" className={`navi-link ${route.seite === "benutzer" ? "active" : ""}`}><IconBenutzer className="navi-icon" />Benutzer</LinkIntern>
          )}
        </div>
        <div className="navi-fuss">
          <Ablegen onFehler={setFehler} />
          <div className="navi-fuss-zeile">
            <button type="button" className="thema-knopf" onClick={cycle} title={themeTitel}>{dark ? <IconSun className="navi-icon" /> : <IconMoon className="navi-icon" />}</button>
            <button type="button" className="abmelden" onClick={async () => { await api("/api/auth/logout", { method: "POST" }); setBenutzer(null); }}>Abmelden</button>
          </div>
          <LinkIntern href="/konto" className={`konto-link ${route.seite === "konto" ? "active" : ""}`}>Passwort ändern</LinkIntern>
        </div>
      </nav>
      <main>
        <Fehler text={fehler} />
        {route.seite === "rechnungen" && <RechnungenSeite rechnungId={route.id} onFehler={setFehler} />}
        {route.seite === "kunden" && <KundenSeite kundeId={route.id} neu={route.neu} onFehler={setFehler} />}
        {route.seite === "belege" && <BelegeSeite belegId={route.id} onFehler={setFehler} />}
        {route.seite === "scan" && <ScanSeite onFehler={setFehler} />}
        {route.seite === "kontozeilen" && <KontozeilenSeite bewegungId={route.id} onFehler={setFehler} />}
        {route.seite === "einstellungen" && <EinstellungenSeite onFehler={setFehler} istAdmin={istAdmin} />}
        {route.seite === "konto" && <KontoSeite benutzer={benutzer} onFehler={setFehler} />}
        {route.seite === "benutzer" && istAdmin && <BenutzerSeite aktuell={benutzer} onFehler={setFehler} />}
      </main>
    </div>
  );
}

type LoginAntwort = Benutzer | { mfa_erforderlich: true; methoden: string[] };

function Login({ onOk }: { onOk: (benutzer: Benutzer) => void }) {
  const [benutzername, setBenutzername] = useState("");
  const [password, setPassword] = useState("");
  const [mfa, setMfa] = useState<string[] | null>(null);
  const [code, setCode] = useState("");
  const [fehler, setFehler] = useState("");

  async function senden(event: FormEvent) {
    event.preventDefault();
    setFehler("");
    try {
      const antwort = await api<LoginAntwort>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ benutzername, password }),
      });
      if ("mfa_erforderlich" in antwort) {
        setPassword("");
        setMfa(antwort.methoden);
      } else {
        onOk(antwort);
      }
    } catch (exc) {
      setFehler(exc instanceof ApiFehler ? exc.message : "Anmeldung fehlgeschlagen.");
    }
  }

  async function mfaSenden(event: FormEvent) {
    event.preventDefault();
    setFehler("");
    try {
      onOk(await api<Benutzer>("/api/auth/mfa", { method: "POST", body: JSON.stringify({ code }) }));
    } catch (exc) {
      setFehler(exc instanceof ApiFehler ? exc.message : "Code ungültig.");
    }
  }

  async function mitPasskey() {
    setFehler("");
    try {
      const optionen = await api<Record<string, unknown>>("/api/auth/passkey/optionen", {
        method: "POST",
        body: JSON.stringify({ benutzername }),
      });
      const credential = await startAuthentication({ optionsJSON: optionen as never });
      onOk(await api<Benutzer>("/api/auth/passkey/verifizieren", {
        method: "POST",
        body: JSON.stringify({ credential }),
      }));
    } catch (exc) {
      if (exc instanceof Error && exc.name === "NotAllowedError") setFehler("Passkey-Anmeldung abgebrochen.");
      else setFehler(exc instanceof ApiFehler ? exc.message : "Passkey-Anmeldung nicht möglich.");
    }
  }

  if (mfa !== null) {
    return (
      <form className="login" onSubmit={mfaSenden}>
        <h1>{PRODUCT_NAME}</h1>
        <p className="hinweis">
          Zweiter Faktor{mfa.includes("backup_code") ? " (Code aus der App oder Backup-Code)" : " (Code aus der App)"}:
        </p>
        <label>Code<input value={code} onChange={(event) => setCode(event.target.value)} autoFocus inputMode="numeric" autoComplete="one-time-code" /></label>
        <Fehler text={fehler} />
        <p><button type="submit">Bestätigen</button></p>
        <p><button type="button" className="secondary" onClick={() => { setMfa(null); setCode(""); }}>Zurück</button></p>
      </form>
    );
  }

  return (
    <form className="login" onSubmit={senden}>
      <h1>{PRODUCT_NAME}</h1>
      <label>Benutzername<input value={benutzername} onChange={(event) => setBenutzername(event.target.value)} autoFocus autoComplete="username" /></label>
      <label>Passwort<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label>
      <Fehler text={fehler} />
      <p><button type="submit">Anmelden</button></p>
      <p><button type="button" className="secondary" onClick={() => void mitPasskey()}>Mit Passkey anmelden</button></p>
      <div className="links">
        <LinkIntern href="/passwort-vergessen">Passwort vergessen?</LinkIntern>
      </div>
    </form>
  );
}

function PasswortAendern({ benutzer, onOk }: { benutzer: Benutzer; onOk: (benutzer: Benutzer) => void }) {
  const [alt, setAlt] = useState("");
  const [neu, setNeu] = useState("");
  const [wiederholung, setWiederholung] = useState("");
  const [fehler, setFehler] = useState("");
  async function senden(event: FormEvent) {
    event.preventDefault();
    setFehler("");
    if (neu !== wiederholung) {
      setFehler("Die Passwörter stimmen nicht überein.");
      return;
    }
    try {
      onOk(await api<Benutzer>("/api/auth/passwort", { method: "PUT", body: JSON.stringify({ alt, neu }) }));
    } catch (exc) {
      setFehler(exc instanceof ApiFehler ? exc.message : "Passwort nicht geändert.");
    }
  }
  return (
    <form className="login" onSubmit={senden}>
      <h1>{PRODUCT_NAME}</h1>
      <p className="hinweis">Hallo {benutzer.benutzername}, bitte vergib ein eigenes Passwort (mind. 8 Zeichen).</p>
      <label>Altes Passwort<input type="password" value={alt} onChange={(event) => setAlt(event.target.value)} autoFocus autoComplete="current-password" /></label>
      <label>Neues Passwort<input type="password" value={neu} onChange={(event) => setNeu(event.target.value)} autoComplete="new-password" /></label>
      <label>Neues Passwort wiederholen<input type="password" value={wiederholung} onChange={(event) => setWiederholung(event.target.value)} autoComplete="new-password" /></label>
      <Fehler text={fehler} />
      <p><button type="submit">Passwort speichern</button></p>
    </form>
  );
}
