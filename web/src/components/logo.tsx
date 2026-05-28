"use client";

/**
 * DeepForge Brand Logo v2
 * 概念：锻造的火焰 + 数字结晶
 * D和F交织形成钻石结构——代表从粗糙到精品的淬炼
 */
export function Logo({ size = 28 }: { size?: number }) {
  const id = `df-${size}-${Math.random().toString(36).slice(2, 6)}`;
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id={`${id}-bg`} x1="0" y1="0" x2="32" y2="32">
          <stop offset="0%" stopColor="#4338CA" />
          <stop offset="40%" stopColor="#6366F1" />
          <stop offset="100%" stopColor="#818CF8" />
        </linearGradient>
        <linearGradient id={`${id}-inner`} x1="10" y1="6" x2="22" y2="26">
          <stop offset="0%" stopColor="#E0E7FF" />
          <stop offset="50%" stopColor="#FFFFFF" />
          <stop offset="100%" stopColor="#C7D2FE" />
        </linearGradient>
        <linearGradient id={`${id}-spark`} x1="22" y1="4" x2="28" y2="10">
          <stop offset="0%" stopColor="#FDE68A" />
          <stop offset="100%" stopColor="#F59E0B" />
        </linearGradient>
        <filter id={`${id}-glow`} x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="0.8" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* 圆角方形背景 */}
      <rect width="32" height="32" rx="8" fill={`url(#${id}-bg)`} />

      {/* 外层菱形框架——harness */}
      <path d="M16 4L28 16L16 28L4 16Z" stroke="white" strokeWidth="1" strokeOpacity="0.15" fill="none" />

      {/* 内层晶体——精品 */}
      <path d="M16 8L23 16L16 24L9 16Z" fill={`url(#${id}-inner)`} fillOpacity="0.92" filter={`url(#${id}-glow)`} />

      {/* 晶体纹理——结构感 */}
      <path d="M16 8L16 24" stroke="#4338CA" strokeWidth="0.6" strokeOpacity="0.2" />
      <path d="M9 16L23 16" stroke="#4338CA" strokeWidth="0.6" strokeOpacity="0.2" />
      <path d="M12 12L20 20" stroke="#4338CA" strokeWidth="0.4" strokeOpacity="0.12" />
      <path d="M20 12L12 20" stroke="#4338CA" strokeWidth="0.4" strokeOpacity="0.12" />

      {/* 锻造火花 */}
      <circle cx="25" cy="6" r="2.2" fill={`url(#${id}-spark)`} />
      <circle cx="27.5" cy="8.5" r="1.1" fill="#FDE68A" fillOpacity="0.6" />
      <circle cx="23.5" cy="4" r="0.7" fill="#FDE68A" fillOpacity="0.4" />
    </svg>
  );
}

export function LogoMark({ size = 28 }: { size?: number }) {
  return <Logo size={size} />;
}

export function LogoFull({ size = 120 }: { size?: number }) {
  const h = size * 0.3;
  return (
    <div className="flex items-center gap-2">
      <Logo size={h} />
      <span className="font-bold tracking-tight" style={{ fontSize: h * 0.55, color: "var(--text)" }}>
        Deep<span style={{ color: "var(--brand)" }}>Forge</span>
      </span>
    </div>
  );
}
