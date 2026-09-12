from datetime import UTC, datetime, timedelta

import pytest

from app.services.behavior_analytics import (
    BehaviorTrade,
    build_behavior_analysis,
    duration_bucket,
    leverage_bucket,
    open_session_bucket,
    weekday_bucket,
)

pytestmark = pytest.mark.no_db
NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


def trade(
    *,
    pnl: float = 10,
    opened: datetime | None = None,
    closed: datetime | None = None,
    leverage: float | None = 5,
    margin: float = 200,
    symbol: str = "BTC-USDT-PERP",
    side: str = "LONG",
) -> BehaviorTrade:
    close_time = closed or NOW - timedelta(hours=1)
    return BehaviorTrade(
        exchange="BINANCE",
        symbol=symbol,
        normalized_symbol=symbol,
        side=side,
        open_time=opened or close_time - timedelta(hours=2),
        close_time=close_time,
        leverage=leverage,
        margin_used=margin,
        net_pnl=pnl,
    )


def row(payload, dimension: str, key: str):
    return next(item for item in payload[dimension] if item["key"] == key)


def test_behavior_analysis_handles_no_trades():
    payload = build_behavior_analysis([], "30d", now=NOW)
    assert payload["trade_count"] == 0
    assert payload["insights"] == []
    assert all(item["trade_count"] == 0 for item in payload["duration"])


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(minutes=14, seconds=59), "lt_15m"),
        (timedelta(minutes=15), "15m_1h"),
        (timedelta(hours=1), "1h_4h"),
        (timedelta(hours=4), "4h_12h"),
        (timedelta(hours=12), "12h_1d"),
        (timedelta(days=1), "1d_3d"),
        (timedelta(days=3), "1d_3d"),
        (timedelta(days=3, seconds=1), "gt_3d"),
    ],
)
def test_duration_bucket_boundaries(delta, expected):
    assert duration_bucket(NOW - delta, NOW) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "insufficient"),
        (0, "insufficient"),
        (2, "lte_2x"),
        (2.01, "2x_5x"),
        (5, "2x_5x"),
        (5.01, "5x_10x"),
        (10, "5x_10x"),
        (10.01, "10x_20x"),
        (20, "10x_20x"),
        (20.01, "gt_20x"),
    ],
)
def test_leverage_bucket_boundaries(value, expected):
    assert leverage_bucket(value) == expected


def test_invalid_holding_times_are_counted_but_not_bucketed():
    invalid = trade(opened=NOW, closed=NOW - timedelta(hours=1))
    payload = build_behavior_analysis([invalid], "all", now=NOW)
    assert payload["trade_count"] == 1
    assert payload["data_quality"]["invalid_duration_count"] == 1
    assert sum(item["trade_count"] for item in payload["duration"]) == 0


def test_open_time_uses_asia_shanghai_for_session_and_weekday():
    opened = datetime(2026, 9, 13, 16, 30, tzinfo=UTC)
    assert open_session_bucket(opened) == "00_03"
    assert weekday_bucket(opened) == "0"


def test_profit_factor_and_payoff_ratio_cover_mixed_all_win_and_all_loss():
    mixed = build_behavior_analysis(
        [trade(pnl=value) for value in (10, 20, -5, -15)], "all", now=NOW
    )
    metrics = row(mixed, "duration", "1h_4h")
    assert metrics["profit_factor"] == pytest.approx(1.5)
    assert metrics["payoff_ratio"] == pytest.approx(1.5)
    assert metrics["win_rate"] == 50

    winners = build_behavior_analysis(
        [trade(pnl=10), trade(pnl=20)], "all", now=NOW
    )
    winner_metrics = row(winners, "duration", "1h_4h")
    assert winner_metrics["profit_factor"] is None
    assert winner_metrics["profit_factor_unbounded"] is True
    assert winner_metrics["payoff_ratio_unbounded"] is True

    losers = build_behavior_analysis(
        [trade(pnl=-10), trade(pnl=-20)], "all", now=NOW
    )
    loser_metrics = row(losers, "duration", "1h_4h")
    assert loser_metrics["profit_factor"] == 0
    assert loser_metrics["payoff_ratio"] == 0


def test_missing_leverage_and_margin_have_explicit_buckets():
    payload = build_behavior_analysis(
        [trade(leverage=None, margin=0)], "all", now=NOW
    )
    assert leverage_bucket(None) == "insufficient"
    assert row(payload, "leverage", "insufficient")["trade_count"] == 1
    assert row(payload, "position_size", "insufficient")["trade_count"] == 1
    assert payload["data_quality"]["missing_leverage_count"] == 1
    assert payload["data_quality"]["missing_margin_count"] == 1


def test_insights_require_at_least_five_trades():
    four = build_behavior_analysis([trade() for _ in range(4)], "all", now=NOW)
    assert four["insights"] == []

    five = build_behavior_analysis([trade() for _ in range(5)], "all", now=NOW)
    assert {item["code"] for item in five["insights"]} == {
        "DURATION_BEST",
        "SYMBOL_BEST",
    }
    assert all(item["trade_count"] >= 5 for item in five["insights"])


def test_period_filtering_is_rolling_and_inclusive_at_boundary():
    trades = [
        trade(closed=NOW - timedelta(days=7)),
        trade(closed=NOW - timedelta(days=7, seconds=1)),
    ]
    seven_days = build_behavior_analysis(trades, "7d", now=NOW)
    all_time = build_behavior_analysis(trades, "all", now=NOW)
    assert seven_days["trade_count"] == 1
    assert seven_days["effective_from"] == NOW - timedelta(days=7)
    assert all_time["trade_count"] == 2
