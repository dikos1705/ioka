import asyncio
import logging
from datetime import timedelta
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.application.common import ensure_aware, request_hash, utcnow
from app.config import Settings
from app.domain.enums import SearchStatus
from app.domain.provider import AirlineProvider, ProviderSearchRequest
from app.exceptions import NotFoundError
from app.infrastructure.audit import add_provider_audit, add_status_audit
from app.infrastructure.broker import SearchBroker
from app.infrastructure.cache import SearchCache
from app.infrastructure.models import FlightSearch, Offer
from app.schemas import SearchRequest

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider: AirlineProvider,
        settings: Settings,
        cache: SearchCache | None = None,
        broker: SearchBroker | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.settings = settings
        self.cache = cache
        self.broker = broker

    async def start(self, agent_id: str, payload: SearchRequest) -> FlightSearch:
        cache_key = request_hash({"agent_id": agent_id, **payload.model_dump(mode="json")})
        if self.cache:
            cached = await self.cache.get(cache_key)
            if cached:
                async with self.session_factory() as session:
                    existing = await session.get(FlightSearch, cached.get("search_id"))
                    if existing and ensure_aware(existing.expires_at) > utcnow():
                        return existing

        search = FlightSearch(
            agent_id=agent_id,
            origin=payload.origin,
            destination=payload.destination,
            departure_date=payload.departure_date,
            adults=payload.adults,
            cabin_class=payload.cabin_class,
            status=SearchStatus.PENDING,
            expires_at=utcnow() + timedelta(seconds=self.settings.search_ttl_seconds),
        )
        async with self.session_factory() as session:
            session.add(search)
            await session.flush()
            add_status_audit(
                session,
                entity_type="flight_search",
                entity_id=search.id,
                action="search_created",
                before=None,
                after=SearchStatus.PENDING,
            )
            await session.commit()

        if self.cache:
            await self.cache.set(cache_key, {"search_id": search.id})
        if self.settings.search_dispatch_mode == "rabbitmq":
            if not self.broker:
                raise RuntimeError("RabbitMQ dispatch selected without a broker")
            await self.broker.publish(search.id)
        else:
            asyncio.create_task(self.process(search.id))
        return search

    async def process(self, search_id: str) -> None:
        async with self.session_factory() as session:
            search = await session.get(FlightSearch, search_id, with_for_update=True)
            final_statuses = {
                SearchStatus.COMPLETED,
                SearchStatus.FAILED,
                SearchStatus.TIMED_OUT,
            }
            if not search or search.status in final_statuses:
                return
            before = search.status
            search.status = SearchStatus.IN_PROGRESS
            add_status_audit(
                session,
                entity_type="flight_search",
                entity_id=search.id,
                action="provider_search_started",
                before=before,
                after=search.status,
            )
            await session.commit()
            request = ProviderSearchRequest(
                origin=search.origin,
                destination=search.destination,
                departure_date=search.departure_date,
                adults=search.adults,
                cabin_class=search.cabin_class,
            )

        started = perf_counter()
        try:
            offers = await asyncio.wait_for(
                self.provider.search(request),
                timeout=self.settings.search_timeout_seconds,
            )
            duration_ms = int((perf_counter() - started) * 1000)
            async with self.session_factory() as session:
                search = await session.get(FlightSearch, search_id, with_for_update=True)
                if not search:
                    return
                for item in offers:
                    session.add(
                        Offer(
                            search_id=search.id,
                            provider=self.provider.name,
                            provider_offer_id=item.provider_offer_id,
                            origin=item.origin,
                            destination=item.destination,
                            departure_at=item.departure_at,
                            arrival_at=item.arrival_at,
                            carrier=item.carrier,
                            flight_number=item.flight_number,
                            fare_family=item.fare_family,
                            baggage=item.baggage,
                            total_amount=item.total_amount,
                            currency=item.currency,
                            expires_at=item.expires_at,
                            raw_payload=item.raw_payload,
                        )
                    )
                before = search.status
                search.status = SearchStatus.COMPLETED
                search.completed_at = utcnow()
                add_provider_audit(
                    session,
                    action="search",
                    entity_type="flight_search",
                    entity_id=search.id,
                    request_payload={
                        "origin": request.origin,
                        "destination": request.destination,
                        "departure_date": request.departure_date.isoformat(),
                        "adults": request.adults,
                        "cabin_class": request.cabin_class,
                    },
                    response_payload={"offers_count": len(offers)},
                    duration_ms=duration_ms,
                    status_code=200,
                )
                add_status_audit(
                    session,
                    entity_type="flight_search",
                    entity_id=search.id,
                    action="provider_search_completed",
                    before=before,
                    after=search.status,
                )
                await session.commit()
        except Exception as exc:
            timed_out = isinstance(exc, TimeoutError)
            duration_ms = int((perf_counter() - started) * 1000)
            async with self.session_factory() as session:
                search = await session.get(FlightSearch, search_id, with_for_update=True)
                if not search:
                    return
                before = search.status
                search.status = SearchStatus.TIMED_OUT if timed_out else SearchStatus.FAILED
                search.error_code = "provider_timeout" if timed_out else "provider_error"
                search.error_message = str(exc) or type(exc).__name__
                add_provider_audit(
                    session,
                    action="search",
                    entity_type="flight_search",
                    entity_id=search.id,
                    request_payload={
                        "origin": request.origin,
                        "destination": request.destination,
                        "departure_date": request.departure_date.isoformat(),
                        "adults": request.adults,
                        "cabin_class": request.cabin_class,
                    },
                    response_payload=None,
                    duration_ms=duration_ms,
                    status_code=504 if timed_out else 502,
                    error_message=search.error_message,
                )
                add_status_audit(
                    session,
                    entity_type="flight_search",
                    entity_id=search.id,
                    action="provider_search_failed",
                    before=before,
                    after=search.status,
                )
                await session.commit()
            logger.exception("Flight search %s failed", search_id)

    async def get(self, search_id: str, agent_id: str) -> FlightSearch:
        async with self.session_factory() as session:
            result = await session.scalar(
                select(FlightSearch)
                .options(selectinload(FlightSearch.offers))
                .where(FlightSearch.id == search_id, FlightSearch.agent_id == agent_id)
            )
            if not result:
                raise NotFoundError("Search not found")
            return result
