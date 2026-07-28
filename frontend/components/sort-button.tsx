"use client";

export type SortDirection = "none" | "asc" | "desc";

const directionLabels: Record<SortDirection, string> = {
  none: "未排序",
  asc: "升序",
  desc: "降序",
};

const nextDirection: Record<SortDirection, SortDirection> = {
  none: "asc",
  asc: "desc",
  desc: "none",
};

export function SortButton({
  direction,
  label,
  onChange,
}: {
  direction: SortDirection;
  label: string;
  onChange: (direction: SortDirection) => void;
}) {
  const next = nextDirection[direction];
  const description = `${label}排序：${directionLabels[direction]}，点击切换为${directionLabels[next]}`;

  return (
    <button
      type="button"
      className="ml-1 inline-flex h-7 w-7 flex-col items-center justify-center rounded-md align-middle leading-[0.5rem] transition hover:bg-[var(--accent-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
      aria-label={description}
      title={description}
      onClick={() => onChange(next)}
    >
      <span
        aria-hidden="true"
        className={`text-[8px] ${
          direction === "asc" ? "text-[var(--accent)]" : "text-[var(--muted)] opacity-35"
        }`}
      >
        ▲
      </span>
      <span
        aria-hidden="true"
        className={`text-[8px] ${
          direction === "desc" ? "text-[var(--accent)]" : "text-[var(--muted)] opacity-35"
        }`}
      >
        ▼
      </span>
    </button>
  );
}
