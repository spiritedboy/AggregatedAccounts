"""Checks for the host-level closed-position PnL reporter."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch
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
        ]
        summary = report.summarize(rows)
        self.assertEqual(summary["net"], Decimal("5.75"))
        self.assertEqual((summary["wins"], summary["losses"]), (1, 1))
        self.assertEqual(report.summarize([])["net"], Decimal(0))

    def test_all_partial_records_are_counted_without_notice(self):
        summary = report.summarize([
            {"net_pnl": "-1", "exchange": "OKX", "data_completeness": "PARTIAL"},
            {"net_pnl": "2", "exchange": "BINANCE", "data_completeness": "PARTIAL"},
        ])
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["net"], Decimal("1"))
        payload = report.card(date(2026, 11, 10), summary, "https://www.bitboy.cn")
        self.assertNotIn("部分完整", str(payload))
        self.assertNotIn("口径", str(payload))

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
        self.assertIn("🔴", elements[0]["content"])
        self.assertIn("-12.34 USDT", elements[0]["content"])
        self.assertIn("\n\n", elements[0]["content"])
        self.assertNotIn("持平", str(payload))
        self.assertNotIn("口径", str(payload))
        self.assertIn("start=2026-11-10&end=2026-11-10&page_size=50",
                      elements[-1]["behaviors"][0]["default_url"])

    def test_profit_card_is_green_and_binance_partial_is_not_warned(self):
        summary = report.summarize([
            {"net_pnl": "12.34", "exchange": "BINANCE", "data_completeness": "PARTIAL"},
        ])
        payload = report.card(date(2026, 11, 10), summary, "https://www.bitboy.cn")
        self.assertEqual(payload["card"]["header"]["template"], "green")
        self.assertIn("🟢", payload["card"]["body"]["elements"][0]["content"])
        self.assertNotIn("⚠️", str(payload))

    def test_feishu_rejection_reports_safe_code_and_retries(self):
        response = io.BytesIO(json.dumps({"code": 19021, "msg": "temporary error at https://example.test/private-token"}).encode())
        with patch.object(report, "urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "code=19021") as caught:
                report.send_card("https://example.test/webhook", {"msg_type": "interactive"})
        self.assertNotIn("private-token", str(caught.exception))

        send = Mock(side_effect=[ValueError("temporary"), ValueError("temporary"), None])
        sleep = Mock()
        report.send_with_retry("webhook", {}, send=send, sleep=sleep)
        self.assertEqual(send.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [3, 10])

    def test_success_marker_skips_scheduled_retry_but_explicit_date_resends(self):
        day = date(2026, 11, 15)
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            report.mark_sent(day, state_dir)
            self.assertTrue(report.sent_marker(day, state_dir).exists())
            with patch.dict(os.environ, {"DAILY_PNL_STATE_DIR": directory, "FEISHU_DAILY_PNL_WEBHOOK_URL": "https://example.test/pnl", "FEISHU_HEALTH_WEBHOOK_URL": "https://example.test/health"}), \
                 patch.object(report, "report_date", return_value=day), \
                 patch.object(report, "load_positions", return_value=[]), \
                 patch.object(report, "send_with_retry") as send, \
                 patch.object(sys, "argv", ["daily-pnl-report.py"]):
                self.assertEqual(report.main(), 0)
                send.assert_not_called()
                with patch.object(sys, "argv", ["daily-pnl-report.py", "--date", day.isoformat()]):
                    self.assertEqual(report.main(), 0)
                send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
