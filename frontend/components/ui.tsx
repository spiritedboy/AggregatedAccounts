import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  SlidersHorizontal,
  LoaderCircle,
  type LucideIcon,
} from "lucide-react";
import { type CSSProperties, type ReactNode, useId } from "react";

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
    <div className="panel overflow-hidden" aria-label="正在加载">
      <div className="grid grid-cols-3 gap-4 border-b bg-[var(--surface-soft)] px-4 py-3" style={{ borderColor: "var(--line)" }}>
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-3 w-16 justify-self-end" />
        <Skeleton className="h-3 w-20 justify-self-end" />
      </div>
      <div className="divide-y" style={{ borderColor: "var(--line)" }}>
        {Array.from({ length: rows }).map((_, index) => (
          <div key={index} className="grid grid-cols-[1.3fr_.7fr] items-center gap-5 px-4 py-3 sm:grid-cols-3">
            <div className="space-y-2"><Skeleton className="h-3.5 w-32 max-w-full" /><Skeleton className="h-2.5 w-20" /></div>
            <Skeleton className="hidden h-3 w-16 justify-self-end sm:block" />
            <Skeleton className="h-3.5 w-20 justify-self-end" />
          </div>
        ))}
      </div>
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
  const safeMessage = message.replace(/\s+/g, " ").slice(0, 180);
  return (
    <div className="panel flex min-h-48 flex-col items-center justify-center gap-3 p-8 text-center">
      <AlertTriangle className="h-8 w-8 text-[var(--warning)]" />
      <div>
        <p className="font-semibold">数据暂时不可用</p>
        <p className="muted mt-1 text-sm">{safeMessage}</p>
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
    <header className="page-hero mb-4 flex min-w-0 flex-col justify-between gap-3 md:flex-row md:items-center">
      <div className="min-w-0 max-w-full">
        <p className="eyebrow">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--aqua)]" />
          {eyebrow}
        </p>
        <h1 className="page-title mt-1 text-[24px] font-bold tracking-[-0.035em] md:text-[27px]">{title}</h1>
        <p className="muted mt-1 max-w-3xl text-xs leading-5 [overflow-wrap:anywhere]">{description}</p>
      </div>
      {action && <div className="flex w-full min-w-0 max-w-full flex-wrap items-center md:w-auto md:shrink-0 md:justify-end">{action}</div>}
    </header>
  );
}

export function FilterPanel({
  primary,
  secondary,
  activeCount = 0,
  desktopClassName = "sm:grid-cols-2 xl:grid-cols-4",
  onReset,
}: {
  primary: ReactNode;
  secondary?: ReactNode;
  activeCount?: number;
  desktopClassName?: string;
  onReset?: () => void;
}) {
  const disclosureId = useId();
  return (
    <section className={`filter-panel responsive-filter-panel ${desktopClassName}`} aria-label="筛选工具栏">
      <div className="filter-primary">{primary}</div>
      {secondary && (
        <>
          <input id={disclosureId} type="checkbox" className="filter-disclosure peer sr-only" />
          <label htmlFor={disclosureId} className="filter-disclosure-button">
            <span className="flex items-center gap-2">
              <SlidersHorizontal className="h-4 w-4 text-[var(--accent)]" />
              更多筛选{activeCount > 0 ? ` (${activeCount})` : ""}
            </span>
            <ChevronDown className="h-4 w-4 transition-transform peer-checked:rotate-180" />
          </label>
          <div className="filter-secondary">{secondary}</div>
        </>
      )}
      {onReset && activeCount > 0 ? (
        <button
          type="button"
          className="min-h-10 rounded-[9px] border border-[var(--line)] px-3 text-xs font-semibold text-[var(--accent-strong)] transition hover:bg-[var(--accent-soft)]"
          onClick={onReset}
        >
          重置筛选
        </button>
      ) : null}
    </section>
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
      className={`panel metric-card relative overflow-hidden ${featured ? "p-5 md:p-7" : "p-4 md:p-5"}`}
      style={
        featured
          ? {
              background: "color-mix(in srgb, var(--accent-soft) 40%, var(--surface))",
              borderColor: "color-mix(in srgb, var(--accent) 28%, var(--line))",
              boxShadow: "var(--panel-shadow)",
            }
          : undefined
      }
    >
      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="metric-label">{label}</p>
          <div className={`metric-value ${featured ? "metric-value-featured" : ""} ${toneClass}`}>
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
  BYBIT: "BY",
  HYPERLIQUID: "HL",
  POLYMARKET: "PM",
};

const exchangePalette: Record<string, string> = {
  BINANCE: "#c98d00",
  OKX: "#765ee5",
  BITGET: "#07949c",
  BYBIT: "#d76821",
  HYPERLIQUID: "#079a72",
  POLYMARKET: "#b54e7b",
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
  const palette = exchangePalette[exchange] ?? "var(--accent)";
  return (
    <span
      className={`exchange-mark mono-number inline-grid shrink-0 place-items-center border font-semibold ${dimensions}`}
      style={{
        "--mark-color": palette,
      } as CSSProperties}
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
