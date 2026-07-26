import { AlertTriangle, CheckCircle2, LoaderCircle } from "lucide-react";
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
      "border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300",
    negative: "border-rose-500/20 bg-rose-500/10 text-rose-600 dark:text-rose-300",
    warning: "border-amber-500/20 bg-amber-500/10 text-amber-600 dark:text-amber-300",
    neutral: "border-black/10 bg-black/5 text-current dark:border-white/10 dark:bg-white/5",
    mint: "border-mint-400/20 bg-mint-400/10 text-mint-500 dark:text-mint-300",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold ${colors[tone]}`}
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
      <AlertTriangle className="h-8 w-8 text-amber-500" />
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
      <CheckCircle2 className="h-8 w-8 text-mint-400" />
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
    <header className="mb-6 flex flex-col justify-between gap-4 md:flex-row md:items-end">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight md:text-3xl">{title}</h1>
        <p className="muted mt-2 max-w-2xl text-sm leading-6">{description}</p>
      </div>
      {action}
    </header>
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
