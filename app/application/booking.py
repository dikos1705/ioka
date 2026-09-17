import asyncio
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.common import ensure_aware, request_hash, utcnow
from app.config import Settings
from app.domain.enums import OrderStatus, PaymentStatus
from app.domain.provider import AirlineProvider
from app.exceptions import ConflictError, InsufficientBalanceError, NotFoundError, ProviderError
from app.infrastructure.audit import add_provider_audit, add_status_audit
from app.infrastructure.models import (
    Agent,
    BalanceTransaction,
    FlightSearch,
    IdempotencyRecord,
    Offer,
    Order,
)
from app.schemas import OrderCreate


class BookingService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider: AirlineProvider,
        settings: Settings | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.provider_timeout_seconds = settings.provider_timeout_seconds if settings else 15

    async def create_order(
        self,
        agent_id: str,
        payload: OrderCreate,
        idempotency_key: str,
    ) -> Order:
        payload_hash = request_hash(payload.model_dump(mode="json"))
        replay = await self._idempotent_order(agent_id, "create_order", idempotency_key, payload_hash)
        if replay:
            return replay

        async with self.session_factory() as session:
            offer = await session.scalar(
                select(Offer)
                .join(FlightSearch)
                .where(Offer.id == payload.offer_id, FlightSearch.agent_id == agent_id)
            )
            if not offer:
                raise NotFoundError("Offer not found")
            if ensure_aware(offer.expires_at) <= utcnow():
                raise ConflictError("Offer has expired")

        started = perf_counter()
        try:
            booking = await asyncio.wait_for(
                self.provider.book(
                    offer.provider_offer_id,
                    payload.passenger.model_dump(mode="json"),
                    idempotency_key,
                ),
                timeout=self.provider_timeout_seconds,
            )
        except Exception as exc:
            duration_ms = int((perf_counter() - started) * 1000)
            async with self.session_factory() as session:
                add_provider_audit(
                    session,
                    action="book",
                    entity_type="offer",
                    entity_id=offer.id,
                    request_payload={"offer_id": offer.id, "idempotency_key": idempotency_key},
                    response_payload=None,
                    duration_ms=duration_ms,
                    status_code=504 if isinstance(exc, TimeoutError) else 502,
                    error_message=str(exc) or type(exc).__name__,
                )
                await session.commit()
            raise ProviderError("Airline provider rejected the booking") from exc
        duration_ms = int((perf_counter() - started) * 1000)

        async with self.session_factory() as session:
            order = Order(
                agent_id=agent_id,
                offer_id=offer.id,
                status=OrderStatus.BOOKED,
                passenger=payload.passenger.model_dump(mode="json"),
                amount=offer.total_amount,
                currency=offer.currency,
                provider_booking_id=booking.provider_booking_id,
                booking_reference=booking.booking_reference,
            )
            session.add(order)
            await session.flush()
            session.add(
                IdempotencyRecord(
                    agent_id=agent_id,
                    scope="create_order",
                    key=idempotency_key,
                    request_hash=payload_hash,
                    resource_type="order",
                    resource_id=order.id,
                )
            )
            add_provider_audit(
                session,
                action="book",
                entity_type="order",
                entity_id=order.id,
                request_payload={"offer_id": offer.id, "idempotency_key": idempotency_key},
                response_payload={"provider_booking_id": booking.provider_booking_id},
                duration_ms=duration_ms,
                status_code=200,
            )
            add_status_audit(
                session,
                entity_type="order",
                entity_id=order.id,
                action="order_booked",
                before=None,
                after=OrderStatus.BOOKED,
            )
            try:
                await session.commit()
                await session.refresh(order)
                return order
            except IntegrityError:
                await session.rollback()
                replay = await self._idempotent_order(
                    agent_id, "create_order", idempotency_key, payload_hash
                )
                if replay:
                    return replay
                raise

    async def issue_order(
        self,
        agent_id: str,
        order_id: str,
        idempotency_key: str,
    ) -> tuple[Order, Agent, str]:
        async with self.session_factory() as session:
            order = await session.scalar(
                select(Order)
                .where(Order.id == order_id, Order.agent_id == agent_id)
                .with_for_update()
            )
            if not order:
                raise NotFoundError("Order not found")
            agent = await session.scalar(select(Agent).where(Agent.id == agent_id).with_for_update())
            if not agent:
                raise NotFoundError("Agent not found")
            transaction = await session.scalar(
                select(BalanceTransaction).where(BalanceTransaction.order_id == order.id).with_for_update()
            )
            if order.status == OrderStatus.ISSUED:
                return order, agent, PaymentStatus.CAPTURED
            if order.issue_idempotency_key and order.issue_idempotency_key != idempotency_key:
                raise ConflictError("Order issue is already being processed with another idempotency key")

            if transaction is None:
                if agent.balance < order.amount:
                    raise InsufficientBalanceError(
                        "Agent balance is insufficient",
                        details={"balance": str(agent.balance), "required": str(order.amount)},
                    )
                agent.balance -= order.amount
                transaction = BalanceTransaction(
                    agent_id=agent.id,
                    order_id=order.id,
                    idempotency_key=idempotency_key,
                    amount=order.amount,
                    currency=order.currency,
                    status=PaymentStatus.HELD,
                )
                session.add(transaction)
            elif transaction.status == PaymentStatus.RELEASED:
                if agent.balance < order.amount:
                    raise InsufficientBalanceError("Agent balance is insufficient")
                agent.balance -= order.amount
                transaction.status = PaymentStatus.HELD

            before = order.status
            order.status = OrderStatus.ISSUING
            order.issue_idempotency_key = idempotency_key
            add_status_audit(
                session,
                entity_type="order",
                entity_id=order.id,
                action="issue_started",
                before=before,
                after=order.status,
            )
            await session.commit()
            provider_booking_id = order.provider_booking_id

        started = perf_counter()
        try:
            ticket = await asyncio.wait_for(
                self.provider.issue(provider_booking_id, idempotency_key),
                timeout=self.provider_timeout_seconds,
            )
        except Exception as exc:
            await self._release_hold(agent_id, order_id, str(exc))
            raise ProviderError("Airline provider failed to issue the ticket") from exc
        duration_ms = int((perf_counter() - started) * 1000)

        async with self.session_factory() as session:
            order = await session.scalar(
                select(Order).where(Order.id == order_id, Order.agent_id == agent_id).with_for_update()
            )
            agent = await session.scalar(select(Agent).where(Agent.id == agent_id).with_for_update())
            transaction = await session.scalar(
                select(BalanceTransaction).where(BalanceTransaction.order_id == order_id).with_for_update()
            )
            if not order or not agent or not transaction:
                raise NotFoundError("Issue state not found")
            if order.status != OrderStatus.ISSUED:
                before = order.status
                order.status = OrderStatus.ISSUED
                order.ticket_number = ticket.ticket_number
                order.issued_at = ticket.issued_at
                transaction.status = PaymentStatus.CAPTURED
                add_provider_audit(
                    session,
                    action="issue",
                    entity_type="order",
                    entity_id=order.id,
                    request_payload={"idempotency_key": idempotency_key},
                    response_payload={"ticket_number": ticket.ticket_number},
                    duration_ms=duration_ms,
                    status_code=200,
                )
                add_status_audit(
                    session,
                    entity_type="order",
                    entity_id=order.id,
                    action="issue_completed",
                    before=before,
                    after=order.status,
                )
                await session.commit()
                await session.refresh(order)
                await session.refresh(agent)
            return order, agent, transaction.status

    async def _release_hold(self, agent_id: str, order_id: str, error: str) -> None:
        async with self.session_factory() as session:
            order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
            agent = await session.scalar(select(Agent).where(Agent.id == agent_id).with_for_update())
            transaction = await session.scalar(
                select(BalanceTransaction).where(BalanceTransaction.order_id == order_id).with_for_update()
            )
            if order and agent and transaction and transaction.status == PaymentStatus.HELD:
                agent.balance += transaction.amount
                transaction.status = PaymentStatus.RELEASED
                before = order.status
                order.status = OrderStatus.BOOKED
                add_provider_audit(
                    session,
                    action="issue",
                    entity_type="order",
                    entity_id=order.id,
                    request_payload={"idempotency_key": transaction.idempotency_key},
                    response_payload=None,
                    duration_ms=0,
                    status_code=502,
                    error_message=error,
                )
                add_status_audit(
                    session,
                    entity_type="order",
                    entity_id=order.id,
                    action="issue_failed",
                    before=before,
                    after=order.status,
                )
                await session.commit()

    async def get_order(self, agent_id: str, order_id: str) -> Order:
        async with self.session_factory() as session:
            order = await session.scalar(
                select(Order).where(Order.id == order_id, Order.agent_id == agent_id)
            )
            if not order:
                raise NotFoundError("Order not found")
            return order

    async def _idempotent_order(
        self,
        agent_id: str,
        scope: str,
        key: str,
        payload_hash: str,
    ) -> Order | None:
        async with self.session_factory() as session:
            record = await session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.agent_id == agent_id,
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.key == key,
                )
            )
            if not record:
                return None
            if record.request_hash != payload_hash:
                raise ConflictError("Idempotency key was already used with a different request")
            return await session.get(Order, record.resource_id)
