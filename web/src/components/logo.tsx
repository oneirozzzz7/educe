"use client";

/**
 * DeepForge Brand Logo v3
 * 小尺寸：简洁菱形图标（sidebar/favicon用）
 * 大尺寸：字母标+图标组合（空状态/品牌展示用）
 */

export function Logo({ size = 28 }: { size?: number }) {
  const id = `df-${Math.random().toString(36).slice(2, 6)}`;
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id={`${id}-bg`} x1="0" y1="0" x2="32" y2="32">
          <stop offset="0%" stopColor="#4F46E5" />
          <stop offset="100%" stopColor="#7C3AED" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="7" fill={`url(#${id}-bg)`} />
      <path d="M16 7L24.5 16L16 25L7.5 16Z" fill="white" fillOpacity="0.95" />
      <path d="M16 11L20.5 16L16 21L11.5 16Z" fill={`url(#${id}-bg)`} fillOpacity="0.3" />
    </svg>
  );
}

export function LogoMark({ size = 28 }: { size?: number }) {
  return <Logo size={size} />;
}

export function LogoBrand({ size = 48 }: { size?: number }) {
  const fontSize = size * 0.45;
  return (
    <div className="flex items-center gap-3" style={{ userSelect: "none" }}>
      <Logo size={size * 0.7} />
      <div>
        <div className="font-bold tracking-tight leading-none" style={{ fontSize, color: "var(--text)" }}>
          Deep<span style={{ color: "var(--brand)" }}>Forge</span>
        </div>
        <div className="tracking-widest uppercase font-medium" style={{ fontSize: fontSize * 0.28, color: "var(--text-3)", marginTop: 2 }}>
          Multi-Agent Framework
        </div>
      </div>
    </div>
  );
}
