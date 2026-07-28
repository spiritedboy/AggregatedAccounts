import {
  AlertTriangle,
  CheckCircle2,
  LoaderCircle,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "positive" | "negative" | "warning" | "neutral" | "mint";
}) {
  const colors = {
    positive:
      "border-emerald-500/20 bg-[var(--positive-soft)] text-[var(--positive)]",
    negative: "border-rose-500/20 bg-[var(--negative-soft)] text-[var(--negative)]",
    warning: "border-amber-500/20 bg-[var(--warning-soft)] text-[var(--warning)]",
    neutral: "border-[var(--line)] bg-[var(--surface-soft)] text-[var(--muted)]",
    mint: "border-cyan-500/20 bg-[var(--aqua-soft)] text-[var(--aqua)]",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold whitespace-nowrap ${colors[tone]}`}
    >
      {children}
    </span>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-xl bg-black/5 dark:bg-white/[0.06] ${className}`}
      aria-hidden="true"
    />
  );
}

export function LoadingState({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-3" aria-label="正在加载">
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-16 w-full" />
      ))}
    </div>
  );
}

export function ErrorState({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="panel flex min-h-48 flex-col items-center justify-center gap-3 p-8 text-center">
      <AlertTriangle className="h-8 w-8 text-[var(--warning)]" />
      <div>
        <p className="font-semibold">数据暂时不可用</p>
        <p className="muted mt-1 text-sm">{message}</p>
      </div>
      {retry && (
        <button type="button" className="button-secondary" onClick={retry}>
          重试
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center p-8 text-center">
      <CheckCircle2 className="h-8 w-8 text-[var(--aqua)]" />
      <p className="mt-3 font-semibold">{title}</p>
      <p className="muted mt-1 max-w-sm text-sm">{description}</p>
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <header className="mb-5 flex flex-col justify-between gap-4 md:flex-row md:items-end">
      <div className="min-w-0">
        <p className="eyebrow">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--aqua)]" />
          {eyebrow}
        </p>
        <h1 className="page-title mt-2 text-[30px] font-extrabold tracking-[-0.045em] md:text-[34px]">{title}</h1>
        <p className="muted mt-1.5 max-w-2xl text-sm leading-6">{description}</p>
      </div>
      {action}
    </header>
  );
}

export function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  tone = "neutral",
  featured = false,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  icon?: LucideIcon;
  tone?: "neutral" | "positive" | "negative" | "warning" | "accent";
  featured?: boolean;
}) {
  const toneClass = {
    neutral: "",
    positive: "text-positive",
    negative: "text-negative",
    warning: "text-warning",
    accent: "text-[var(--accent)]",
  }[tone];

  return (
    <article
      className={`panel relative overflow-hidden ${featured ? "p-6 md:p-7" : "p-5"}`}
      style={
        featured
          ? {
              background:
                "linear-gradient(135deg, color-mix(in srgb, var(--accent-soft) 68%, var(--surface)) 0%, var(--surface) 48%, color-mix(in srgb, var(--aqua-soft) 58%, var(--surface)) 100%)",
            }
          : undefined
      }
    >
      {featured && (
        <>
          <div className="pointer-events-none absolute -right-12 -top-14 h-36 w-36 rounded-full border-[18px] border-[var(--accent)]/10" />
          <div className="pointer-events-none absolute bottom-5 right-20 h-5 w-5 rounded-full bg-[var(--aqua)]/25" />
          <div className="pointer-events-none absolute right-10 top-1/2 h-3 w-3 rounded-full bg-pink-400/30" />
        </>
      )}
      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="metric-label">{label}</p>
          <div className={`metric-value ${featured ? "text-3xl md:text-4xl" : ""} ${toneClass}`}>
            {value}
          </div>
          {detail && <div className="muted mt-2 text-xs leading-5">{detail}</div>}
        </div>
        {Icon && (
          <div
            className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] border"
            style={{ background: "var(--surface-soft)", borderColor: "var(--line)" }}
          >
            <Icon className={`h-4 w-4 ${toneClass || "text-[var(--accent)]"}`} />
          </div>
        )}
      </div>
    </article>
  );
}

const exchangeNames: Record<string, string> = {
  BINANCE: "BN",
  OKX: "OK",
  BITGET: "BG",
  HYPERLIQUID: "HL",
  POLYMARKET: "PM",
};

const exchangePalette: Record<string, { color: string; background: string; border: string }> = {
  BINANCE: { color: "#8a6500", background: "#fff4c8", border: "#f3cf55" },
  OKX: { color: "#5c4fc2", background: "#eeeaff", border: "#c9c1ff" },
  BITGET: { color: "#087f87", background: "#dcf9f7", border: "#8be2dc" },
  HYPERLIQUID: { color: "#068968", background: "#ddf9ef", border: "#86dfc2" },
  POLYMARKET: { color: "#bd4679", background: "#ffe7f2", border: "#f6a9c9" },
};

export function ExchangeMark({
  exchange,
  size = "md",
}: {
  exchange: string;
  size?: "sm" | "md" | "lg";
}) {
  const dimensions = {
    sm: "h-7 w-7 rounded-lg text-[9px]",
    md: "h-9 w-9 rounded-[10px] text-[10px]",
    lg: "h-11 w-11 rounded-xl text-[11px]",
  }[size];
  const palette = exchangePalette[exchange] ?? {
    color: "var(--accent-strong)",
    background: "var(--accent-soft)",
    border: "var(--line)",
  };
  return (
    <span
      className={`mono-number inline-grid shrink-0 place-items-center border font-semibold ${dimensions}`}
      style={{
        color: palette.color,
        background: palette.background,
        borderColor: palette.border,
      }}
      aria-label={exchange}
    >
      {exchangeNames[exchange] ?? exchange.slice(0, 2)}
    </span>
  );
}

export function SubmitLabel({
  pending,
  children,
}: {
  pending: boolean;
  children: ReactNode;
}) {
  return (
    <>
      {pending && <LoaderCircle className="h-4 w-4 animate-spin" />}
      {children}
    </>
  );
}
