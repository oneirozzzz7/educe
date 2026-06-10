"use client";

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 72 72" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="36" cy="36" r="32" stroke="rgba(255,255,255,0.08)" strokeWidth="1" fill="none" />
      <circle cx="36" cy="36" r="32" stroke="var(--accent)" strokeWidth="1.5"
        strokeLinecap="round" strokeDasharray="50 150"
        fill="none" style={{ animation: "educe-spin 12s linear infinite", transformOrigin: "center" }} />
      <circle cx="36" cy="36" r="3" fill="var(--accent)" opacity="0.8" />
      <style>{`
        @keyframes educe-spin { to { transform: rotate(360deg); } }
      `}</style>
    </svg>
  );
}

export function LogoMark({ size = 20 }: { size?: number }) {
  const fontSize = size;
  const lineWidth = fontSize * 1.6;
  const lineHeight = Math.max(1.5, fontSize * 0.08);
  const lineOffset = fontSize * 0.25;

  return (
    <span style={{
      position: "relative",
      display: "inline-block",
      fontFamily: "'Spectral', 'Instrument Serif', Georgia, serif",
      fontSize,
      fontWeight: 300,
      color: "var(--text-0)",
      letterSpacing: "-0.01em",
      lineHeight: 1,
      userSelect: "none",
    }}>
      <span style={{ color: "var(--accent)", fontWeight: 400 }}>E</span>duce
      <span style={{
        position: "absolute",
        left: 0,
        bottom: -lineOffset,
        width: lineWidth,
        height: lineHeight,
        borderRadius: lineHeight,
        background: "linear-gradient(90deg, var(--accent) 0%, rgba(167,139,250,0.3) 60%, transparent 100%)",
      }} />
    </span>
  );
}

export function LogoBrand({ size = 48 }: { size?: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16, userSelect: "none" }}>
      <LogoMark size={size} />
    </div>
  );
}
