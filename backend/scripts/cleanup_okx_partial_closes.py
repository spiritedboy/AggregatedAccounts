import argparse
import asyncio
import json

from app.database import SessionLocal
from app.services.maintenance import cleanup_okx_closed_positions


async def run(apply: bool) -> None:
    async with SessionLocal() as db:
        result = await cleanup_okx_closed_positions(db, apply=apply)
        if not apply:
            await db.rollback()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Preview or clean duplicate OKX partial-close history rows."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply cleanup. Without this flag the command is read-only.",
    )
    arguments = parser.parse_args()
    asyncio.run(run(arguments.apply))
