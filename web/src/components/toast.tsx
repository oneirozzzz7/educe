"use client";

import { useState, useEffect, useCallback } from "react";

interface Toast { id: number; message: string; type: "error" | "info" | "success" }

let toastId = 0;
let addToastFn: ((msg: string, type?: Toast["type"]) => void) | null = null;

export function toast(message: string, type: Toast["type"] = "info") {
  addToastFn?.(message, type);
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((message: string, type: Toast["type"] = "info") => {
    const id = ++toastId;
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000);
  }, []);

  useEffect(() => { addToastFn = addToast; return () => { addToastFn = null; }; }, [addToast]);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2">
      {toasts.map(t => (
        <div key={t.id} className="px-4 py-2.5 rounded-xl text-sm shadow-lg animate-in fade-in slide-in-from-top-2"
          style={{
            background: t.type === "error" ? "var(--fail)" : t.type === "success" ? "var(--pass)" : "var(--surface-1)",
            color: t.type === "info" ? "var(--text-0)" : "var(--void)",
            border: t.type === "info" ? "1px solid var(--border-1)" : "none",
            boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
          }}>
          {t.message}
        </div>
      ))}
    </div>
  );
}
