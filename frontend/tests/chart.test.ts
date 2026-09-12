import { describe, expect, it } from "vitest";

import { categoryAxisInterval, compactAxisMoney } from "@/lib/chart";

describe("responsive chart helpers", () => {
  it("limits category labels without hiding short series", () => {
    expect(categoryAxisInterval(4, 4)).toBe(0);
    expect(categoryAxisInterval(5, 4)).toBe(1);
    expect(categoryAxisInterval(30, 4)).toBe(7);
  });

  it("keeps large axis values compact in both currencies", () => {
    expect(compactAxisMoney(3250, "USD")).toBe("$3.3k");
    expect(compactAxisMoney(-1_250_000, "CNY")).toBe("−¥1.3m");
  });
});
