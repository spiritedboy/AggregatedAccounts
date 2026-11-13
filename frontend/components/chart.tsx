"use client";

import type { EChartsOption } from "echarts";
import dynamic from "next/dynamic";
import { type CSSProperties, useId } from "react";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

export function Chart({
  option,
  height = 280,
  mobileHeight = 240,
  ariaLabel = "数据图表",
  description,
}: {
  option: EChartsOption;
  height?: number;
  mobileHeight?: number;
  ariaLabel?: string;
  description?: string;
}) {
  const descriptionId = useId();
  return (
    <div
      className="responsive-chart min-w-0"
      style={{
        "--chart-height": `${height}px`,
        "--chart-mobile-height": `${mobileHeight}px`,
      } as CSSProperties}
    >
      <div role="img" aria-label={ariaLabel} aria-describedby={description ? descriptionId : undefined} className="h-full">
        <ReactECharts
          option={option}
          notMerge
          lazyUpdate
          style={{ height: "100%", width: "100%" }}
          opts={{ renderer: "svg" }}
        />
      </div>
      {description && <span id={descriptionId} className="sr-only">{description}</span>}
    </div>
  );
}
