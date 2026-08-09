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
        className="calculation-tooltip pointer-events-none top-full hidden text-left text-xs font-normal leading-5 text-[var(--text)] group-hover:block group-focus-within:block"
      >
        {text}
      </span>
    </span>
  );
}
