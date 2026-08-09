"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { dateTime } from "@/lib/format";

export const AUTO_REFRESH_INTERVAL_MS = 60_000;
export const DATA_STALE_AFTER_MS = 120_000;

export type AutoRefreshState = {
  nextRefreshAt: number;
  now: number;
  refreshing: boolean;
  refreshNow: () => Promise<void>;
};

export function isDataStale(
  lastUpdatedAt: string | null | undefined,
  now: number,
  staleAfterMs = DATA_STALE_AFTER_MS,
) {
  if (!lastUpdatedAt) return false;
  const updatedAt = Date.parse(lastUpdatedAt);
  return Number.isFinite(updatedAt) && now - updatedAt > staleAfterMs;
}

export function useAutoRefresh(
  refresh: () => void | Promise<unknown>,
  intervalMs = AUTO_REFRESH_INTERVAL_MS,
): AutoRefreshState {
  const [now, setNow] = useState(() => Date.now());
  const [nextRefreshAt, setNextRefreshAt] = useState(() => Date.now() + intervalMs);
  const [refreshing, setRefreshing] = useState(false);
  const running = useRef(false);
  const mounted = useRef(true);

  const runRefresh = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    setRefreshing(true);
    try {
      await refresh();
    } finally {
      running.current = false;
      if (mounted.current) {
        const refreshedAt = Date.now();
        setNow(refreshedAt);
        setNextRefreshAt(refreshedAt + intervalMs);
        setRefreshing(false);
      }
    }
  }, [intervalMs, refresh]);

  useEffect(() => {
    mounted.current = true;

    const refreshTimer = window.setInterval(() => void runRefresh(), intervalMs);
    const clockTimer = window.setInterval(() => setNow(Date.now()), 1_000);
    const handleVisibility = () => {
      const currentTime = Date.now();
      setNow(currentTime);
      if (document.visibilityState === "visible" && currentTime >= nextRefreshAt) {
        void runRefresh();
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      mounted.current = false;
      window.clearInterval(refreshTimer);
      window.clearInterval(clockTimer);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [intervalMs, nextRefreshAt, runRefresh]);

  return { nextRefreshAt, now, refreshing, refreshNow: runRefresh };
}

export function AutoRefreshStatus({
  state,
  lastUpdatedAt,
}: {
  state: AutoRefreshState;
  lastUpdatedAt?: string | null;
}) {
  const stale = isDataStale(lastUpdatedAt, state.now);
  const seconds = Math.max(0, Math.ceil((state.nextRefreshAt - state.now) / 1_000));

  return (
    <button
      type="button"
      className={`auto-refresh-status inline-flex max-w-full flex-wrap items-center justify-start gap-x-2 gap-y-1 rounded-[10px] border px-3 py-2 text-[11px] font-medium transition sm:justify-end ${
        stale
          ? "border-amber-500/25 bg-[var(--warning-soft)] text-[var(--warning)]"
          : "border-[var(--line)] bg-[var(--surface)] text-[var(--muted)]"
      }`}
      onClick={() => void state.refreshNow()}
      disabled={state.refreshing}
      title="立即刷新数据"
      aria-live="polite"
      aria-label={state.refreshing ? "正在刷新数据" : "立即刷新数据"}
    >
      {stale ? (
        <AlertTriangle className="h-3.5 w-3.5" />
      ) : (
        <RefreshCw className={`h-3.5 w-3.5 ${state.refreshing ? "animate-spin" : ""}`} />
      )}
      <span>{stale ? "数据已过期，正在自动重试" : state.refreshing ? "正在刷新" : `${seconds} 秒后刷新`}</span>
      {lastUpdatedAt && <span className="auto-refresh-updated opacity-75">更新于 {dateTime(lastUpdatedAt)}</span>}
    </button>
  );
}
