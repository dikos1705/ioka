import asyncio

from app.application.search import SearchService
from app.config import get_settings
from app.infrastructure.broker import SearchBroker, consume_searches
from app.infrastructure.cache import SearchCache
from app.infrastructure.database import SessionFactory
from app.infrastructure.mock_provider import MockAirlineProvider


async def main() -> None:
    settings = get_settings()
    cache = SearchCache(settings.redis_url, settings.search_ttl_seconds)
    service = SearchService(
        SessionFactory,
        MockAirlineProvider(),
        settings,
        cache,
        SearchBroker(settings.rabbitmq_url),
    )
    try:
        await consume_searches(settings.rabbitmq_url, service.process)
    finally:
        await cache.close()


if __name__ == "__main__":
    asyncio.run(main())
