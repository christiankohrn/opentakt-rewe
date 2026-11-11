/* Linien-Icons im Stil von Opentakt Zeit (24er-Raster, currentColor). */
import type { ReactNode } from "react";

type IconProps = { className?: string };

function Geruest({ className, children }: IconProps & { children: ReactNode }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      {children}
    </svg>
  );
}

export function IconRechnung({ className }: IconProps) {
  return (
    <Geruest className={className}>
      <path d="M6 3h8l4 4v14H6V3z" strokeLinejoin="round" />
      <path d="M14 3v4h4" strokeLinejoin="round" />
      <path d="M9 12h6M9 16h6" strokeLinecap="round" />
    </Geruest>
  );
}

export function IconKunden({ className }: IconProps) {
  return (
    <Geruest className={className}>
      <circle cx="9" cy="8" r="3" />
      <circle cx="16" cy="9" r="2.5" />
      <path d="M3 19c.8-3 3-5 6-5s5.2 2 6 5M14 14c2.2 0 4.2 1.2 5 3.5" strokeLinecap="round" />
    </Geruest>
  );
}

export function IconBeleg({ className }: IconProps) {
  return (
    <Geruest className={className}>
      <path d="M3 13l2.5-8h13L21 13v6H3v-6z" strokeLinejoin="round" />
      <path d="M3 13h5l1.5 2.5h5L16 13h5" strokeLinejoin="round" />
    </Geruest>
  );
}

export function IconScan({ className }: IconProps) {
  return (
    <Geruest className={className}>
      <path d="M4 8V5h3M17 5h3v3M20 16v3h-3M7 20H4v-3" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 12h16" strokeLinecap="round" />
    </Geruest>
  );
}

export function IconKontozeilen({ className }: IconProps) {
  return (
    <Geruest className={className}>
      <path d="M4 19h16" strokeLinecap="round" />
      <path d="M7 16v-5M12 16V8M17 16v-8" strokeLinecap="round" />
    </Geruest>
  );
}

export function IconGear({ className }: IconProps) {
  return (
    <Geruest className={className}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9c.3.7.9 1.2 1.5 1.2H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </Geruest>
  );
}

export function IconBenutzer({ className }: IconProps) {
  return (
    <Geruest className={className}>
      <circle cx="9" cy="8" r="3" />
      <circle cx="16" cy="9" r="2.5" />
      <path d="M3 19c.8-3 3-5 6-5s5.2 2 6 5M14 14c2.2 0 4.2 1.2 5 3.5" strokeLinecap="round" />
    </Geruest>
  );
}

export function IconKonto({ className }: IconProps) {
  return (
    <Geruest className={className}>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20c1-3.5 3.8-5.5 7-5.5s6 2 7 5.5" strokeLinecap="round" />
    </Geruest>
  );
}

export function IconAbmelden({ className }: IconProps) {
  return (
    <Geruest className={className}>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5M21 12H9" strokeLinecap="round" strokeLinejoin="round" />
    </Geruest>
  );
}

export function IconChevronLinks({ className }: IconProps) {
  return (
    <Geruest className={className}>
      <path d="M15 6l-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
    </Geruest>
  );
}

export function IconChevronRechts({ className }: IconProps) {
  return (
    <Geruest className={className}>
      <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
    </Geruest>
  );
}

export function IconSun({ className }: IconProps) {
  return (
    <Geruest className={className}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 3v2M12 19v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M3 12h2M19 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" strokeLinecap="round" />
    </Geruest>
  );
}

export function IconMoon({ className }: IconProps) {
  return (
    <Geruest className={className}>
      <path d="M18 13a7 7 0 1 1-8-9 7 7 0 0 0 8 9z" strokeLinejoin="round" />
    </Geruest>
  );
}
