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
  lastFetchedAt,
}: {
  state: AutoRefreshState;
  lastUpdatedAt?: string | null;
  lastFetchedAt?: string | null;
}) {
  const stale = isDataStale(lastUpdatedAt, state.now);
  const seconds = Math.max(0, Math.ceil((state.nextRefreshAt - state.now) / 1_000));
  const sourceAt = lastUpdatedAt ? Date.parse(lastUpdatedAt) : Number.NaN;
  const fetchedAt = lastFetchedAt ? Date.parse(lastFetchedAt) : Number.NaN;
  const sourceAgeSeconds = Number.isFinite(sourceAt)
    ? Math.max(0, Math.floor((state.now - sourceAt) / 1_000))
    : null;
  const fetchedAgeSeconds = Number.isFinite(fetchedAt)
    ? Math.max(0, Math.floor((state.now - fetchedAt) / 1_000))
    : null;
  const statusText = stale
    ? `DATA STALE · ${sourceAgeSeconds ?? "—"}s`
    : state.refreshing
      ? "FETCHING"
      : sourceAgeSeconds !== null
        ? `SOURCE · ${sourceAgeSeconds}s`
        : fetchedAgeSeconds !== null
          ? `FETCH · ${fetchedAgeSeconds}s`
          : `NEXT FETCH · ${seconds}s`;

  const timeDescription = [
    lastFetchedAt ? `页面取数 ${dateTime(lastFetchedAt)}` : null,
    lastUpdatedAt ? `源数据更新 ${dateTime(lastUpdatedAt)}` : null,
  ].filter(Boolean).join(" · ");

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
      title={timeDescription ? `立即刷新 · ${timeDescription}` : "立即刷新数据"}
      aria-label={state.refreshing ? "正在获取页面数据" : stale ? "源数据已过期，立即刷新数据" : "立即刷新数据"}
    >
      {stale ? (
        <AlertTriangle className="h-3.5 w-3.5" />
      ) : (
        <RefreshCw className={`h-3.5 w-3.5 ${state.refreshing ? "animate-spin" : ""}`} />
      )}
      <span className="mono-number font-semibold tracking-[0.04em]">{statusText}</span>
    </button>
  );
}

export function RefreshErrorNotice({
  message,
  lastFetchedAt,
  retry,
}: {
  message: string;
  lastFetchedAt: string | null;
  retry: () => void;
}) {
  return (
    <div role="alert" className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-[var(--warning)]/30 bg-[var(--warning-soft)] px-4 py-3 text-xs text-[var(--warning)]">
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <span className="min-w-0 flex-1">刷新失败：{message.replace(/\s+/g, " ").slice(0, 180)}。仍显示上次成功数据{lastFetchedAt ? `（页面取数 ${dateTime(lastFetchedAt)}）` : ""}。</span>
      <button type="button" className="min-h-9 rounded-lg border border-current px-3 font-semibold" onClick={retry}>重试</button>
    </div>
  );
}
