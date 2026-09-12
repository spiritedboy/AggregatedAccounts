import type { DisplayCurrency } from "@/lib/format";

export function categoryAxisInterval(pointCount: number, maximumLabels: number) {
  if (pointCount <= maximumLabels) return 0;
  return Math.max(0, Math.ceil(pointCount / maximumLabels) - 1);
}

export function compactAxisMoney(value: number, currency: DisplayCurrency) {
  const absolute = Math.abs(value);
  const prefix = currency === "CNY" ? "¥" : "$";
  const sign = value < 0 ? "−" : "";
  if (absolute >= 1_000_000) return `${sign}${prefix}${trimDecimal(absolute / 1_000_000)}m`;
  if (absolute >= 1_000) return `${sign}${prefix}${trimDecimal(absolute / 1_000)}k`;
  return `${sign}${prefix}${trimDecimal(absolute)}`;
}

function trimDecimal(value: number) {
  return value.toFixed(value >= 100 ? 0 : 1).replace(/\.0$/, "");
}
