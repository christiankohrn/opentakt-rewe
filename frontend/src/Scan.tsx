import { useEffect, useRef, useState } from "react";
import { ApiFehler, dateiSenden } from "./api";
import { gehe } from "./nav";
import {
  aufhellen,
  bildLaden,
  canvasZuJpeg,
  eckenSortieren,
  erkenneDokument,
  jpegsZuPdf,
  perspektiveKorrigieren,
  type Viereck,
} from "./scan";

type Seite = { id: number; jpeg: Blob; vorschau: string };

function standardEcken(breite: number, hoehe: number): Viereck {
  const rx = breite * 0.06;
  const ry = hoehe * 0.06;
  return [
    { x: rx, y: ry },
    { x: breite - rx, y: ry },
    { x: breite - rx, y: hoehe - ry },
    { x: rx, y: hoehe - ry },
  ];
}

export function ScanSeite({ onFehler }: { onFehler: (text: string) => void }) {
  const [bild, setBild] = useState<HTMLImageElement | null>(null);
  const [bildUrl, setBildUrl] = useState("");
  const [ecken, setEcken] = useState<Viereck | null>(null);
  const [selbstErkannt, setSelbstErkannt] = useState(false);
  const [arbeitet, setArbeitet] = useState("");
  const [seiten, setSeiten] = useState<Seite[]>([]);
  const [fertigId, setFertigId] = useState<number | null>(null);
  const [seiteId, setSeiteId] = useState(1);
  const kamera = useRef<HTMLInputElement>(null);
  const auswahl = useRef<HTMLInputElement>(null);
  const zugId = useRef<number | null>(null);

  useEffect(() => () => {
    if (bildUrl) URL.revokeObjectURL(bildUrl);
    for (const seite of seiten) URL.revokeObjectURL(seite.vorschau);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function fotoNehmen(datei: File | undefined) {
    if (!datei) return;
    setFertigId(null);
    setArbeitet("Foto wird gelesen …");
    try {
      const geladen = await bildLaden(datei);
      setBildUrl((alt) => {
        if (alt) URL.revokeObjectURL(alt);
        return geladen.src;
      });
      setBild(geladen);
      setEcken(null);
      setSelbstErkannt(false);
      onFehler("");
      window.setTimeout(() => {
        try {
          const gefunden = erkenneDokument(geladen);
          if (gefunden) {
            setEcken(gefunden);
            setSelbstErkannt(true);
          } else {
            setEcken(standardEcken(geladen.naturalWidth, geladen.naturalHeight));
            setSelbstErkannt(false);
          }
        } catch {
          setEcken(standardEcken(geladen.naturalWidth, geladen.naturalHeight));
          setSelbstErkannt(false);
        } finally {
          setArbeitet("");
        }
      }, 30);
    } catch {
      setArbeitet("");
      onFehler("Das Foto ließ sich nicht lesen.");
    }
  }

  function erneutErkennen() {
    if (!bild) return;
    setArbeitet("Beleg wird gesucht …");
    window.setTimeout(() => {
      try {
        const gefunden = erkenneDokument(bild);
        setEcken(gefunden || standardEcken(bild.naturalWidth, bild.naturalHeight));
        setSelbstErkannt(Boolean(gefunden));
      } catch {
        setEcken(standardEcken(bild.naturalWidth, bild.naturalHeight));
        setSelbstErkannt(false);
      } finally {
        setArbeitet("");
      }
    }, 30);
  }

  async function seiteUebernehmen() {
    if (!bild || !ecken) return;
    setArbeitet("Seite wird zugeschnitten …");
    try {
      await new Promise((r) => window.setTimeout(r, 30));
      const canvas = perspektiveKorrigieren(bild, eckenSortieren(ecken));
      aufhellen(canvas);
      const jpeg = await canvasZuJpeg(canvas);
      const id = seiteId;
      setSeiteId(id + 1);
      setSeiten((bisher) => [...bisher, { id, jpeg, vorschau: URL.createObjectURL(jpeg) }]);
      fotoVerwerfen();
      onFehler("");
    } catch {
      onFehler("Zuschneiden fehlgeschlagen.");
    } finally {
      setArbeitet("");
    }
  }

  function fotoVerwerfen() {
    setBild(null);
    setBildUrl((alt) => {
      if (alt) URL.revokeObjectURL(alt);
      return "";
    });
    setEcken(null);
  }

  function seiteEntfernen(id: number) {
    setSeiten((bisher) => {
      const rest = bisher.filter((seite) => seite.id !== id);
      const weg = bisher.find((seite) => seite.id === id);
      if (weg) URL.revokeObjectURL(weg.vorschau);
      return rest;
    });
  }

  async function importieren() {
    if (!seiten.length || arbeitet) return;
    setArbeitet(seiten.length > 1 ? "PDF wird gebaut und importiert …" : "Seite wird importiert …");
    try {
      const pdf = await jpegsZuPdf(seiten.map((seite) => seite.jpeg));
      const stempel = new Date().toISOString().slice(0, 16).replace("T", "-").replace(":", "");
      const antwort = await dateiSenden<{ beleg_id: number }>("/api/belege", new File([pdf], `Scan-${stempel}.pdf`, { type: "application/pdf" }), {
        art: "scan",
        quelle: "scan",
      });
      for (const seite of seiten) URL.revokeObjectURL(seite.vorschau);
      setSeiten([]);
      setFertigId(antwort.beleg_id);
      window.dispatchEvent(new CustomEvent("buchhaltung:belege-aktualisiert", { detail: { beleg_id: antwort.beleg_id, art: "scan" } }));
      onFehler("");
    } catch (exc) {
      onFehler(exc instanceof ApiFehler ? exc.message : "Import fehlgeschlagen.");
    } finally {
      setArbeitet("");
    }
  }

  function eckeZiehen(index: number, clientX: number, clientY: number, svg: SVGSVGElement) {
    if (!bild || !ecken) return;
    const rect = svg.getBoundingClientRect();
    const x = ((clientX - rect.left) / rect.width) * bild.naturalWidth;
    const y = ((clientY - rect.top) / rect.height) * bild.naturalHeight;
    setEcken((bisher) => {
      if (!bisher) return bisher;
      const neu = bisher.slice() as Viereck;
      neu[index] = {
        x: Math.min(bild.naturalWidth, Math.max(0, x)),
        y: Math.min(bild.naturalHeight, Math.max(0, y)),
      };
      return neu;
    });
  }

  return (
    <div className="scan-seite">
      <h1>Scannen</h1>
      {fertigId !== null && (
        <p className="scan-fertig">
          Scan als Beleg importiert.{" "}
          <button type="button" className="secondary" onClick={() => gehe("/belege/" + fertigId)}>
            In Belegbearbeitung öffnen
          </button>
        </p>
      )}
      {!bild && (
        <div className="card">
          <p className="hinweis">Beleg flach hinlegen, gerade von oben fotografieren. Die Umrisse werden automatisch gesucht.</p>
          <div className="actions scan-knöpfe">
            <button type="button" onClick={() => kamera.current?.click()}>
              Fotografieren
            </button>
            <button type="button" className="secondary" onClick={() => auswahl.current?.click()}>
              Bild wählen
            </button>
          </div>
          <input
            ref={kamera}
            type="file"
            accept="image/*"
            capture="environment"
            style={{ display: "none" }}
            onChange={(event) => {
              void fotoNehmen(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
          <input
            ref={auswahl}
            type="file"
            accept="image/*"
            style={{ display: "none" }}
            onChange={(event) => {
              void fotoNehmen(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
        </div>
      )}
      {arbeitet && (
        <p className="hinweis" role="status">
          {arbeitet}
        </p>
      )}
      {bild && ecken && (
        <div className="card">
          <p className="hinweis">{selbstErkannt ? "Umriss erkannt — Ecken bei Bedarf an den Punkten nachziehen." : "Kein Umriss gefunden — Ecken an den Punkten selbst setzen."}</p>
          <div className="scan-rahmen">
            <img src={bildUrl} alt="Belegfoto" className="scan-foto" draggable={false} />
            <svg
              className="scan-svg"
              viewBox={`0 0 ${bild.naturalWidth} ${bild.naturalHeight}`}
              onPointerMove={(event) => {
                if (zugId.current !== null) eckeZiehen(zugId.current, event.clientX, event.clientY, event.currentTarget);
              }}
              onPointerUp={() => (zugId.current = null)}
              onPointerCancel={() => (zugId.current = null)}
            >
              <polygon points={ecken.map((p) => `${p.x},${p.y}`).join(" ")} className="scan-polygon" />
              {ecken.map((p, i) => (
                <circle
                  key={i}
                  cx={p.x}
                  cy={p.y}
                  r={Math.max(bild.naturalWidth, bild.naturalHeight) * 0.02}
                  className="scan-punkt"
                  onPointerDown={(event) => {
                    event.currentTarget.setPointerCapture(event.pointerId);
                    zugId.current = i;
                  }}
                />
              ))}
            </svg>
          </div>
          <div className="actions scan-knöpfe">
            <button type="button" disabled={Boolean(arbeitet)} onClick={() => void seiteUebernehmen()}>
              Zuschneiden & übernehmen
            </button>
            <button type="button" className="secondary" disabled={Boolean(arbeitet)} onClick={erneutErkennen}>
              Erneut suchen
            </button>
            <button type="button" className="secondary" disabled={Boolean(arbeitet)} onClick={fotoVerwerfen}>
              Verwerfen
            </button>
          </div>
        </div>
      )}
      {seiten.length > 0 && (
        <div className="card">
          <h2>
            Seiten ({seiten.length} {seiten.length === 1 ? "Seite" : "Seiten"})
          </h2>
          <div className="scan-seiten">
            {seiten.map((seite, index) => (
              <figure key={seite.id} className="scan-daumen">
                    <img src={seite.vorschau} alt={`Seite ${index + 1}`} />
                <figcaption>
                  Seite {index + 1} <button type="button" className="secondary" onClick={() => seiteEntfernen(seite.id)}>Entfernen</button>
                </figcaption>
              </figure>
            ))}
          </div>
          <div className="actions scan-knöpfe">
            <button type="button" disabled={Boolean(arbeitet)} onClick={() => kamera.current?.click()}>
              Weitere Seite
            </button>
            <button type="button" className="secondary" disabled={Boolean(arbeitet)} onClick={() => void importieren()}>
              {seiten.length === 1 ? "Als Beleg importieren" : `Als PDF mit ${seiten.length} Seiten importieren`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
