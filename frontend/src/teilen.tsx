import { useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";

export function Teilung({ links, rechts, start = 55 }: { links: ReactNode; rechts: ReactNode; start?: number }) {
  const [breite, setBreite] = useState(start);
  const kasten = useRef<HTMLDivElement>(null);

  function ziehen(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const ursprung = event.clientX;
    const anfang = breite;
    const gesamt = kasten.current?.getBoundingClientRect().width || 1;
    function bewegen(ev: PointerEvent) {
      const delta = ((ev.clientX - ursprung) / gesamt) * 100;
      setBreite(Math.min(78, Math.max(22, anfang + delta)));
    }
    function los() {
      window.removeEventListener("pointermove", bewegen);
      window.removeEventListener("pointerup", los);
    }
    window.addEventListener("pointermove", bewegen);
    window.addEventListener("pointerup", los);
  }

  return (
    <div className="teilung" ref={kasten}>
      <div className="teilung-pane" style={{ width: `${breite}%` }}>{links}</div>
      <div className="trenner" role="separator" aria-orientation="vertical" aria-label="Teiler" onPointerDown={ziehen} />
      <div className="teilung-rest">{rechts}</div>
    </div>
  );
}
