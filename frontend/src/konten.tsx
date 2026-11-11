import { useEffect, useState } from "react";
import { api } from "./api";

export type Kategorie = {
  schluessel: string;
  name: string;
  datev_email: string;
  weiterverarbeitung?: boolean;
  iban?: string;
  bic?: string;
};

export function useKategorien(): Kategorie[] {
  const [liste, setListe] = useState<Kategorie[]>([]);
  useEffect(() => {
    api<Kategorie[]>("/api/kategorien").then(setListe).catch(() => setListe([]));
  }, []);
  return liste;
}

export function KontoFilter({ wert, onChange }: { wert: string; onChange: (wert: string) => void }) {
  const kategorien = useKategorien();
  return (
    <div className="chip-leiste" role="group" aria-label="Konto filtern">
      <button type="button" className={wert === "" ? "" : "secondary"} onClick={() => onChange("")}>Alle</button>
      {kategorien.map((konto) => (
        <button key={konto.schluessel} type="button" className={wert === konto.schluessel ? "" : "secondary"} onClick={() => onChange(konto.schluessel)}>
          {konto.name}
        </button>
      ))}
    </div>
  );
}
