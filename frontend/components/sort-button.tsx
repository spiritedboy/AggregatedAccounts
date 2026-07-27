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
      className="ml-1 inline-flex h-6 w-5 flex-col items-center justify-center rounded-sm align-middle leading-[0.5rem] transition hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400/70 dark:hover:bg-white/10"
      aria-label={description}
      title={description}
      onClick={() => onChange(next)}
    >
      <span
        aria-hidden="true"
        className={`text-[8px] ${
          direction === "asc" ? "text-violet-500" : "text-slate-400/50 dark:text-slate-500/60"
        }`}
      >
        ▲
      </span>
      <span
        aria-hidden="true"
        className={`text-[8px] ${
          direction === "desc" ? "text-violet-500" : "text-slate-400/50 dark:text-slate-500/60"
        }`}
      >
        ▼
      </span>
    </button>
  );
}
