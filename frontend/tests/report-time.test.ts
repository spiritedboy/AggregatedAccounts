import { describe, expect, it } from "vitest";

import { beijingDateKey, beijingDayEnd, beijingDayStart, millisecondsUntilNextBeijingDay } from "@/lib/report-time";

describe("Beijing reporting day", () => {
  it("uses the same calendar day regardless of browser timezone", () => {
    expect(beijingDayStart("2026-11-10")).toBe("2026-11-10T00:00:00+08:00");
    expect(beijingDayEnd("2026-11-10")).toBe("2026-11-10T23:59:59.999999+08:00");
  });

  it("rolls over at Beijing midnight", () => {
    const before = new Date("2026-11-12T15:59:59.000Z");
    const after = new Date("2026-11-12T16:00:00.000Z");
    expect(beijingDateKey(before)).toBe("2026-11-12");
    expect(millisecondsUntilNextBeijingDay(before)).toBe(1000);
    expect(beijingDateKey(after)).toBe("2026-11-13");
    expect(millisecondsUntilNextBeijingDay(after)).toBe(24 * 60 * 60 * 1000);
  });
});
