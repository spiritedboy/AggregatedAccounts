import type { ClosedPosition, Position } from "@/lib/types";

type PositionLabelData = Pick<
  Position | ClosedPosition,
  | "exchange"
  | "symbol"
  | "normalized_symbol"
  | "display_symbol"
  | "original_symbol"
  | "translation_status"
>;

export function PositionLabel({
  position,
  compact = false,
}: {
  position: PositionLabelData;
  compact?: boolean;
}) {
  if (position.exchange !== "POLYMARKET") {
    return (
      <p className={`font-mono font-semibold ${compact ? "text-sm" : ""}`}>
        {position.normalized_symbol}
      </p>
    );
  }

  const translated =
    position.translation_status === "READY" &&
    position.display_symbol !== position.original_symbol;

  return (
    <div className="min-w-0">
      <p
        className={`font-semibold leading-snug ${compact ? "text-sm" : ""}`}
        title={position.display_symbol}
      >
        {position.display_symbol}
      </p>
      {translated && (
        <div className="mt-1 flex min-w-0 items-center gap-1.5">
          <span className="shrink-0 rounded-full bg-[var(--aqua-soft)] px-1.5 py-0.5 text-[9px] font-bold tracking-wide text-[var(--aqua)]">
            AI译
          </span>
          <p
            className="muted truncate text-[10px]"
            title={position.original_symbol}
          >
            {position.original_symbol}
          </p>
        </div>
      )}
    </div>
  );
}
