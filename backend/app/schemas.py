import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ExchangeName = Literal[
    "BINANCE", "OKX", "BITGET", "BYBIT", "HYPERLIQUID", "POLYMARKET"
]


class ExchangeAccountCreate(BaseModel):
    exchange: ExchangeName
    connection_name: str = Field(min_length=2, max_length=80)
    api_key: str | None = Field(default=None, min_length=8, max_length=256)
    api_secret: str | None = Field(default=None, min_length=8, max_length=256)
    passphrase: str | None = Field(default=None, min_length=1, max_length=256)
    wallet_address: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_exchange_fields(self) -> "ExchangeAccountCreate":
        if self.exchange in {"HYPERLIQUID", "POLYMARKET"}:
            if not self.wallet_address or not re.fullmatch(
                r"0x[a-fA-F0-9]{40}", self.wallet_address
            ):
                raise ValueError(f"{self.exchange} 需要有效的 42 位公开钱包地址")
            if self.api_key:
                raise ValueError(f"{self.exchange} 只读查询不接受 API Key")
            if self.api_secret or self.passphrase:
                raise ValueError(f"{self.exchange} 只读查询不接受私钥、助记词或密码")
        else:
            if not self.api_key or not self.api_secret:
                raise ValueError(f"{self.exchange} 需要 API Key 和 API Secret")
            if self.exchange in {"OKX", "BITGET"} and not self.passphrase:
                raise ValueError(f"{self.exchange} 需要 Passphrase")
        return self


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exchange: str
    connection_name: str
    masked_identifier: str
    is_active: bool
    is_demo: bool
    connection_status: str
    permission_status: dict[str, Any]
    data_completeness: str
    tracking_started_at: datetime
    last_synced_at: datetime | None


class QueryFilters(BaseModel):
    exchange: str | None = None
    account_id: uuid.UUID | None = None
    tracking_period_id: uuid.UUID | None = None
    symbol: str | None = None
    side: Literal["LONG", "SHORT"] | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)


def envelope(data: Any = None, error: Any = None, success: bool = True) -> dict[str, Any]:
    return {
        "success": success,
        "data": data,
        "error": error,
        "timestamp": datetime.now().astimezone().isoformat(),
    }
