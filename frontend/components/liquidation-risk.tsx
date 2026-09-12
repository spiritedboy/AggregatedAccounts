"use client";

import { CalculationHint } from "@/components/calculation-hint";
import { Badge } from "@/components/ui";
import { number, usd } from "@/lib/format";
import type { LiquidationRiskLevel } from "@/lib/types";

const riskLabels: Record<LiquidationRiskLevel, string> = {
  SAFE: "安全",
  WATCH: "关注",
  DANGER: "危险",
};

const riskTones: Record<LiquidationRiskLevel, "positive" | "warning" | "negative"> = {
  SAFE: "positive",
  WATCH: "warning",
  DANGER: "negative",
};

export function liquidationRiskLabel(level: LiquidationRiskLevel | null) {
  return level ? riskLabels[level] : "无强平数据";
}

export function liquidationRiskTone(level: LiquidationRiskLevel | null) {
  return level ? riskTones[level] : "neutral";
}

export function LiquidationRiskDisplay({
  liquidationPrice,
  distancePercent,
  riskLevel,
  marginMode,
  compact = false,
}: {
  liquidationPrice: number | null;
  distancePercent: number | null;
  riskLevel: LiquidationRiskLevel | null;
  marginMode: string;
  compact?: boolean;
}) {
  if (liquidationPrice === null || distancePercent === null || riskLevel === null) {
    return <p className="max-w-40 text-xs leading-5 text-[var(--muted)]">交易所未提供可靠强平价</p>;
  }

  const isCross = marginMode.toUpperCase() === "CROSS";
  return (
    <div className={compact ? "space-y-1.5" : "space-y-1"}>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mono-number text-sm font-semibold">{usd(liquidationPrice)}</span>
        {isCross ? (
          <CalculationHint
            label="全仓强平价"
            text="该强平价由交易所返回。全仓模式会随账户权益、其他仓位、资金费和保证金变化而动态调整。"
          />
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`mono-number text-xs font-semibold ${riskLevel === "SAFE" ? "text-positive" : riskLevel === "WATCH" ? "text-warning" : "text-negative"}`}>
          距强平 {number(distancePercent, 1)}%
        </span>
        <Badge tone={riskTones[riskLevel]}>{riskLabels[riskLevel]}</Badge>
      </div>
    </div>
  );
}
