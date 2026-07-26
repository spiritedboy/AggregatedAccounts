from app.adapters import ADAPTERS
from app.adapters.base import ExchangeAdapter


def test_all_registered_adapters_implement_closed_positions():
    for name, adapter_type in ADAPTERS.items():
        assert (
            adapter_type.get_closed_positions
            is not ExchangeAdapter.get_closed_positions
        ), f"{name} must implement get_closed_positions"


def test_history_capabilities_have_concrete_implementations():
    method_by_stream = {
        "income": "get_income_history",
        "funding": "get_funding_history",
        "fees": "get_fee_history",
        "cash_flows": "get_cash_flow_history",
    }
    for name, adapter_type in ADAPTERS.items():
        for stream in adapter_type.history_streams:
            method_name = method_by_stream[stream]
            assert getattr(adapter_type, method_name) is not getattr(
                ExchangeAdapter, method_name
            ), f"{name} declares {stream} but does not implement {method_name}"
