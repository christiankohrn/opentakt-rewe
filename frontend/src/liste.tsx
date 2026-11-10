import type { MouseEvent, ReactNode } from "react";

export type Sortierung = { spalte: string; richtung: "auf" | "ab" };

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
  href,
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
}: {
  zeilen: T[];
  zeilenId: (zeile: T) => number;
  href: (zeile: T) => string;
  spalten: { key: string; titel: string; zelle: (zeile: T) => ReactNode }[];
  aktivId: number | null;
  gewaehlt: number[];
  sortierung: Sortierung | null;
  onSort: (spalte: string) => void;
  onZeile: (event: MouseEvent<HTMLTableRowElement>, index: number) => void;
  onDoppel?: (index: number) => void;
  onKontext?: (event: MouseEvent<HTMLTableRowElement>, index: number) => void;
  vorn?: (zeile: T) => ReactNode;
  klasse?: (zeile: T) => string;
}) {
  return (
    <table>
      <thead>
        <tr>
          {vorn && <th />}
          {spalten.map((spalte) => (
            <th key={spalte.key}>
              <button type="button" className="sort" onClick={() => onSort(spalte.key)}>
                {spalte.titel}
                {sortierung?.spalte === spalte.key ? (sortierung.richtung === "ab" ? " ↓" : " ↑") : ""}
              </button>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {zeilen.map((zeile, index) => {
          const id = zeilenId(zeile);
          return (
            <tr
              key={id}
              className={`${aktivId === id ? "aktiv " : ""}${gewaehlt.includes(id) ? "markiert " : ""}${klasse ? klasse(zeile) : ""}`}
              onMouseDown={(event) => { if (event.shiftKey) event.preventDefault(); }}
              onClick={(event) => onZeile(event, index)}
              onDoubleClick={() => onDoppel?.(index)}
              onContextMenu={(event) => { if (!onKontext) return; event.preventDefault(); onKontext(event, index); }}
            >
              {vorn && <td>{vorn(zeile)}</td>}
              {spalten.map((spalte, spaltenIndex) => (
                <td key={spalte.key}>
                  {spaltenIndex === 0
                    ? <a href={href(zeile)} onClick={(event) => { if (event.button === 0) event.preventDefault(); }}>{spalte.zelle(zeile)}</a>
                    : spalte.zelle(zeile)}
                </td>
              ))}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
