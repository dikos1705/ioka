import json
import logging
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class SearchCache:
    def __init__(self, redis_url: str, ttl_seconds: int) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.ttl_seconds = ttl_seconds

    async def get(self, key: str) -> dict[str, Any] | None:
        try:
            value = await self.redis.get(f"flight-search:{key}")
            return json.loads(value) if value else None
        except Exception as exc:
            logger.warning("Redis cache read failed: %s", exc)
            return None

    async def set(self, key: str, value: dict[str, Any]) -> None:
        try:
            await self.redis.setex(f"flight-search:{key}", self.ttl_seconds, json.dumps(value))
        except Exception as exc:
            logger.warning("Redis cache write failed: %s", exc)

    async def close(self) -> None:
        await self.redis.aclose()
