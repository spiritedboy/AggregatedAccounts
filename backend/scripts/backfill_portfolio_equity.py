import asyncio

from app.database import SessionLocal
from app.services.equity_curve import backfill_portfolio_equity_points


async def main() -> None:
    async with SessionLocal() as db:
        count = await backfill_portfolio_equity_points(db)
    print(f"portfolio equity backfill completed: {count} buckets")


if __name__ == "__main__":
    asyncio.run(main())
