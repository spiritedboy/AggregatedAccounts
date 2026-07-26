import type { Envelope } from "@/lib/types";

function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const item = document.cookie
    .split("; ")
    .find((entry) => entry.startsWith("portfolio_csrf="));
  return item ? decodeURIComponent(item.split("=")[1]) : "";
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    headers.set("X-CSRF-Token", csrfToken());
  }
  const response = await fetch(path, {
    ...init,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });
  const payload = (await response.json()) as Envelope<T>;
  if (!response.ok || !payload.success) {
    throw new Error(payload.error?.message ?? "请求失败，请稍后重试");
  }
  return payload.data;
}
