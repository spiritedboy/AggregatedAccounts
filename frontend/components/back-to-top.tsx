"use client";

import { ArrowUp } from "lucide-react";
import { useEffect, useState } from "react";

export function BackToTop() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const updateVisibility = () => setVisible(window.scrollY > 640);
    updateVisibility();
    window.addEventListener("scroll", updateVisibility, { passive: true });
    return () => window.removeEventListener("scroll", updateVisibility);
  }, []);

  return (
    <button
      type="button"
      aria-label="返回页面顶部"
      title="返回顶部"
      onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
      className={`button-secondary fixed right-4 z-30 grid h-11 min-h-11 w-11 place-items-center rounded-full p-0 shadow-lg transition-all lg:hidden ${
        visible ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-3 opacity-0"
      }`}
      style={{ bottom: "calc(5.75rem + env(safe-area-inset-bottom))" }}
    >
      <ArrowUp className="h-4 w-4" />
    </button>
  );
}
