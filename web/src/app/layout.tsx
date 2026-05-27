import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DeepForge",
  description: "7 AI Agents collaborate to build what you imagine",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="bg-bg text-white h-screen overflow-hidden flex flex-col">
        {children}
      </body>
    </html>
  );
}
