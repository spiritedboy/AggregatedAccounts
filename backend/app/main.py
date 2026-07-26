import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api import router
from app.config import settings
from app.database import SessionLocal
from app.models import ExchangeAccount
from app.schemas import envelope
from app.services.accounts import sync_account
from app.services.configured_accounts import provision_configured_accounts
from app.services.demo import seed_demo_data
from app.services.maintenance import apply_data_retention

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("portfolio")
scheduler = AsyncIOScheduler(timezone="UTC")


async def scheduled_sync() -> None:
    async with SessionLocal() as db:
        account_ids = (
            await db.scalars(select(ExchangeAccount.id).where(ExchangeAccount.is_active.is_(True)))
        ).all()

    async def run_one(account_id):
        async with SessionLocal() as account_db:
            account = await account_db.get(ExchangeAccount, account_id)
            return await sync_account(account_db, account)

    results = await asyncio.gather(
        *(run_one(account_id) for account_id in account_ids),
        return_exceptions=True,
    )
    logger.info("scheduled account refresh completed accounts=%s", len(results))


async def scheduled_retention() -> None:
    async with SessionLocal() as db:
        result = await apply_data_retention(db)
    logger.info("scheduled data retention completed result=%s", result)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.demo_mode:
        async with SessionLocal() as db:
            await seed_demo_data(db)
    async with SessionLocal() as db:
        configured = await provision_configured_accounts(db)
        logger.info("configured account provisioning completed result=%s", configured)
    if settings.app_env != "test":
        scheduler.add_job(
            scheduled_sync,
            "interval",
            seconds=max(settings.sync_balance_seconds, 30),
            id="portfolio-sync",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        scheduler.add_job(
            scheduled_retention,
            "cron",
            hour=min(max(settings.maintenance_hour_utc, 0), 23),
            minute=min(max(settings.maintenance_minute_utc, 0), 59),
            id="data-retention",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        scheduler.start()
    yield
    if settings.app_env != "test":
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="多交易所账户资产聚合平台",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)
app.include_router(router)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(data=None, error={"message": exc.detail}, success=False),
    )


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors: list[dict[str, Any]] = []
    for item in exc.errors():
        errors.append(
            {
                "field": ".".join(str(part) for part in item["loc"] if part != "body"),
                "message": item["msg"],
            }
        )
    return JSONResponse(
        status_code=422,
        content=envelope(
            data=None, error={"message": "请求参数无效", "fields": errors}, success=False
        ),
    )
