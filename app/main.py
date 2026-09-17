import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.routes import health_router, router
from app.application.booking import BookingService
from app.application.search import SearchService
from app.config import get_settings
from app.exceptions import AppError
from app.infrastructure.broker import SearchBroker
from app.infrastructure.cache import SearchCache
from app.infrastructure.database import SessionFactory, create_schema, engine
from app.infrastructure.mock_provider import MockAirlineProvider
from app.infrastructure.models import Agent
from app.security import hash_password

settings = get_settings()
logging.basicConfig(level=settings.log_level)


async def seed_default_agent() -> None:
    async with SessionFactory() as session:
        agent = await session.scalar(select(Agent).where(Agent.email == settings.default_agent_email.lower()))
        if agent:
            return
        session.add(
            Agent(
                email=settings.default_agent_email.lower(),
                password_hash=hash_password(settings.default_agent_password),
                balance=settings.default_agent_balance,
                currency="UZS",
            )
        )
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_schema:
        await create_schema()
    await seed_default_agent()
    provider = MockAirlineProvider()
    cache = SearchCache(settings.redis_url, settings.search_ttl_seconds)
    broker = SearchBroker(settings.rabbitmq_url)
    app.state.search_cache = cache
    app.state.search_service = SearchService(SessionFactory, provider, settings, cache, broker)
    app.state.booking_service = BookingService(SessionFactory, provider, settings)
    yield
    await cache.close()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Agent API for asynchronous flight search, booking, issuing and PDF tickets.",
    lifespan=lifespan,
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "details": exc.details},
    )


app.include_router(health_router)
app.include_router(router)
