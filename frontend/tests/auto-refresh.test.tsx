import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AutoRefreshStatus,
  isDataStale,
  useAutoRefresh,
} from "@/components/auto-refresh-status";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("automatic data refresh", () => {
  it("refreshes once every 60 seconds", async () => {
    vi.useFakeTimers();
    const refresh = vi.fn();

    function Probe() {
      useAutoRefresh(refresh);
      return null;
    }

    render(<Probe />);
    expect(refresh).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("marks source data as stale after 120 seconds", () => {
    const updatedAt = "2026-07-26T00:00:00.000Z";
    const now = Date.parse("2026-07-26T00:02:01.000Z");

    expect(isDataStale(updatedAt, now)).toBe(true);
    expect(isDataStale(updatedAt, now - 2_000)).toBe(false);

    render(
      <AutoRefreshStatus
        state={{ nextRefreshAt: now + 30_000, now, refreshing: false }}
        lastUpdatedAt={updatedAt}
      />,
    );
    expect(screen.getByText("数据已过期，正在自动重试")).toBeInTheDocument();
  });
});
