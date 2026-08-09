"use client";

import { CircleHelp } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

type TooltipPosition = { left: number; top: number; width: number; arrowLeft: number };

export function CalculationHint({ label, text }: { label: string; text: string }) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<TooltipPosition | null>(null);

  const updatePosition = useCallback(() => {
    const button = buttonRef.current;
    if (!button) return;
    const rect = button.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const mobile = viewportWidth < 768;
    const width = mobile ? viewportWidth - 32 : 256;
    const left = mobile
      ? 16
      : Math.min(Math.max(rect.left + rect.width / 2 - width / 2, 16), viewportWidth - width - 16);
    const estimatedHeight = mobile ? 112 : 92;
    const showAbove = !mobile && rect.bottom + estimatedHeight + 16 > viewportHeight;
    const top = mobile
      ? Math.max(16, viewportHeight / 2 - estimatedHeight / 2)
      : showAbove
        ? Math.max(16, rect.top - estimatedHeight - 10)
        : rect.bottom + 10;
    const arrowLeft = Math.min(Math.max(rect.left + rect.width / 2 - left, 16), width - 16);
    setPosition({ left, top, width, arrowLeft });
  }, []);

  useEffect(() => setMounted(true), []);
  useEffect(() => {
    if (!open) return;
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [open, updatePosition]);

  const tooltip = (
    <span
      role="tooltip"
      className={`calculation-tooltip pointer-events-none top-full text-left text-xs font-normal leading-5 text-[var(--text)] ${open && position ? "block" : "hidden"}`}
      style={position ? { left: position.left, top: position.top, width: position.width } : undefined}
    >
      {!position || window.innerWidth < 768 ? null : (
        <span className="calculation-tooltip-arrow" style={{ left: position.arrowLeft }} />
      )}
      {text}
    </span>
  );

  return (
    <span
      className="relative ml-1 inline-flex align-middle"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      <button
        ref={buttonRef}
        type="button"
        aria-label={`${label}计算说明`}
        aria-expanded={open}
        className="muted rounded-full p-0.5 transition hover:text-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
        onClick={() => setOpen((current) => !current)}
      >
        <CircleHelp className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      {mounted ? createPortal(tooltip, document.body) : tooltip}
    </span>
  );
}
