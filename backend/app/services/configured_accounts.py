import json
import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import ExchangeAccount
from app.schemas import ExchangeAccountCreate
from app.services.accounts import create_account

logger = logging.getLogger("portfolio.configured_accounts")


def _environment_value(item: dict[str, Any], field: str) -> str | None:
    environment_name = item.get(f"{field}_env")
    if not environment_name:
        return None
    value = os.getenv(str(environment_name), "").strip()
    return value or None


def load_account_definitions(path: str | None = None) -> list[dict[str, Any]]:
    config_path = Path(path or settings.exchange_accounts_config)
    if not config_path.exists():
        logger.warning("exchange account config not found path=%s", config_path)
        return []
    document = json.loads(config_path.read_text(encoding="utf-8"))
    accounts = document.get("accounts", [])
    if not isinstance(accounts, list):
        raise ValueError("exchange account config field 'accounts' must be a list")
    return accounts


async def provision_configured_accounts(
    db: AsyncSession, path: str | None = None
) -> dict[str, int]:
    result = {"configured": 0, "created": 0, "existing": 0, "skipped": 0, "failed": 0}
    for item in load_account_definitions(path):
        result["configured"] += 1
        if not item.get("enabled", False):
            result["skipped"] += 1
            continue
        try:
            exchange = str(item["exchange"]).upper()
            connection_name = str(item["connection_name"])
            existing = await db.scalar(
                select(ExchangeAccount).where(
                    ExchangeAccount.exchange == exchange,
                    ExchangeAccount.connection_name == connection_name,
                    ExchangeAccount.is_active.is_(True),
                )
            )
            if existing:
                result["existing"] += 1
                continue
            payload = ExchangeAccountCreate(
                exchange=exchange,
                connection_name=connection_name,
                api_key=_environment_value(item, "api_key"),
                api_secret=_environment_value(item, "api_secret"),
                passphrase=_environment_value(item, "passphrase"),
                wallet_address=_environment_value(item, "wallet_address"),
            )
            await create_account(db, payload, "CONFIG_FILE")
            result["created"] += 1
        except Exception as exc:
            await db.rollback()
            result["failed"] += 1
            logger.error(
                "configured account provisioning failed exchange=%s name=%s error=%s",
                item.get("exchange", "UNKNOWN"),
                item.get("connection_name", "UNKNOWN"),
                type(exc).__name__,
            )
    return result
