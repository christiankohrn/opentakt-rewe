import { useEffect, useState } from "react";
import { getDocument, GlobalWorkerOptions } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

GlobalWorkerOptions.workerSrc = workerUrl;

export function PdfVorschau({ url, titel }: { url: string; titel: string }) {
  const [seiten, setSeiten] = useState<string[]>([]);
  const [fehler, setFehler] = useState("");
  const [laden, setLaden] = useState(true);

  useEffect(() => {
    let abbruch = false;
    setSeiten([]);
    setFehler("");
    setLaden(true);
    (async () => {
      const antwort = await fetch(url, { credentials: "include" });
      if (!antwort.ok) throw new Error("Vorschau nicht geladen.");
      const pdf = await getDocument({ data: await antwort.arrayBuffer() }).promise;
      const bilder: string[] = [];
      for (let nummer = 1; nummer <= pdf.numPages; nummer += 1) {
        const seite = await pdf.getPage(nummer);
        const ansicht = seite.getViewport({ scale: 1.5 });
        const flaeche = document.createElement("canvas");
        flaeche.width = ansicht.width;
        flaeche.height = ansicht.height;
        const context = flaeche.getContext("2d");
        if (!context) throw new Error("Vorschau nicht gezeichnet.");
        await seite.render({ canvasContext: context, viewport: ansicht }).promise;
        bilder.push(flaeche.toDataURL("image/png"));
      }
      if (!abbruch) {
        setSeiten(bilder);
        setLaden(false);
      }
    })().catch((exc: unknown) => {
      if (!abbruch) {
        setLaden(false);
        setFehler(exc instanceof Error ? exc.message : "Vorschau nicht geladen.");
      }
    });
    return () => { abbruch = true; };
  }, [url]);

  return (
    <div className="pdf-vorschau">
      {laden && !fehler && <div className="lade-mitte" role="status"><span className="kreis" aria-label="Laden" /></div>}
      {fehler && <p className="fehler">{fehler}</p>}
      {seiten.map((src, index) => (
        <img
          key={index}
          className="pdf-seite"
          src={src}
          alt={`${titel}, Seite ${index + 1}`}
          draggable={false}
          onDragStart={(event) => event.preventDefault()}
        />
      ))}
    </div>
  );
}

export function DateiLink({ url }: { url: string }) {
  return <a className="button datei-link" href={url} target="_blank" rel="noreferrer" draggable={false}>Datei öffnen</a>;
}

export function LokaleDateiVorschau({ datei }: { datei: File }) {
  const [url, setUrl] = useState("");

  useEffect(() => {
    const objektUrl = URL.createObjectURL(datei);
    setUrl(objektUrl);
    return () => URL.revokeObjectURL(objektUrl);
  }, [datei]);

  if (!url) return null;
  const bild = /\.(jpe?g|png|gif|webp)$/i.test(datei.name) || datei.type.startsWith("image/");
  const pdf = /\.pdf$/i.test(datei.name) || datei.type === "application/pdf";
  return (
    <div className="vorschau-box">
      {bild && <img className="vorschau-bild" src={url} alt={datei.name} draggable={false} onDragStart={(event) => event.preventDefault()} />}
      {pdf && <PdfVorschau url={url} titel={datei.name} />}
      {!bild && !pdf && <p className="hinweis vorschau-mitte">{datei.name}</p>}
      <DateiLink url={url} />
    </div>
  );
}
