"use client";

import { useEffect } from "react";

type FilterValue = string | number | null | undefined;

export function readPageFilters(pathname: string) {
  if (typeof window === "undefined" || window.location.pathname !== pathname) return null;
  return new URLSearchParams(window.location.search);
}

export function useUrlFilterSync(
  pathname: string,
  ready: boolean,
  values: Record<string, FilterValue>,
) {
  const serialized = new URLSearchParams(
    Object.entries(values)
      .filter(([, value]) => value !== "" && value !== null && value !== undefined && value !== 1)
      .map(([key, value]) => [key, String(value)]),
  ).toString();

  useEffect(() => {
    if (!ready || window.location.pathname !== pathname) return;
    const nextUrl = `${pathname}${serialized ? `?${serialized}` : ""}${window.location.hash}`;
    window.history.replaceState(window.history.state, "", nextUrl);
  }, [pathname, ready, serialized]);
}
