import { CircleHelp } from "lucide-react";

export function CalculationHint({ label, text }: { label: string; text: string }) {
  return (
    <span className="group relative ml-1 inline-flex align-middle">
      <button
        type="button"
        aria-label={`${label}计算说明`}
        className="muted rounded-full p-0.5 transition hover:text-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
      >
        <CircleHelp className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full right-0 z-30 mb-2 hidden w-64 rounded-xl border bg-[var(--panel)] p-3 text-left text-xs font-normal leading-5 text-[var(--text)] shadow-xl group-hover:block group-focus-within:block"
        style={{ borderColor: "var(--line)" }}
      >
        {text}
      </span>
    </span>
  );
}
