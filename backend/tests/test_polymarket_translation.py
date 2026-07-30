import json

import httpx
import pytest
from sqlalchemy import select

from app.api import _polymarket_asset_id, _translation_fields
from app.database import SessionLocal
from app.models import ClosedPosition, CurrentPosition, PolymarketTranslation
from app.services.polymarket_translation import (
    BaiduLLMTranslator,
    capture_polymarket_translation_sources,
    process_pending_polymarket_translations,
)


@pytest.mark.asyncio
async def test_baidu_llm_translator_uses_bearer_and_simplified_chinese():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-api-key"
        payload = json.loads(request.content)
        assert payload["appid"] == "test-appid"
        assert payload["from"] == "en"
        assert payload["to"] == "zh"
        assert "Polymarket" in payload["reference"]
        return httpx.Response(
            200,
            json={
                "from": "en",
                "to": "zh",
                "trans_result": [
                    {
                        "src": payload["q"],
                        "dst": "集成测试会通过吗？ · 是",
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    translator = BaiduLLMTranslator(
        appid="test-appid",
        api_key="test-api-key",
        endpoint="https://example.test/translate",
        timeout=1,
        client=client,
    )
    try:
        result = await translator.translate("Will the integration test pass? · Yes")
    finally:
        await client.aclose()
    assert result == "集成测试会通过吗？ · 是"


class FakeTranslator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def translate(self, text: str) -> str:
        self.calls.append(text)
        return "集成测试会通过吗？ · 是"

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_translation_is_captured_once_and_reused_by_asset_id():
    item = {
        "translation_asset_id": "stable-outcome-token",
        "translation_condition_id": "0x" + "a" * 64,
        "translation_outcome_index": 0,
        "translation_source_title": "Will the integration test pass?",
        "translation_source_outcome": "Yes",
    }
    async with SessionLocal() as db:
        assert await capture_polymarket_translation_sources(db, [item, item]) == 1
        await db.commit()

        translator = FakeTranslator()
        result = await process_pending_polymarket_translations(
            db,
            translator=translator,
        )
        assert result["translated"] == 1
        assert translator.calls == ["Will the integration test pass? · Yes"]

        row = await db.scalar(
            select(PolymarketTranslation).where(
                PolymarketTranslation.asset_id == "stable-outcome-token"
            )
        )
        assert row is not None
        assert row.status == "READY"
        assert row.translated_display == "集成测试会通过吗？ · 是"

        assert await capture_polymarket_translation_sources(db, [item]) == 0
        await db.commit()
        second = await process_pending_polymarket_translations(
            db,
            translator=FakeTranslator(),
        )
        assert second["translated"] == 0


def test_current_and_closed_positions_reuse_the_same_translation():
    translation = PolymarketTranslation(
        asset_id="stable-outcome-token",
        condition_id="0x" + "a" * 64,
        outcome_index=0,
        source_title="Will the integration test pass?",
        source_outcome="Yes",
        source_display="Will the integration test pass? · Yes",
        source_hash="a" * 64,
        translated_display="集成测试会通过吗？ · 是",
        status="READY",
    )
    current = CurrentPosition(
        exchange="POLYMARKET",
        symbol="Will the integration test pass? · Yes",
        source_record_id="stable-outcome-token",
    )
    closed = ClosedPosition(
        exchange="POLYMARKET",
        symbol="Will the integration test pass? · Yes",
        source_record_id="poly-closed:stable-outcome-token",
    )

    assert _polymarket_asset_id(current) == translation.asset_id
    assert _polymarket_asset_id(closed) == translation.asset_id
    assert (
        _translation_fields(current, translation)["display_symbol"]
        == "集成测试会通过吗？ · 是"
    )
    assert (
        _translation_fields(closed, translation)["display_symbol"]
        == "集成测试会通过吗？ · 是"
    )
