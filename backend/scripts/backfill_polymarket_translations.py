import asyncio

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ExchangeAccount
from app.services.accounts import sync_account
from app.services.polymarket_translation import (
    process_pending_polymarket_translations,
)


async def main() -> None:
    async with SessionLocal() as db:
        accounts = (
            await db.scalars(
                select(ExchangeAccount).where(
                    ExchangeAccount.exchange == "POLYMARKET",
                    ExchangeAccount.is_active.is_(True),
                )
            )
        ).all()
        sync_results = []
        for account in accounts:
            sync_results.append(await sync_account(db, account))
        translation_result = await process_pending_polymarket_translations(
            db,
            limit=500,
        )
    print(
        {
            "accounts": len(accounts),
            "sync_results": sync_results,
            "translations": translation_result,
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
