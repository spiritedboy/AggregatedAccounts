import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import PolymarketTranslation

logger = logging.getLogger("portfolio.polymarket_translation")

TRANSLATION_REFERENCE = (
    "Translate this Polymarket prediction-market position into concise Simplified Chinese. "
    "Preserve proper names, team names, ticker symbols, dates, numbers, league names, and "
    "BO1/BO3/BO5. Translate Yes as 是 and No as 否. Keep the separator · between the market "
    "question and the held outcome. Return the translation only, with no explanation."
)


class TranslationProvider(Protocol):
    async def translate(self, text: str) -> str: ...

    async def close(self) -> None: ...


class BaiduLLMTranslationError(Exception):
    """A credential-safe Baidu LLM translation failure."""


class BaiduLLMTranslator:
    def __init__(
        self,
        *,
        appid: str,
        api_key: str,
        endpoint: str,
        timeout: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.appid = appid
        self.api_key = api_key
        self.endpoint = endpoint
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=timeout)

    async def translate(self, text: str) -> str:
        try:
            response = await self.client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "appid": self.appid,
                    "from": "en",
                    "to": "zh",
                    "q": text,
                    "reference": TRANSLATION_REFERENCE,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BaiduLLMTranslationError(type(exc).__name__) from None

        error_code = int(payload.get("error_code") or 0)
        if error_code:
            safe_message = str(payload.get("error_msg") or "unknown")[:120]
            raise BaiduLLMTranslationError(f"Baidu {error_code}: {safe_message}")
        results = payload.get("trans_result")
        if not isinstance(results, list) or not results:
            raise BaiduLLMTranslationError("Baidu returned no translation")
        translated = str(results[0].get("dst") or "").strip().strip("\"'")
        if not translated:
            raise BaiduLLMTranslationError("Baidu returned an empty translation")
        return translated.replace("•", "·").replace("・", "·")

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()


def _translation_source(item: dict[str, Any]) -> dict[str, Any] | None:
    asset_id = str(item.get("translation_asset_id") or "").strip()
    title = str(item.get("translation_source_title") or "").strip()
    outcome = str(item.get("translation_source_outcome") or "").strip()
    if not asset_id or not title or not outcome:
        return None
    source_display = f"{title} · {outcome}"
    return {
        "asset_id": asset_id,
        "condition_id": str(item.get("translation_condition_id") or "")[:80],
        "outcome_index": int(item.get("translation_outcome_index") or 0),
        "source_title": title,
        "source_outcome": outcome[:320],
        "source_display": source_display,
        "source_hash": hashlib.sha256(source_display.encode("utf-8")).hexdigest(),
    }


async def capture_polymarket_translation_sources(
    db: AsyncSession,
    items: list[dict[str, Any]],
) -> int:
    sources: dict[str, dict[str, Any]] = {}
    for item in items:
        source = _translation_source(item)
        if source:
            sources[source["asset_id"]] = source
    if not sources:
        return 0

    existing_rows = (
        await db.scalars(
            select(PolymarketTranslation).where(
                PolymarketTranslation.asset_id.in_(sources)
            )
        )
    ).all()
    existing = {row.asset_id: row for row in existing_rows}
    changed = 0
    for asset_id, source in sources.items():
        row = existing.get(asset_id)
        if row is None:
            db.add(PolymarketTranslation(**source))
            changed += 1
            continue
        if row.source_hash == source["source_hash"]:
            continue
        row.condition_id = source["condition_id"]
        row.outcome_index = source["outcome_index"]
        row.source_title = source["source_title"]
        row.source_outcome = source["source_outcome"]
        row.source_display = source["source_display"]
        row.source_hash = source["source_hash"]
        row.translated_display = None
        row.status = "PENDING"
        row.attempt_count = 0
        row.last_error = None
        row.last_attempt_at = None
        changed += 1
    return changed


def _default_translator() -> BaiduLLMTranslator:
    return BaiduLLMTranslator(
        appid=settings.baidu_translation_appid,
        api_key=settings.baidu_translation_api_key,
        endpoint=settings.baidu_translation_endpoint,
        timeout=settings.baidu_translation_timeout_seconds,
    )


async def process_pending_polymarket_translations(
    db: AsyncSession,
    *,
    limit: int | None = None,
    translator: TranslationProvider | None = None,
) -> dict[str, int | bool]:
    if translator is None and (
        not settings.baidu_translation_enabled
        or not settings.baidu_translation_appid
        or not settings.baidu_translation_api_key
    ):
        return {"enabled": False, "translated": 0, "failed": 0}

    retry_before = datetime.now(UTC) - timedelta(minutes=15)
    rows = (
        await db.scalars(
            select(PolymarketTranslation)
            .where(
                PolymarketTranslation.attempt_count < 5,
                or_(
                    PolymarketTranslation.status == "PENDING",
                    and_(
                        PolymarketTranslation.status == "FAILED",
                        PolymarketTranslation.last_attempt_at < retry_before,
                    ),
                ),
            )
            .order_by(PolymarketTranslation.created_at)
            .limit(max(1, limit or settings.baidu_translation_batch_size))
            .with_for_update(skip_locked=True)
        )
    ).all()
    if not rows:
        return {"enabled": True, "translated": 0, "failed": 0}

    provider = translator or _default_translator()
    translated_count = 0
    failed_count = 0
    try:
        for row in rows:
            row.attempt_count += 1
            row.last_attempt_at = datetime.now(UTC)
            try:
                row.translated_display = await provider.translate(row.source_display)
                row.status = "READY"
                row.provider = "BAIDU_LLM"
                row.target_language = "zh"
                row.last_error = None
                translated_count += 1
            except Exception as exc:
                row.status = "FAILED"
                row.last_error = f"{type(exc).__name__}: {exc}"[:240]
                failed_count += 1
                logger.warning(
                    "polymarket translation failed asset=%s error=%s",
                    row.asset_id[-12:],
                    type(exc).__name__,
                )
        await db.commit()
    finally:
        await provider.close()
    return {
        "enabled": True,
        "translated": translated_count,
        "failed": failed_count,
    }
