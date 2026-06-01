"use client";

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 72 72" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="36" cy="36" r="34" stroke="var(--border-1)" strokeWidth="0.5" fill="none" />
      <circle cx="36" cy="36" r="22" stroke="var(--border-1)" strokeWidth="0.5" fill="none" />
      <circle cx="36" cy="36" r="34" stroke="var(--amber)" strokeWidth="1.5"
        strokeLinecap="round" strokeDasharray="55 150"
        fill="none" style={{ animation: "educe-spin 10s linear infinite", transformOrigin: "center" }} />
      <circle cx="36" cy="36" r="22" stroke="var(--amber-bright)" strokeWidth="0.8"
        strokeLinecap="round" strokeDasharray="35 170"
        fill="none" opacity="0.4" style={{ animation: "educe-spin-r 14s linear infinite", transformOrigin: "center" }} />
      <circle cx="36" cy="36" r="3" fill="var(--amber)" opacity="0.7" />
      <style>{`
        @keyframes educe-spin { to { transform: rotate(360deg); } }
        @keyframes educe-spin-r { to { transform: rotate(-360deg); } }
      `}</style>
    </svg>
  );
}

export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <span style={{
      fontFamily: "'Instrument Serif', Georgia, serif",
      fontSize: size * 0.85,
      color: "var(--text-0)",
      letterSpacing: "-0.02em",
      lineHeight: 1,
      userSelect: "none",
    }}>
      <span style={{ color: "var(--amber)" }}>E</span>duce
    </span>
  );
}

export function LogoBrand({ size = 48 }: { size?: number }) {
  return (
    <div className="flex flex-col items-center gap-4" style={{ userSelect: "none" }}>
      <Logo size={size * 1.4} />
    </div>
  );
}
