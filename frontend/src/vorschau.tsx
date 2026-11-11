import { useEffect, useState } from "react";
import { ApiFehler, api, dateiSenden } from "./api";

type VorschauInfo = {
  art: "pdf" | "bild" | "text" | "datei";
  seiten: number;
  version?: string;
  text?: string;
};

type LokaleVorschauInfo = {
  art: "pdf" | "bild" | "text" | "datei";
  gesamt: number;
  seiten: string[];
  text?: string;
};

function vorschauEndpunkte(url: string): { infoUrl: string; seiteUrl: (seite: number, version?: string) => string } | null {
  const rechnung = /^\/api\/rechnungen\/(\d+)\/vorschau(\?.*)?$/.exec(url);
  if (rechnung) {
    const id = rechnung[1];
    const query = rechnung[2] || "";
    return {
      infoUrl: `/api/rechnungen/${id}/vorschau-info${query}`,
      seiteUrl: (seite) => `/api/rechnungen/${id}/vorschau-seite/${seite}${query}`,
    };
  }
  const beleg = /^\/api\/belege\/(\d+)\/datei(\?.*)?$/.exec(url);
  if (beleg) {
    const id = beleg[1];
    return {
      infoUrl: `/api/belege/${id}/vorschau`,
      seiteUrl: (seite, version) => `/api/belege/${id}/seite/${seite}${version ? `?v=${encodeURIComponent(version)}` : ""}`,
    };
  }
  return null;
}

export function PdfVorschau({ url, titel }: { url: string; titel: string }) {
  const [info, setInfo] = useState<VorschauInfo | null>(null);
  const [fehler, setFehler] = useState("");
  const [laden, setLaden] = useState(true);
  const [ersteFertig, setErsteFertig] = useState(false);

  const endpunkte = vorschauEndpunkte(url);

  useEffect(() => {
    let abbruch = false;
    setInfo(null);
    setFehler("");
    setLaden(true);
    setErsteFertig(false);

    if (!endpunkte) {
      setLaden(false);
      return;
    }

    api<VorschauInfo>(endpunkte.infoUrl)
      .then((daten) => {
        if (abbruch) return;
        setInfo(daten);
        setLaden(false);
        if (daten.art !== "pdf" || daten.seiten === 0) {
          setErsteFertig(true);
        }
      })
      .catch((exc: unknown) => {
        if (abbruch) return;
        setLaden(false);
        setErsteFertig(true);
        setFehler(exc instanceof ApiFehler ? exc.message : "Vorschau nicht geladen.");
      });

    return () => {
      abbruch = true;
    };
  }, [url]);

  if (!endpunkte) {
    return (
      <div className="pdf-vorschau">
        <p className="hinweis vorschau-mitte">{titel}</p>
      </div>
    );
  }

  return (
    <div className="pdf-vorschau">
      {(laden || (info?.art === "pdf" && !ersteFertig)) && !fehler && (
        <div className="lade-mitte" role="status">
          <span className="kreis" aria-label="Laden" />
        </div>
      )}
      {fehler && <p className="fehler">{fehler}</p>}
      {info?.art === "pdf" &&
        Array.from({ length: info.seiten }, (_, index) => {
          const seite = index + 1;
          return (
            <img
              key={`${url}-${seite}`}
              className="pdf-seite"
              src={endpunkte.seiteUrl(seite, info.version)}
              alt={`${titel}, Seite ${seite}`}
              loading={seite === 1 ? "eager" : "lazy"}
              decoding="async"
              draggable={false}
              onLoad={() => {
                if (seite === 1) setErsteFertig(true);
              }}
              onError={() => {
                if (seite === 1) {
                  setErsteFertig(true);
                  setFehler("Seite konnte nicht geladen werden.");
                }
              }}
              onDragStart={(event) => event.preventDefault()}
            />
          );
        })}
      {info?.art === "bild" && (
        <img
          className="vorschau-bild"
          src={url}
          alt={titel}
          decoding="async"
          draggable={false}
          onDragStart={(event) => event.preventDefault()}
        />
      )}
      {info?.art === "text" && <pre className="text-vorschau">{info.text || "Leere Datei."}</pre>}
      {info?.art === "datei" && <p className="hinweis vorschau-mitte">{titel}</p>}
    </div>
  );
}

export function DateiLink({ url }: { url: string }) {
  return (
    <a className="button secondary kompakt-knopf datei-link" href={url} target="_blank" rel="noreferrer" draggable={false}>
      Originaldatei öffnen
    </a>
  );
}

export function LokaleDateiVorschau({ datei }: { datei: File }) {
  const [url, setUrl] = useState("");
  const [info, setInfo] = useState<LokaleVorschauInfo | null>(null);
  const [laden, setLaden] = useState(false);

  const bild = /\.(jpe?g|png|gif|webp)$/i.test(datei.name) || datei.type.startsWith("image/");

  useEffect(() => {
    const objektUrl = URL.createObjectURL(datei);
    setUrl(objektUrl);
    return () => URL.revokeObjectURL(objektUrl);
  }, [datei]);

  useEffect(() => {
    if (bild) {
      setInfo(null);
      setLaden(false);
      return;
    }
    let abbruch = false;
    setInfo(null);
    setLaden(true);
    dateiSenden<LokaleVorschauInfo>("/api/belege/vorschau-lokal", datei, {})
      .then((daten) => {
        if (!abbruch) {
          setInfo(daten);
          setLaden(false);
        }
      })
      .catch(() => {
        if (!abbruch) {
          setInfo({ art: "datei", gesamt: 0, seiten: [] });
          setLaden(false);
        }
      });
    return () => {
      abbruch = true;
    };
  }, [datei, bild]);

  if (!url) return null;

  return (
    <div className="vorschau-box">
      {bild ? (
        <img className="vorschau-bild" src={url} alt={datei.name} draggable={false} onDragStart={(event) => event.preventDefault()} />
      ) : (
        <div className="pdf-vorschau">
          {laden && (
            <div className="lade-mitte" role="status">
              <span className="kreis" aria-label="Laden" />
            </div>
          )}
          {info?.art === "pdf" && (
            <>
              {info.seiten.map((src, index) => (
                <img
                  key={index}
                  className="pdf-seite"
                  src={src}
                  alt={`${datei.name}, Seite ${index + 1}`}
                  draggable={false}
                  onDragStart={(event) => event.preventDefault()}
                />
              ))}
              {info.gesamt > info.seiten.length && (
                <p className="hinweis" style={{ textAlign: "center", margin: "0.4rem 0" }}>
                  Vorschau der ersten {info.seiten.length} von {info.gesamt} Seiten
                </p>
              )}
            </>
          )}
          {info?.art === "text" && <pre className="text-vorschau">{info.text}</pre>}
          {info?.art === "datei" && !laden && <p className="hinweis vorschau-mitte">{datei.name}</p>}
        </div>
      )}
      <DateiLink url={url} />
    </div>
  );
}
