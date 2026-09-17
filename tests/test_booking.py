from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.application.booking import BookingService
from app.application.tickets import build_ticket_pdf
from app.domain.provider import ProviderTicket
from app.exceptions import ConflictError, ProviderError
from app.infrastructure.mock_provider import MockAirlineProvider
from app.infrastructure.models import Agent, BalanceTransaction
from app.schemas import OrderCreate, Passenger


def payload(offer_id: str, document_number: str = "AA1234567") -> OrderCreate:
    return OrderCreate(
        offer_id=offer_id,
        passenger=Passenger(
            first_name="Ali",
            last_name="Karimov",
            birth_date=date(1990, 1, 1),
            document_number=document_number,
            document_expiry=date.today() + timedelta(days=1000),
            citizenship="UZ",
        ),
    )


@pytest.mark.asyncio
async def test_create_and_issue_are_idempotent_and_debit_once(db):
    factory, ids = db
    service = BookingService(factory, MockAirlineProvider(delay_seconds=0))

    first = await service.create_order(ids["agent_id"], payload(ids["offer_id"]), "create-key-001")
    replay = await service.create_order(ids["agent_id"], payload(ids["offer_id"]), "create-key-001")
    assert replay.id == first.id

    issued, agent, payment_status = await service.issue_order(
        ids["agent_id"], first.id, "issue-key-001"
    )
    replay_issue, replay_agent, _ = await service.issue_order(
        ids["agent_id"], first.id, "issue-key-001"
    )

    assert issued.status == "ISSUED"
    assert replay_issue.ticket_number == issued.ticket_number
    assert payment_status == "CAPTURED"
    assert agent.balance == replay_agent.balance == Decimal("4000000.00")
    assert build_ticket_pdf(issued).startswith(b"%PDF")
    async with factory() as session:
        transactions = await session.scalar(select(func.count()).select_from(BalanceTransaction))
        assert transactions == 1


@pytest.mark.asyncio
async def test_idempotency_key_rejects_different_payload(db):
    factory, ids = db
    service = BookingService(factory, MockAirlineProvider(delay_seconds=0))
    await service.create_order(ids["agent_id"], payload(ids["offer_id"]), "create-key-002")

    with pytest.raises(ConflictError):
        await service.create_order(
            ids["agent_id"], payload(ids["offer_id"], "AA9999999"), "create-key-002"
        )


class FailingIssueProvider(MockAirlineProvider):
    async def issue(self, provider_booking_id: str, idempotency_key: str) -> ProviderTicket:
        raise RuntimeError("provider unavailable")


@pytest.mark.asyncio
async def test_failed_issue_releases_balance(db):
    factory, ids = db
    service = BookingService(factory, FailingIssueProvider(delay_seconds=0))
    order = await service.create_order(ids["agent_id"], payload(ids["offer_id"]), "create-key-003")

    with pytest.raises(ProviderError):
        await service.issue_order(ids["agent_id"], order.id, "issue-key-003")

    async with factory() as session:
        agent = await session.get(Agent, ids["agent_id"])
        transaction = await session.scalar(
            select(BalanceTransaction).where(BalanceTransaction.order_id == order.id)
        )
        assert agent.balance == Decimal("5000000.00")
        assert transaction.status == "RELEASED"
    restored = await service.get_order(ids["agent_id"], order.id)
    assert restored.status == "BOOKED"
