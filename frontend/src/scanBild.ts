/* Belegscan: Kantenerkennung, Perspektivkorrektur und PDF-Bau ohne Abhängigkeiten.
   Der Kern arbeitet auf Grauwert-Puffern und ist ohne DOM testbar. */

export type Punkt = { x: number; y: number };
/* Ecken im Uhrzeigersinn: oben-links, oben-rechts, unten-rechts, unten-links. */
export type Viereck = [Punkt, Punkt, Punkt, Punkt];

export function graustufen(rgba: Uint8ClampedArray, breite: number, hoehe: number): Uint8ClampedArray {
  const grau = new Uint8ClampedArray(breite * hoehe);
  for (let i = 0; i < breite * hoehe; i++) {
    grau[i] = (rgba[i * 4] * 77 + rgba[i * 4 + 1] * 150 + rgba[i * 4 + 2] * 29) >> 8;
  }
  return grau;
}

function kastenWeich(eingabe: Uint8ClampedArray, breite: number, hoehe: number, radius: number): Uint8ClampedArray {
  const zwischen = new Float32Array(breite * hoehe);
  const ausgabe = new Uint8ClampedArray(breite * hoehe);
  const fenster = radius * 2 + 1;
  for (let y = 0; y < hoehe; y++) {
    let summe = 0;
    for (let x = -radius; x <= radius; x++) summe += eingabe[y * breite + Math.min(breite - 1, Math.max(0, x))];
    for (let x = 0; x < breite; x++) {
      zwischen[y * breite + x] = summe / fenster;
      summe += eingabe[y * breite + Math.min(breite - 1, x + radius + 1)] - eingabe[y * breite + Math.max(0, x - radius)];
    }
  }
  for (let x = 0; x < breite; x++) {
    let summe = 0;
    for (let y = -radius; y <= radius; y++) summe += zwischen[Math.min(hoehe - 1, Math.max(0, y)) * breite + x];
    for (let y = 0; y < hoehe; y++) {
      ausgabe[y * breite + x] = summe / fenster;
      summe += zwischen[Math.min(hoehe - 1, y + radius + 1) * breite + x] - zwischen[Math.max(0, y - radius) * breite + x];
    }
  }
  return ausgabe;
}

/* Kantenstärke (Sobel), normiert auf 0–255. */
export function sobelKanten(grau: Uint8ClampedArray, breite: number, hoehe: number): Uint8ClampedArray {
  const ausgabe = new Uint8ClampedArray(breite * hoehe);
  let max = 1;
  const staerke = new Float32Array(breite * hoehe);
  for (let y = 1; y + 1 < hoehe; y++) {
    for (let x = 1; x + 1 < breite; x++) {
      const i = y * breite + x;
      const gx =
        -grau[i - breite - 1] - 2 * grau[i - 1] - grau[i + breite - 1] + grau[i - breite + 1] + 2 * grau[i + 1] + grau[i + breite + 1];
      const gy =
        -grau[i - breite - 1] - 2 * grau[i - breite] - grau[i - breite + 1] + grau[i + breite - 1] + 2 * grau[i + breite] + grau[i + breite + 1];
      const wert = Math.abs(gx) + Math.abs(gy);
      staerke[i] = wert;
      if (wert > max) max = wert;
    }
  }
  for (let i = 0; i < staerke.length; i++) ausgabe[i] = (staerke[i] * 255) / max;
  return ausgabe;
}

/* Schließt kleine Lücken im Kantenbild (3x3-Dilatation, n Durchgänge). */
function dilatieren(binaer: Uint8Array, breite: number, hoehe: number, durchgaenge: number): Uint8Array {
  let quelle = binaer;
  for (let n = 0; n < durchgaenge; n++) {
    const ziel = new Uint8Array(breite * hoehe);
    for (let y = 0; y < hoehe; y++) {
      for (let x = 0; x < breite; x++) {
        let gesetzt = 0;
        for (let dy = -1; dy <= 1 && !gesetzt; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            const nx = x + dx;
            const ny = y + dy;
            if (nx >= 0 && ny >= 0 && nx < breite && ny < hoehe && quelle[ny * breite + nx]) {
              gesetzt = 1;
              break;
            }
          }
        }
        ziel[y * breite + x] = gesetzt;
      }
    }
    quelle = ziel;
  }
  return quelle;
}

export function otsuSchwelle(grau: Uint8ClampedArray): number {
  const hist = new Uint32Array(256);
  for (let i = 0; i < grau.length; i++) hist[grau[i]]++;
  const gesamt = grau.length;
  let summe = 0;
  for (let t = 0; t < 256; t++) summe += t * hist[t];
  let summeHinten = 0;
  let gewichtHinten = 0;
  let beste = 0;
  let bestWert = -1;
  for (let t = 0; t < 256; t++) {
    gewichtHinten += hist[t];
    if (!gewichtHinten) continue;
    const gewichtVorne = gesamt - gewichtHinten;
    if (!gewichtVorne) break;
    summeHinten += t * hist[t];
    const mittelHinten = summeHinten / gewichtHinten;
    const mittelVorne = (summe - summeHinten) / gewichtVorne;
    const abstand = mittelHinten - mittelVorne;
    const wert = gewichtHinten * gewichtVorne * abstand * abstand;
    if (wert > bestWert) {
      bestWert = wert;
      beste = t;
    }
  }
  return beste;
}

function binaerBild(grau: Uint8ClampedArray, breite: number, hoehe: number): Uint8Array {
  const schwelle = otsuSchwelle(grau);
  const binaer = new Uint8Array(breite * hoehe);
  for (let i = 0; i < grau.length; i++) binaer[i] = grau[i] > schwelle ? 1 : 0;
  /* Der Beleg ist die helle Fläche: Ist der Rand mehrheitlich hell, umkehren. */
  let rand = 0;
  let hell = 0;
  for (let x = 0; x < breite; x += 2) {
    for (const y of [0, 1, hoehe - 2, hoehe - 1]) {
      rand++;
      hell += binaer[y * breite + x];
    }
  }
  for (let y = 0; y < hoehe; y += 2) {
    for (const x of [0, 1, breite - 2, breite - 1]) {
      rand++;
      hell += binaer[y * breite + x];
    }
  }
  if (hell * 2 > rand) {
    for (let i = 0; i < binaer.length; i++) binaer[i] = binaer[i] ? 0 : 1;
  }
  return binaer;
}

/* Größte zusammenhängende Fläche, grob abgetastet für Tempo. */
function groessteFlaeche(binaer: Uint8Array, breite: number, hoehe: number): Punkt[] {
  const besucht = new Uint8Array(breite * hoehe);
  const schritt = 2;
  let beste: Punkt[] = [];
  const stapel: number[] = [];
  for (let start = 0; start < binaer.length; start++) {
    if (!binaer[start] || besucht[start]) continue;
    const punkte: Punkt[] = [];
    stapel.push(start);
    besucht[start] = 1;
    while (stapel.length) {
      const at = stapel.pop() as number;
      const x = at % breite;
      const y = (at / breite) | 0;
      if (x % schritt === 0 && y % schritt === 0) punkte.push({ x, y });
      if (x > 0 && binaer[at - 1] && !besucht[at - 1]) {
        besucht[at - 1] = 1;
        stapel.push(at - 1);
      }
      if (x + 1 < breite && binaer[at + 1] && !besucht[at + 1]) {
        besucht[at + 1] = 1;
        stapel.push(at + 1);
      }
      if (y > 0 && binaer[at - breite] && !besucht[at - breite]) {
        besucht[at - breite] = 1;
        stapel.push(at - breite);
      }
      if (y + 1 < hoehe && binaer[at + breite] && !besucht[at + breite]) {
        besucht[at + breite] = 1;
        stapel.push(at + breite);
      }
    }
    if (punkte.length > beste.length) beste = punkte;
  }
  return beste;
}

/* Konvexe Hülle (Andrew), sortiert gegen den Uhrzeigersinn. */
export function konvexeHuelle(punkte: Punkt[]): Punkt[] {
  const sortiert = punkte.slice().sort((a, b) => (a.x === b.x ? a.y - b.y : a.x - b.x));
  if (sortiert.length < 3) return sortiert;
  const kreuz = (o: Punkt, a: Punkt, b: Punkt) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const unten: Punkt[] = [];
  const oben: Punkt[] = [];
  for (const p of sortiert) {
    while (unten.length >= 2 && kreuz(unten[unten.length - 2], unten[unten.length - 1], p) <= 0) unten.pop();
    unten.push(p);
  }
  for (let i = sortiert.length - 1; i >= 0; i--) {
    const p = sortiert[i];
    while (oben.length >= 2 && kreuz(oben[oben.length - 2], oben[oben.length - 1], p) <= 0) oben.pop();
    oben.push(p);
  }
  unten.pop();
  oben.pop();
  return unten.concat(oben);
}

export function douglasPeucker(punkte: Punkt[], epsilon: number): Punkt[] {
  if (punkte.length < 3) return punkte.slice();
  const abstand = (p: Punkt, a: Punkt, b: Punkt) => {
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const nenner = Math.hypot(dx, dy) || 1;
    return Math.abs(dy * p.x - dx * p.y + b.x * a.y - b.y * a.x) / nenner;
  };
  const behalten = new Array<boolean>(punkte.length).fill(false);
  behalten[0] = true;
  behalten[punkte.length - 1] = true;
  const stapel: Array<[number, number]> = [[0, punkte.length - 1]];
  while (stapel.length) {
    const [von, bis] = stapel.pop() as [number, number];
    let weit = 0;
    let wo = -1;
    for (let i = von + 1; i < bis; i++) {
      const d = abstand(punkte[i], punkte[von], punkte[bis]);
      if (d > weit) {
        weit = d;
        wo = i;
      }
    }
    if (weit > epsilon && wo > 0) {
      behalten[wo] = true;
      stapel.push([von, wo], [wo, bis]);
    }
  }
  return punkte.filter((_, i) => behalten[i]);
}

function umfang(punkte: Punkt[]): number {
  let summe = 0;
  for (let i = 0; i < punkte.length; i++) {
    const a = punkte[i];
    const b = punkte[(i + 1) % punkte.length];
    summe += Math.hypot(b.x - a.x, b.y - a.y);
  }
  return summe;
}

function flaeche(punkte: Punkt[]): number {
  let summe = 0;
  for (let i = 0; i < punkte.length; i++) {
    const a = punkte[i];
    const b = punkte[(i + 1) % punkte.length];
    summe += a.x * b.y - b.x * a.y;
  }
  return Math.abs(summe) / 2;
}

function istViereck(punkte: Punkt[]): boolean {
  if (punkte.length !== 4) return false;
  let vorzeichen = 0;
  for (let i = 0; i < 4; i++) {
    const a = punkte[i];
    const b = punkte[(i + 1) % 4];
    const c = punkte[(i + 2) % 4];
    const kreuz = (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x);
    const norm = Math.hypot(b.x - a.x, b.y - a.y) * Math.hypot(c.x - b.x, c.y - b.y) || 1;
    const winkel = Math.acos(Math.min(1, Math.max(-1, ((a.x - b.x) * (c.x - b.x) + (a.y - b.y) * (c.y - b.y)) / norm)));
    const grad = (winkel * 180) / Math.PI;
    if (grad < 55 || grad > 125) return false;
    const s = Math.sign(kreuz);
    if (s !== 0) {
      if (vorzeichen !== 0 && s !== vorzeichen) return false;
      vorzeichen = s;
    }
  }
  return true;
}

/* Ecken sortieren: oben-links zuerst, dann im Uhrzeigersinn. */
export function eckenSortieren(punkte: Punkt[]): Viereck {
  const mitte = {
    x: punkte.reduce((s, p) => s + p.x, 0) / punkte.length,
    y: punkte.reduce((s, p) => s + p.y, 0) / punkte.length,
  };
  const imUhrzeigersinn = punkte
    .slice()
    .sort((a, b) => Math.atan2(a.y - mitte.y, a.x - mitte.x) - Math.atan2(b.y - mitte.y, b.x - mitte.x));
  let start = 0;
  let best = Infinity;
  for (let i = 0; i < imUhrzeigersinn.length; i++) {
    const p = imUhrzeigersinn[i];
    const wert = p.y * 2 + p.x / 1000;
    if (wert < best) {
      best = wert;
      start = i;
    }
  }
  const gedreht = imUhrzeigersinn.slice(start).concat(imUhrzeigersinn.slice(0, start));
  return [gedreht[0], gedreht[1], gedreht[2], gedreht[3]];
}

/* Douglas-Peucker für geschlossene Konturen: am fernsten Punkt auftrennen. */
function douglasPeuckerGeschlossen(huelle: Punkt[], epsilon: number): Punkt[] {
  let weit = -1;
  let wo = 0;
  for (let i = 1; i < huelle.length; i++) {
    const d = Math.hypot(huelle[i].x - huelle[0].x, huelle[i].y - huelle[0].y);
    if (d > weit) {
      weit = d;
      wo = i;
    }
  }
  const ketteA = huelle.slice(0, wo + 1);
  const ketteB = huelle.slice(wo).concat([huelle[0]]);
  const teilA = douglasPeucker(ketteA, epsilon);
  const teilB = douglasPeucker(ketteB, epsilon);
  return teilA.concat(teilB.slice(1, -1));
}

function viereckAusBinaer(binaer: Uint8Array, breite: number, hoehe: number): Viereck | null {
  const flaechePx = groessteFlaeche(binaer, breite, hoehe);
  const bildFlaeche = (breite * hoehe) / 4;
  if (flaechePx.length < bildFlaeche * 0.04 || flaechePx.length > bildFlaeche * 0.96) return null;
  const huelle = konvexeHuelle(flaechePx);
  if (huelle.length < 4) return null;
  const u = umfang(huelle);
  for (const anteil of [0.005, 0.01, 0.02, 0.03, 0.05, 0.08]) {
    const ecken = douglasPeuckerGeschlossen(huelle, u * anteil);
    if (istViereck(ecken) && flaeche(ecken) > bildFlaeche * 0.03) return eckenSortieren(ecken);
  }
  return null;
}

export function erkenneViereckAusGrau(grau: Uint8ClampedArray, breite: number, hoehe: number): Viereck | null {
  const weich = kastenWeich(grau, breite, hoehe, 2);
  /* 1. Versuch: helle Papierfläche direkt per Schwelle. */
  const flaeche = viereckAusBinaer(binaerBild(weich, breite, hoehe), breite, hoehe);
  if (flaeche) return flaeche;
  /* 2. Versuch: Umriss über Kanten (robuster bei Schatten und Verlauf). */
  const kanten = sobelKanten(weich, breite, hoehe);
  const schwelle = otsuSchwelle(kanten);
  const binaer = new Uint8Array(breite * hoehe);
  for (let i = 0; i < kanten.length; i++) binaer[i] = kanten[i] > schwelle ? 1 : 0;
  return viereckAusBinaer(dilatieren(binaer, breite, hoehe, 2), breite, hoehe);
}

/* ---------- DOM-Hüllen ---------- */

export function bildLaden(datei: File): Promise<HTMLImageElement> {
  return new Promise((resolve, ablehnen) => {
    const url = URL.createObjectURL(datei);
    const bild = new Image();
    bild.onload = () => resolve(bild);
    bild.onerror = () => {
      URL.revokeObjectURL(url);
      ablehnen(new Error("Bild ließ sich nicht lesen."));
    };
    bild.src = url;
  });
}

function verkleinern(bild: HTMLImageElement, maxKante: number): { canvas: HTMLCanvasElement; massstab: number } {
  const massstab = Math.min(1, maxKante / Math.max(bild.naturalWidth, bild.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bild.naturalWidth * massstab));
  canvas.height = Math.max(1, Math.round(bild.naturalHeight * massstab));
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new Error("Canvas steht nicht bereit.");
  ctx.drawImage(bild, 0, 0, canvas.width, canvas.height);
  return { canvas, massstab };
}

export function erkenneDokument(bild: HTMLImageElement, maxKante = 800): Viereck | null {
  const { canvas, massstab } = verkleinern(bild, maxKante);
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  const daten = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const grau = graustufen(daten.data, canvas.width, canvas.height);
  const gefunden = erkenneViereckAusGrau(grau, canvas.width, canvas.height);
  if (!gefunden) return null;
  return gefunden.map((p) => ({ x: p.x / massstab, y: p.y / massstab })) as Viereck;
}

/* Löst ein kleines lineares Gleichungssystem (Gauß). */
function loeseGleichung(a: number[][], b: number[]): number[] {
  const n = b.length;
  const m = a.map((zeile, i) => zeile.concat([b[i]]));
  for (let spalte = 0; spalte < n; spalte++) {
    let pivot = spalte;
    for (let zeile = spalte + 1; zeile < n; zeile++) {
      if (Math.abs(m[zeile][spalte]) > Math.abs(m[pivot][spalte])) pivot = zeile;
    }
    const tmp = m[spalte];
    m[spalte] = m[pivot];
    m[pivot] = tmp;
    const teiler = m[spalte][spalte] || 1e-9;
    for (let k = spalte; k <= n; k++) m[spalte][k] /= teiler;
    for (let zeile = 0; zeile < n; zeile++) {
      if (zeile === spalte) continue;
      const faktor = m[zeile][spalte];
      for (let k = spalte; k <= n; k++) m[zeile][k] -= faktor * m[spalte][k];
    }
  }
  return m.map((zeile) => zeile[n]);
}

/* Homographie Ziel → Quelle aus vier Punktpaaren. */
function homographie(quadrat: Viereck, ziel: Viereck): number[] {
  const a: number[][] = [];
  const b: number[] = [];
  for (let i = 0; i < 4; i++) {
    const [x, y] = [quadrat[i].x, quadrat[i].y];
    const [u, v] = [ziel[i].x, ziel[i].y];
    a.push([x, y, 1, 0, 0, 0, -u * x, -u * y]);
    b.push(u);
    a.push([0, 0, 0, x, y, 1, -v * x, -v * y]);
    b.push(v);
  }
  return loeseGleichung(a, b);
}

export function perspektiveKorrigieren(bild: HTMLImageElement, ecken: Viereck, zielBreite = 1240): HTMLCanvasElement {
  const [tl, tr, br, bl] = eckenSortieren(ecken);
  const oben = Math.hypot(tr.x - tl.x, tr.y - tl.y);
  const unten = Math.hypot(br.x - bl.x, br.y - bl.y);
  const links = Math.hypot(bl.x - tl.x, bl.y - tl.y);
  const rechts = Math.hypot(br.x - tr.x, br.y - tr.y);
  const breiteMittel = Math.max(1, (oben + unten) / 2);
  const hoeheMittel = Math.max(1, (links + rechts) / 2);
  const zielHoehe = Math.min(2400, Math.max(600, Math.round((zielBreite * hoeheMittel) / breiteMittel)));
  const quelle = document.createElement("canvas");
  quelle.width = bild.naturalWidth;
  quelle.height = bild.naturalHeight;
  const qctx = quelle.getContext("2d", { willReadFrequently: true });
  if (!qctx) throw new Error("Canvas steht nicht bereit.");
  qctx.drawImage(bild, 0, 0);
  const quellDaten = qctx.getImageData(0, 0, quelle.width, quelle.height);
  const ziel: Viereck = [
    { x: 0, y: 0 },
    { x: zielBreite - 1, y: 0 },
    { x: zielBreite - 1, y: zielHoehe - 1 },
    { x: 0, y: zielHoehe - 1 },
  ];
  const h = homographie(ziel, [tl, tr, br, bl]);
  const canvas = document.createElement("canvas");
  canvas.width = zielBreite;
  canvas.height = zielHoehe;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas steht nicht bereit.");
  const ausgabe = ctx.createImageData(zielBreite, zielHoehe);
  const qd = quellDaten.data;
  const qw = quelle.width;
  const qh = quelle.height;
  for (let y = 0; y < zielHoehe; y++) {
    for (let x = 0; x < zielBreite; x++) {
      const nenner = h[6] * x + h[7] * y + 1;
      const sx = (h[0] * x + h[1] * y + h[2]) / nenner;
      const sy = (h[3] * x + h[4] * y + h[5]) / nenner;
      const x0 = Math.floor(sx);
      const y0 = Math.floor(sy);
      const fx = sx - x0;
      const fy = sy - y0;
      const lesen = (px: number, py: number, kanal: number) => {
        const cx = Math.min(qw - 1, Math.max(0, px));
        const cy = Math.min(qh - 1, Math.max(0, py));
        return qd[(cy * qw + cx) * 4 + kanal];
      };
      const zi = (y * zielBreite + x) * 4;
      for (let k = 0; k < 3; k++) {
        const obenWert = lesen(x0, y0, k) * (1 - fx) + lesen(x0 + 1, y0, k) * fx;
        const untenWert = lesen(x0, y0 + 1, k) * (1 - fx) + lesen(x0 + 1, y0 + 1, k) * fx;
        ausgabe.data[zi + k] = obenWert * (1 - fy) + untenWert * fy;
      }
      ausgabe.data[zi + 3] = 255;
    }
  }
  ctx.putImageData(ausgabe, 0, 0);
  return canvas;
}

/* Hellt den Scan dezent auf (Spreizung zwischen 2-%- und 98-%-Quantil). */
export function aufhellen(canvas: HTMLCanvasElement): void {
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return;
  const daten = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const hist = new Uint32Array(256);
  for (let i = 0; i < daten.data.length; i += 4) {
    const g = (daten.data[i] * 77 + daten.data[i + 1] * 150 + daten.data[i + 2] * 29) >> 8;
    hist[g]++;
  }
  const gesamt = daten.data.length / 4;
  let lo = 0;
  let hi = 255;
  let summe = 0;
  for (let i = 0; i < 256; i++) {
    summe += hist[i];
    if (summe < gesamt * 0.02) lo = i;
  }
  summe = 0;
  for (let i = 255; i >= 0; i--) {
    summe += hist[i];
    if (summe < gesamt * 0.02) hi = i;
  }
  if (hi - lo < 24) return;
  const faktor = 255 / (hi - lo);
  for (let i = 0; i < daten.data.length; i += 4) {
    for (let k = 0; k < 3; k++) {
      daten.data[i + k] = Math.min(255, Math.max(0, (daten.data[i + k] - lo) * faktor));
    }
  }
  ctx.putImageData(daten, 0, 0);
}

export function canvasZuJpeg(canvas: HTMLCanvasElement, qualitaet = 0.85): Promise<Blob> {
  return new Promise((resolve, ablehnen) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : ablehnen(new Error("JPEG ließ sich nicht erzeugen."))), "image/jpeg", qualitaet);
  });
}

function textEncoder(): (text: string) => Uint8Array {
  const encoder = new TextEncoder();
  return (text: string) => encoder.encode(text);
}

/* Exakt große Kopie als Blob-Baustein (teilt keinen Puffer). */
function alsTeil(daten: Uint8Array): Uint8Array<ArrayBuffer> {
  const kopie = new Uint8Array(daten.byteLength);
  kopie.set(daten);
  return kopie;
}

/* Liest Breite/Höhe aus einem JPEG (SOF-Marker). */
export function jpegGroesse(jpeg: Uint8Array): { breite: number; hoehe: number } {
  for (let i = 0; i + 8 < jpeg.length; i++) {
    if (jpeg[i] !== 0xff) continue;
    const marker = jpeg[i + 1];
    if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      return { hoehe: (jpeg[i + 5] << 8) | jpeg[i + 6], breite: (jpeg[i + 7] << 8) | jpeg[i + 8] };
    }
  }
  throw new Error("JPEG-Maße nicht lesbar.");
}

/* Baut aus JPEG-Seiten ein mehrseitiges PDF (reines Einbetten, ohne Umkodieren). */
export async function jpegsZuPdf(seiten: Blob[]): Promise<Blob> {
  if (!seiten.length) throw new Error("Keine Seiten zum Ablegen.");
  const kodieren = textEncoder();
  const teile: BlobPart[] = [];
  const offsets: number[] = [];
  let position = 0;
  const schreiben = (daten: BlobPart) => {
    teile.push(daten);
    position += typeof daten === "string" ? kodieren(daten).length : (daten as Uint8Array).length;
  };
  const objekt = (nummer: number, inhalt: string) => {
    offsets[nummer] = position;
    schreiben(`${nummer} 0 obj\n${inhalt}\nendobj\n`);
  };
  schreiben("%PDF-1.4\n");
  const seitenNummern: number[] = [];
  let nummer = 3;
  for (const seite of seiten) {
    const roh = new Uint8Array(await seite.arrayBuffer());
    const { breite, hoehe } = jpegGroesse(roh);
    const punktBreite = 595;
    const punktHoehe = Math.round((punktBreite * hoehe) / Math.max(1, breite));
    const bildNr = nummer++;
    const inhaltNr = nummer++;
    const seitenNr = nummer++;
    seitenNummern.push(seitenNr);
    offsets[bildNr] = position;
    const kopf = kodieren(
      `${bildNr} 0 obj\n<< /Type /XObject /Subtype /Image /Width ${breite} /Height ${hoehe} ` +
        `/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${roh.length} >>\nstream\n`,
    );
    teile.push(alsTeil(kopf));
    position += kopf.length;
    teile.push(alsTeil(roh));
    position += roh.length;
    schreiben("\nendstream\nendobj\n");
    const zeichnen = `q ${punktBreite} 0 0 ${punktHoehe} 0 0 cm /Bild Do Q`;
    objekt(inhaltNr, `<< /Length ${zeichnen.length} >>\nstream\n${zeichnen}\nendstream`);
    objekt(seitenNr, `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${punktBreite} ${punktHoehe}] /Resources << /XObject << /Bild ${bildNr} 0 R >> >> /Contents ${inhaltNr} 0 R >>`);
  }
  objekt(1, "<< /Type /Catalog /Pages 2 0 R >>");
  objekt(2, `<< /Type /Pages /Kids [${seitenNummern.map((n) => `${n} 0 R`).join(" ")}] /Count ${seitenNummern.length} >>`);
  const xrefStart = position;
  const anzahl = nummer;
  let xref = `xref\n0 ${anzahl}\n0000000000 65535 f \n`;
  for (let i = 1; i < anzahl; i++) xref += `${String(offsets[i]).padStart(10, "0")} 00000 n \n`;
  xref += `trailer\n<< /Size ${anzahl} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`;
  schreiben(xref);
  return new Blob(teile, { type: "application/pdf" });
}
