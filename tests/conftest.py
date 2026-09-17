from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.database import Base
from app.infrastructure.models import Agent, FlightSearch, Offer
from app.security import hash_password


@pytest_asyncio.fixture
async def db(tmp_path):
    database_path = (tmp_path / "test.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with factory() as session:
        agent = Agent(
            email="test@example.com",
            password_hash=hash_password("Secret123!"),
            balance=Decimal("5000000.00"),
            currency="UZS",
        )
        session.add(agent)
        await session.flush()
        search = FlightSearch(
            agent_id=agent.id,
            origin="TAS",
            destination="IST",
            departure_date=date.today() + timedelta(days=30),
            adults=1,
            cabin_class="ECONOMY",
            status="COMPLETED",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            completed_at=datetime.now(UTC),
        )
        session.add(search)
        await session.flush()
        offer = Offer(
            search_id=search.id,
            provider="mock-air",
            provider_offer_id="offer-1",
            origin="TAS",
            destination="IST",
            departure_at=datetime.now(UTC) + timedelta(days=30),
            arrival_at=datetime.now(UTC) + timedelta(days=30, hours=4),
            carrier="Ioka Airways",
            flight_number="IO210",
            fare_family="FLEX",
            baggage="Checked baggage 23 kg",
            total_amount=Decimal("1000000.00"),
            currency="UZS",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            raw_payload={"refundable": True},
        )
        session.add(offer)
        await session.commit()
        ids = {"agent_id": agent.id, "search_id": search.id, "offer_id": offer.id}

    yield factory, ids
    await engine.dispose()
