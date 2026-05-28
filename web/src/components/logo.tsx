"use client";

/**
 * DeepForge Brand Logo
 * 概念：淬炼晶体——从原料到精品的转化
 * 外层菱形轮廓 = 框架（harness）
 * 内层发光晶体 = 被框架激发的潜力
 * 右上火花 = 锻造(Forge)的能量
 */
export function Logo({ size = 28 }: { size?: number }) {
  const id = `df-${size}`;
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id={`${id}-bg`} x1="0" y1="0" x2="32" y2="32">
          <stop offset="0%" stopColor="#4338CA" />
          <stop offset="50%" stopColor="#6366F1" />
          <stop offset="100%" stopColor="#7C3AED" />
        </linearGradient>
        <linearGradient id={`${id}-crystal`} x1="10" y1="8" x2="22" y2="24">
          <stop offset="0%" stopColor="#E0E7FF" />
          <stop offset="100%" stopColor="#FFFFFF" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="7" fill={`url(#${id}-bg)`} />
      <path d="M16 5L27 16L16 27L5 16Z" stroke="white" strokeWidth="1.2" strokeOpacity="0.2" fill="none" />
      <path d="M16 9L22 16L16 23L10 16Z" fill={`url(#${id}-crystal)`} fillOpacity="0.9" />
      <path d="M12.5 13.5L16 16L19.5 13.5" stroke="#4338CA" strokeWidth="1" strokeLinecap="round" strokeOpacity="0.4" />
      <path d="M12.5 18.5L16 16L19.5 18.5" stroke="#4338CA" strokeWidth="1" strokeLinecap="round" strokeOpacity="0.25" />
      <circle cx="24" cy="7" r="2" fill="#FDE68A" />
      <circle cx="27" cy="9.5" r="1" fill="#FDE68A" fillOpacity="0.5" />
    </svg>
  );
}

export function LogoMark({ size = 28 }: { size?: number }) {
  return <Logo size={size} />;
}
