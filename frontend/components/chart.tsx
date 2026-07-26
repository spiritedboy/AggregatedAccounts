"use client";

import type { EChartsOption } from "echarts";
import dynamic from "next/dynamic";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

export function Chart({
  option,
  height = 280,
}: {
  option: EChartsOption;
  height?: number;
}) {
  return (
    <ReactECharts
      option={option}
      notMerge
      lazyUpdate
      style={{ height, width: "100%" }}
      opts={{ renderer: "svg" }}
    />
  );
}
