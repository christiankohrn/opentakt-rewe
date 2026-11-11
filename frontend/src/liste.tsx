import type { MouseEvent, ReactNode } from "react";

export type Sortierung = { spalte: string; richtung: "auf" | "ab" };

export type Spalte<T> = {
  key: string;
  titel: string;
  zelle: (zeile: T) => ReactNode;
  ausrichtung?: "links" | "rechts";
  nowrap?: boolean;
};

export function zeilenWahl(
  event: { ctrlKey: boolean; metaKey: boolean; shiftKey: boolean },
  index: number,
  ids: number[],
  gewaehlt: number[],
  anker: number,
): { ids: number[]; anker: number } {
  if (event.shiftKey && anker >= 0) {
    const von = Math.min(anker, index);
    const bis = Math.max(anker, index);
    return { ids: ids.slice(von, bis + 1), anker };
  }
  const id = ids[index];
  if (event.ctrlKey || event.metaKey) {
    return {
      ids: gewaehlt.includes(id) ? gewaehlt.filter((wert) => wert !== id) : [...gewaehlt, id],
      anker: index,
    };
  }
  return { ids: [id], anker: index };
}

export function DatenListe<T>({
  zeilen,
  zeilenId,
  spalten,
  aktivId,
  gewaehlt,
  sortierung,
  onSort,
  onZeile,
  onDoppel,
  onKontext,
  vorn,
  klasse,
  leerText = "Keine Einträge vorhanden.",
}: {
  zeilen: T[];
  zeilenId: (zeile: T) => number;
  href?: (zeile: T) => string;
  spalten: Spalte<T>[];
  aktivId: number | null;
  gewaehlt: number[];
  sortierung: Sortierung | null;
  onSort?: (spalte: string) => void;
  onZeile: (event: MouseEvent<HTMLTableRowElement>, index: number) => void;
  onDoppel?: (index: number) => void;
  onKontext?: (event: MouseEvent<HTMLTableRowElement>, index: number) => void;
  vorn?: (zeile: T) => ReactNode;
  klasse?: (zeile: T) => string;
  leerText?: string;
}) {
  const gesamtSpalten = spalten.length + (vorn ? 1 : 0);

  return (
    <table className="daten-tabelle">
      <thead>
        <tr>
          {vorn && <th className="zelle-vorn" />}
          {spalten.map((spalte) => {
            const rechts = spalte.ausrichtung === "rechts";
            const aktivSort = sortierung?.spalte === spalte.key;
            return (
              <th key={spalte.key} className={rechts ? "zelle-rechts" : undefined}>
                {onSort ? (
                  <button type="button" className={`sort ${rechts ? "sort-rechts" : ""} ${aktivSort ? "sort-aktiv" : ""}`} onClick={() => onSort(spalte.key)}>
                    <span>{spalte.titel}</span>
                    {aktivSort && <span className="sort-pfeil">{sortierung.richtung === "ab" ? "↓" : "↑"}</span>}
                  </button>
                ) : (
                  <span>{spalte.titel}</span>
                )}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {zeilen.length === 0 ? (
          <tr className="zeile-leer">
            <td colSpan={gesamtSpalten} className="tabelle-leer">{leerText}</td>
          </tr>
        ) : (
          zeilen.map((zeile, index) => {
            const id = zeilenId(zeile);
            const klassen = [
              "click",
              aktivId === id ? "aktiv" : "",
              gewaehlt.includes(id) ? "markiert" : "",
              klasse ? klasse(zeile) : "",
            ].filter(Boolean).join(" ");
            return (
              <tr
                key={id}
                className={klassen}
                onMouseDown={(event) => { if (event.shiftKey) event.preventDefault(); }}
                onClick={(event) => onZeile(event, index)}
                onDoubleClick={() => onDoppel?.(index)}
                onContextMenu={(event) => { if (!onKontext) return; event.preventDefault(); onKontext(event, index); }}
              >
                {vorn && <td className="zelle-vorn">{vorn(zeile)}</td>}
                {spalten.map((spalte) => {
                  const zellKlassen = [
                    spalte.ausrichtung === "rechts" ? "zelle-rechts" : "",
                    spalte.nowrap ? "zelle-nowrap" : "",
                  ].filter(Boolean).join(" ");
                  return (
                    <td key={spalte.key} className={zellKlassen || undefined}>
                      {spalte.zelle(zeile)}
                    </td>
                  );
                })}
              </tr>
            );
          })
        )}
      </tbody>
    </table>
  );
}
