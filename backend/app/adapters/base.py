import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import httpx


class AdapterError(Exception):
    """A credential-safe exchange adapter error."""


class ExchangeAdapter(ABC):
    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        passphrase: str | None = None,
        wallet_address: str | None = None,
        timeout: float = 12,
    ) -> None:
        self.api_key = api_key
        self._api_secret = api_secret
        self._passphrase = passphrase
        self.wallet_address = wallet_address
        self.client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self.client.request(method, url, **kwargs)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.25 * (2**attempt))
        raise AdapterError(f"交易所只读接口请求失败：{type(last_error).__name__}") from None

    @abstractmethod
    async def test_connection(self) -> bool: ...

    @abstractmethod
    async def get_permissions(self) -> dict[str, bool | None]: ...

    @abstractmethod
    async def get_account_summary(self) -> dict[str, Any]: ...

    @abstractmethod
    async def get_balances(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_open_positions(self) -> list[dict[str, Any]]: ...

    async def get_closed_positions(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        return []

    async def get_income_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        return []

    async def get_funding_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        return []

    async def get_fee_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        return []

    async def get_cash_flow_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        return []

    async def get_mark_prices(self, symbols: list[str]) -> dict[str, float]:
        return {}
