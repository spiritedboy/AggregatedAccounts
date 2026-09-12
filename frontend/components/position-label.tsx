import type { ClosedPosition, Position } from "@/lib/types";
import { ExpandableText } from "@/components/expandable-text";

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
      <p className={`long-data-id font-mono font-semibold ${compact ? "text-sm" : ""}`}>
        {position.normalized_symbol}
      </p>
    );
  }

  const translated =
    position.translation_status === "READY" &&
    position.display_symbol !== position.original_symbol;

  return (
    <div className="min-w-0">
      <div className="flex min-w-0 items-start gap-1.5">
        {translated ? (
          <span className="shrink-0 rounded-full bg-[var(--aqua-soft)] px-1.5 py-0.5 text-[11px] font-bold tracking-wide text-[var(--aqua)]">
            AI译
          </span>
        ) : null}
        <div className="min-w-0 flex-1">
          <ExpandableText
            text={position.display_symbol}
            secondaryText={translated ? position.original_symbol : null}
            className={`font-semibold leading-snug ${compact ? "text-sm" : ""}`}
            secondaryClassName="muted text-[11px]"
          />
        </div>
      </div>
    </div>
  );
}
