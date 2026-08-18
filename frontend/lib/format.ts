export type DisplayCurrency = "USD" | "CNY";

export function money(
  value: number,
  currency: DisplayCurrency = "USD",
  usdCnyRate = 1,
): string {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(currency === "CNY" ? value * usdCnyRate : value);
}

/** Prices and position notional values intentionally stay denominated in USD. */
export function usd(value: number): string {
  return money(value, "USD", 1);
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

const exchangeDisplayNames: Record<string, string> = {
  BINANCE: "Binance",
  OKX: "OKX",
  BITGET: "Bitget",
  BYBIT: "Bybit",
  HYPERLIQUID: "Hyperliquid",
  POLYMARKET: "Polymarket",
};

export function exchangeDisplayName(exchange: string): string {
  return exchangeDisplayNames[exchange.toUpperCase()] ?? exchange;
}

export function connectionDisplayName(name: string, exchange: string): string {
  return name.trim().toLowerCase() === exchange.trim().toLowerCase()
    ? exchangeDisplayName(exchange)
    : name;
}
