import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";

export function gehe(href: string) {
  if (location.pathname === href) {
    window.dispatchEvent(new PopStateEvent("popstate"));
    return;
  }
  history.pushState(null, "", href);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function LinkIntern({
  href,
  className,
  title,
  children,
}: {
  href: string;
  className?: string;
  title?: string;
  children: ReactNode;
}) {
  function klick(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    gehe(href);
  }
  return <a href={href} className={className} title={title} aria-label={title} onClick={klick}>{children}</a>;
}

export function AktionsMenue({
  titel = "Weitere Aktionen",
  kompakt = false,
  resetKey,
  children,
}: {
  titel?: string;
  kompakt?: boolean;
  resetKey?: string | number | null;
  children: ReactNode;
}) {
  const [offen, setOffen] = useState(false);
  const kasten = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setOffen(false);
  }, [resetKey]);

  useEffect(() => {
    if (!offen) return;
    function ausserhalb(event: PointerEvent) {
      if (!kasten.current?.contains(event.target as Node)) {
        setOffen(false);
      }
    }
    function taste(event: KeyboardEvent) {
      if (event.key === "Escape") setOffen(false);
    }
    document.addEventListener("pointerdown", ausserhalb);
    document.addEventListener("keydown", taste);
    return () => {
      document.removeEventListener("pointerdown", ausserhalb);
      document.removeEventListener("keydown", taste);
    };
  }, [offen]);

  return (
    <div className="mehr-menue" ref={kasten}>
      <button
        type="button"
        className={`secondary ${kompakt ? "kompakt-knopf" : ""}`}
        aria-expanded={offen}
        aria-haspopup="menu"
        onClick={() => setOffen((bisher) => !bisher)}
      >
        {titel} ▾
      </button>
      {offen && (
        <div className="mehr-liste" role="menu" onClick={() => setOffen(false)}>
          {children}
        </div>
      )}
    </div>
  );
}

export function routeLesen(): { seite: string; id: number | null; neu: boolean } {
  const teile = location.pathname.replace(/\/+$/, "").split("/").filter(Boolean);
  const roh = teile[0] || "rechnungen";
  const seite = roh === "optionen" ? "einstellungen" : roh;
  const bekannt = new Set(["rechnungen", "kunden", "belege", "scan", "kontozeilen", "einstellungen", "konto", "passwort-vergessen", "passwort-setzen"]);
  const neu = teile[1] === "neu";
  const id = !neu && teile[1] && /^\d+$/.test(teile[1]) ? Number(teile[1]) : null;
  return { seite: bekannt.has(seite) ? seite : "rechnungen", id, neu };
}
