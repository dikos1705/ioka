import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.application.search import SearchService
from app.config import Settings
from app.domain.provider import ProviderSearchRequest
from app.infrastructure.mock_provider import MockAirlineProvider
from app.infrastructure.models import FlightSearch


@pytest.mark.asyncio
async def test_search_worker_completes_and_saves_offers(db):
    factory, ids = db
    settings = Settings(_env_file=None, search_timeout_seconds=2)
    service = SearchService(factory, MockAirlineProvider(delay_seconds=0), settings)
    async with factory() as session:
        search = await session.get(FlightSearch, ids["search_id"])
        search.status = "PENDING"
        await session.commit()

    await service.process(ids["search_id"])
    result = await service.get(ids["search_id"], ids["agent_id"])

    assert result.status == "COMPLETED"
    assert len(result.offers) == 4  # seeded offer plus three provider offers


class SlowProvider(MockAirlineProvider):
    async def search(self, request: ProviderSearchRequest):
        await asyncio.sleep(0.05)
        return []


@pytest.mark.asyncio
async def test_search_timeout_is_persisted(db):
    factory, ids = db
    settings = Settings(_env_file=None, search_timeout_seconds=0.001)
    service = SearchService(factory, SlowProvider(), settings)
    async with factory() as session:
        search = await session.scalar(select(FlightSearch).where(FlightSearch.id == ids["search_id"]))
        search.status = "PENDING"
        search.expires_at += timedelta(minutes=1)
        await session.commit()

    await service.process(ids["search_id"])
    result = await service.get(ids["search_id"], ids["agent_id"])

    assert result.status == "TIMED_OUT"
    assert result.error_code == "provider_timeout"
