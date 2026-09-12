"use client";

import type { EChartsOption } from "echarts";
import dynamic from "next/dynamic";
import type { CSSProperties } from "react";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

export function Chart({
  option,
  height = 280,
  mobileHeight = 240,
  ariaLabel = "数据图表",
}: {
  option: EChartsOption;
  height?: number;
  mobileHeight?: number;
  ariaLabel?: string;
}) {
  return (
    <div
      className="responsive-chart min-w-0"
      role="img"
      aria-label={ariaLabel}
      style={{
        "--chart-height": `${height}px`,
        "--chart-mobile-height": `${mobileHeight}px`,
      } as CSSProperties}
    >
      <ReactECharts
        option={option}
        notMerge
        lazyUpdate
        style={{ height: "100%", width: "100%" }}
        opts={{ renderer: "svg" }}
      />
    </div>
  );
}
