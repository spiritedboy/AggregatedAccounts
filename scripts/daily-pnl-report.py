#!/usr/bin/env python3
"""Send yesterday's Beijing-time closed-position PnL to a separate Feishu bot."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


BEIJING = ZoneInfo("Asia/Shanghai")
PAGE_SIZE = 50


def report_date(now: datetime | None = None) -> date:
    return (now or datetime.now(BEIJING)).astimezone(BEIJING).date() - timedelta(days=1)


def history_params(day: date, page: int) -> dict[str, str]:
    start = datetime.combine(day, time.min, BEIJING)
    end = datetime.combine(day + timedelta(days=1), time.min, BEIJING) - timedelta(microseconds=1)
    return {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "page": str(page),
        "page_size": str(PAGE_SIZE),
    }


def get_json(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def load_positions(day: date, api_base_url: str, get=get_json) -> list[dict]:
    """Read every page; refuse to report if pagination changed mid-read."""
    base = api_base_url.rstrip("/")
    for _attempt in range(2):
        items: list[dict] = []
        seen: set[str] = set()
        expected: int | None = None
        page = 1
        inconsistent = False
        while True:
            url = f"{base}/api/positions/history?{urlencode(history_params(day, page))}"
            payload = get(url)
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise ValueError("历史仓位接口响应格式异常")
            total = data.get("total")
            if not isinstance(total, int) or total < 0:
                raise ValueError("历史仓位总数无效")
            if expected is None:
                expected = total
            elif expected != total:
                inconsistent = True
                break
            batch = data["items"]
            if len(batch) > PAGE_SIZE or (not batch and len(items) < expected):
                inconsistent = True
                break
            for row in batch:
                if not isinstance(row, dict) or not row.get("id") or str(row["id"]) in seen:
                    inconsistent = True
                    break
                seen.add(str(row["id"]))
                items.append(row)
            if inconsistent:
                break
            if len(items) >= expected:
                if len(items) != expected:
                    inconsistent = True
                break
            page += 1
        if not inconsistent:
            return items
    raise ValueError("分页期间历史仓位发生变化，未发送可能不完整的日报")


def amount(row: dict, key: str) -> Decimal:
    value = row.get(key)
    if value is None:
        raise ValueError(f"历史仓位缺少 {key}，未发送日报")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"历史仓位 {key} 无效，未发送日报") from exc
    if not result.is_finite():
        raise ValueError(f"历史仓位 {key} 非有限数字，未发送日报")
    return result


def summarize(rows: list[dict]) -> dict:
    wins = losses = flats = 0
    profit = loss = Decimal(0)
    exchanges: dict[str, dict] = defaultdict(lambda: {"count": 0, "net": Decimal(0)})
    partial = 0
    for row in rows:
        pnl = amount(row, "net_pnl")
        exchange = str(row.get("exchange") or "未知交易所")
        exchanges[exchange]["count"] += 1
        exchanges[exchange]["net"] += pnl
        if pnl > 0:
            wins += 1
            profit += pnl
        elif pnl < 0:
            losses += 1
            loss -= pnl
        else:
            flats += 1
        if row.get("data_completeness") == "PARTIAL":
            partial += 1
    return {
        "count": len(rows), "wins": wins, "losses": losses, "flats": flats,
        "profit": profit, "loss": loss, "net": profit - loss,
        "exchanges": dict(sorted(exchanges.items())), "partial": partial,
    }


def money(value: Decimal, *, signed: bool = True) -> str:
    return f"{value:+,.2f}" if signed else f"{value:,.2f}"


def card(day: date, summary: dict, public_url: str) -> dict:
    net = summary["net"]
    template = "green" if net > 0 else "red" if net < 0 else "blue"
    lines = [
        f"**已平仓净收益：{money(net)} USDT**",
        f"平仓 {summary['count']} 笔｜盈利 {summary['wins']}｜亏损 {summary['losses']}｜持平 {summary['flats']}",
        f"盈利合计 +{money(summary['profit'], signed=False)}｜亏损合计 -{money(summary['loss'], signed=False)} USDT",
    ]
    if summary["exchanges"]:
        lines += ["**按交易所**"]
        for exchange, values in summary["exchanges"].items():
            lines.append(f"{exchange}：{money(values['net'])} USDT（{values['count']} 笔）")
    if summary["partial"]:
        lines.append(f"⚠️ {summary['partial']} 笔记录标记为部分完整，金额仅供参考")
    lines.append("口径：北京时间当日平仓的历史仓位 net_pnl 之和；不含未平仓收益、充值或提现，不等于账户当日权益变化。")
    history_url = f"{public_url.rstrip('/')}/history?{urlencode({'start': day.isoformat(), 'end': day.isoformat(), 'page_size': PAGE_SIZE})}"
    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "header": {"title": {"tag": "plain_text", "content": f"Atlas Ledger 平仓收益日报 · {day.isoformat()}"}, "template": template},
            "body": {"direction": "vertical", "padding": "12px", "elements": [
                {"tag": "markdown", "content": "\n".join(f"• {line}" for line in lines), "text_align": "left"},
                {"tag": "button", "text": {"tag": "plain_text", "content": "查看当日历史仓位"},
                 "type": "default", "width": "fill", "behaviors": [{"type": "open_url", "default_url": history_url}]},
            ]},
        },
    }


def send_card(webhook: str, payload: dict) -> None:
    request = Request(webhook, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    with urlopen(request, timeout=20) as response:
        result = json.load(response)
    if result.get("code", result.get("StatusCode")) != 0:
        raise ValueError("飞书返回非成功状态")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, help="指定北京时间日期；默认昨天")
    parser.add_argument("--no-send", action="store_true", help="仅预览汇总，不推送")
    args = parser.parse_args()
    day = args.date or report_date()
    api_base = os.getenv("DAILY_PNL_API_BASE_URL", "http://127.0.0.1:8000")
    public_url = os.getenv("DAILY_PNL_PUBLIC_URL", "https://www.bitboy.cn")
    webhook = os.getenv("FEISHU_DAILY_PNL_WEBHOOK_URL", "")
    if not args.no_send:
        if not webhook:
            raise ValueError("未配置 FEISHU_DAILY_PNL_WEBHOOK_URL")
        if webhook == os.getenv("FEISHU_HEALTH_WEBHOOK_URL"):
            raise ValueError("收益日报不能复用健康巡检 Webhook")
    rows = load_positions(day, api_base)
    summary = summarize(rows)
    print(f"{day.isoformat()} 北京时间 | 平仓 {summary['count']} 笔 | 净收益 {money(summary['net'])} USDT")
    if not args.no_send:
        send_card(webhook, card(day, summary, public_url))
        print("飞书收益日报发送成功")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (HTTPError, URLError, ValueError, KeyError) as exc:
        print(f"每日收益汇总失败：{exc}", file=sys.stderr)
        sys.exit(2)
