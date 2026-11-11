"""Checks for the host-level closed-position PnL reporter."""

import importlib.util
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse


SCRIPT = Path(__file__).resolve().parents[1] / "daily-pnl-report.py"
SPEC = importlib.util.spec_from_file_location("daily_pnl_report", SCRIPT)
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


class DailyPnlReportTests(unittest.TestCase):
    def test_report_uses_previous_beijing_day(self):
        now = datetime(2026, 11, 10, 17, 0, tzinfo=timezone.utc)
        self.assertEqual(report.report_date(now), date(2026, 11, 10))
        params = report.history_params(date(2026, 11, 10), 1)
        self.assertEqual(params["start_time"], "2026-11-10T00:00:00+08:00")
        self.assertEqual(params["end_time"], "2026-11-10T23:59:59.999999+08:00")

    def test_fetches_all_pages_not_only_first_50(self):
        calls = []

        def get(url):
            query = parse_qs(urlparse(url).query)
            page = int(query["page"][0])
            calls.append(page)
            count = 50 if page == 1 else 3
            start = (page - 1) * 50
            return {"data": {"total": 53, "items": [
                {"id": str(i), "net_pnl": 1, "exchange": "OKX"}
                for i in range(start, start + count)
            ]}}

        rows = report.load_positions(date(2026, 11, 10), "http://127.0.0.1:8000", get)
        self.assertEqual(len(rows), 53)
        self.assertEqual(calls, [1, 2])

    def test_mutating_pages_do_not_produce_partial_report(self):
        def get(url):
            page = int(parse_qs(urlparse(url).query)["page"][0])
            return {"data": {"total": 51, "items": [
                {"id": str(i), "net_pnl": 1}
                for i in (range(50) if page == 1 else [0])
            ]}}

        with self.assertRaisesRegex(ValueError, "分页期间"):
            report.load_positions(date(2026, 11, 10), "http://localhost:8000", get)

    def test_negative_pnl_and_no_trades(self):
        rows = [
            {"net_pnl": "10.25", "exchange": "OKX"},
            {"net_pnl": "-4.50", "exchange": "BINANCE", "data_completeness": "PARTIAL"},
            {"net_pnl": "0", "exchange": "OKX"},
        ]
        summary = report.summarize(rows)
        self.assertEqual(summary["net"], Decimal("5.75"))
        self.assertEqual((summary["wins"], summary["losses"], summary["flats"]), (1, 1, 1))
        self.assertEqual(summary["partial"], 1)
        self.assertEqual(report.summarize([])["net"], Decimal(0))

    def test_missing_financial_value_rejected(self):
        with self.assertRaisesRegex(ValueError, "缺少 net_pnl"):
            report.summarize([{"exchange": "OKX"}])

    def test_card_has_mobile_layout_and_history_link(self):
        summary = report.summarize([{"net_pnl": "-12.34", "exchange": "BYBIT"}])
        payload = report.card(date(2026, 11, 10), summary, "https://www.bitboy.cn")
        self.assertEqual(payload["msg_type"], "interactive")
        self.assertEqual(payload["card"]["header"]["template"], "red")
        elements = payload["card"]["body"]["elements"]
        self.assertEqual(elements[0]["tag"], "markdown")
        self.assertIn("已平仓净收益：-12.34", elements[0]["content"])
        self.assertIn("start=2026-11-10&end=2026-11-10&page_size=50",
                      elements[1]["behaviors"][0]["default_url"])


if __name__ == "__main__":
    unittest.main()
