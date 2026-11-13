/** Reporting days are Asia/Shanghai calendar days, independent of the viewer's timezone. */
const BEIJING_OFFSET_MS = 8 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

export function beijingDateKey(now: Date = new Date()): string {
  return new Date(now.getTime() + BEIJING_OFFSET_MS).toISOString().slice(0, 10);
}

export function millisecondsUntilNextBeijingDay(now: Date = new Date()): number {
  const nextDay = new Date(now.getTime() + BEIJING_OFFSET_MS + DAY_MS).toISOString().slice(0, 10);
  return Math.max(1, Date.parse(`${nextDay}T00:00:00+08:00`) - now.getTime());
}

export function beijingDayStart(day: string): string {
  return `${day}T00:00:00+08:00`;
}

export function beijingDayEnd(day: string): string {
  return `${day}T23:59:59.999999+08:00`;
}
