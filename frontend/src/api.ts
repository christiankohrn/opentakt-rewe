export class ApiFehler extends Error {}

async function fehlertext(res: Response): Promise<string> {
  try {
    const daten = await res.json();
    if (typeof daten.detail === "string") return daten.detail;
    return JSON.stringify(daten.detail);
  } catch {
    return res.statusText || "Fehler";
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers, credentials: "include" });
  if (res.status === 401) throw new ApiFehler("Nicht angemeldet.");
  if (!res.ok) throw new ApiFehler(await fehlertext(res));
  if (res.status === 204) return undefined as T;
  const typ = res.headers.get("content-type") || "";
  if (typ.includes("application/pdf")) return (await res.blob()) as T;
  return res.json() as Promise<T>;
}

export async function dateiSenden<T>(path: string, datei: File, felder: Record<string, string>): Promise<T> {
  const body = new FormData();
  body.append("datei", datei);
  for (const [name, wert] of Object.entries(felder)) body.append(name, wert);
  const res = await fetch(path, { method: "POST", body, credentials: "include" });
  if (res.status === 401) throw new ApiFehler("Nicht angemeldet.");
  if (!res.ok) throw new ApiFehler(await fehlertext(res));
  return res.json() as Promise<T>;
}

export async function dateiSpeichern(path: string, dateiname: string): Promise<void> {
  const res = await fetch(path, { credentials: "include" });
  if (!res.ok) throw new ApiFehler(await fehlertext(res));
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = dateiname;
  link.click();
  URL.revokeObjectURL(url);
}

export async function pdfSpeichern(path: string, body: unknown, dateiname: string): Promise<void> {
  const blob = await api<Blob>(path, { method: "POST", body: JSON.stringify(body) });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = dateiname;
  link.click();
  URL.revokeObjectURL(url);
}

export function geld(wert: string | number | null | undefined): string {
  const zahl = typeof wert === "number" ? wert : Number(wert || 0);
  return new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" }).format(zahl);
}

export function betragEingabe(wert: string | number | null | undefined): string {
  if (wert === null || wert === undefined) return "";
  const roh = String(wert).trim();
  if (!roh) return "";
  const zahl = Number(roh.replace(",", "."));
  if (Number.isNaN(zahl)) return roh;
  return zahl.toFixed(2).replace(".", ",");
}

export function hatExterneDateien(dt: DataTransfer | null | undefined): boolean {
  if (!dt) return false;
  const typen = Array.from(dt.types || []);
  if (!typen.includes("Files")) return false;
  if (typen.includes("text/uri-list") || typen.includes("text/html")) return false;
  return true;
}

export function datumDE(wert: string | null | undefined): string {
  if (!wert) return "";
  const [jahr, monat, tag] = wert.slice(0, 10).split("-");
  return `${tag}.${monat}.${jahr}`;
}

export function heuteISO(): string {
  const jetzt = new Date();
  const monat = String(jetzt.getMonth() + 1).padStart(2, "0");
  const tag = String(jetzt.getDate()).padStart(2, "0");
  return `${jetzt.getFullYear()}-${monat}-${tag}`;
}
