"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { dateTime } from "@/lib/format";

export const AUTO_REFRESH_INTERVAL_MS = 60_000;
export const DATA_STALE_AFTER_MS = 120_000;

export type AutoRefreshState = {
  nextRefreshAt: number;
  now: number;
  refreshing: boolean;
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

  useEffect(() => {
    let active = true;

    const runRefresh = async () => {
      if (running.current) return;
      running.current = true;
      setRefreshing(true);
      try {
        await refresh();
      } finally {
        running.current = false;
        if (active) {
          const refreshedAt = Date.now();
          setNow(refreshedAt);
          setNextRefreshAt(refreshedAt + intervalMs);
          setRefreshing(false);
        }
      }
    };

    const refreshTimer = window.setInterval(runRefresh, intervalMs);
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
      active = false;
      window.clearInterval(refreshTimer);
      window.clearInterval(clockTimer);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [intervalMs, nextRefreshAt, refresh]);

  return { nextRefreshAt, now, refreshing };
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
    <div
      className={`inline-flex flex-wrap items-center justify-end gap-x-2 gap-y-1 rounded-[10px] border px-3 py-2 text-[11px] font-medium ${
        stale
          ? "border-amber-500/25 bg-[var(--warning-soft)] text-[var(--warning)]"
          : "border-[var(--line)] bg-[var(--surface)] text-[var(--muted)]"
      }`}
      aria-live="polite"
    >
      {stale ? (
        <AlertTriangle className="h-3.5 w-3.5" />
      ) : (
        <RefreshCw className={`h-3.5 w-3.5 ${state.refreshing ? "animate-spin" : ""}`} />
      )}
      <span>{stale ? "数据已过期，正在自动重试" : state.refreshing ? "正在刷新" : `${seconds} 秒后刷新`}</span>
      {lastUpdatedAt && <span className="opacity-75">更新于 {dateTime(lastUpdatedAt)}</span>}
    </div>
  );
}
