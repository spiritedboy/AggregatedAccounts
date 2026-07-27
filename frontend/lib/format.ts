export function usd(value: number, hidden = false): string {
  if (hidden) return "$••••••";
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

export function number(value: number, digits = 4): string {
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: digits,
  }).format(value);
}

export function dateTime(value?: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    hour12: false,
  }).format(new Date(value));
}

export function compactDate(value?: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

export function positionSideLabel(
  side: "LONG" | "SHORT",
  exchange?: string,
): string {
  if (exchange === "POLYMARKET") return "持有";
  return side === "LONG" ? "做多" : "做空";
}
