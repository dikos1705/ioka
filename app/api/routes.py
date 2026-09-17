from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentAgent
from app.application.booking import BookingService
from app.application.search import SearchService
from app.application.tickets import build_ticket_pdf
from app.config import Settings, get_settings
from app.exceptions import AuthenticationError, NotFoundError
from app.infrastructure.database import get_session
from app.infrastructure.locations import search_locations
from app.infrastructure.models import Agent, FlightSearch, Offer, Order
from app.schemas import (
    AgentProfile,
    HealthResponse,
    IssueResult,
    LocationOut,
    LoginRequest,
    OfferDetail,
    OrderCreate,
    OrderOut,
    SearchAccepted,
    SearchRequest,
    SearchResult,
    TokenResponse,
)
from app.security import create_access_token, verify_password

router = APIRouter(prefix="/travel")


def search_service(request: Request) -> SearchService:
    return request.app.state.search_service


def booking_service(request: Request) -> BookingService:
    return request.app.state.booking_service


@router.post("/auth/agent/login", response_model=TokenResponse, tags=["Authentication"])
async def login(
    payload: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    agent = await session.scalar(select(Agent).where(Agent.email == payload.email.lower()))
    if not agent or not agent.is_active or not verify_password(payload.password, agent.password_hash):
        raise AuthenticationError("Invalid email or password")
    token, expires_at = create_access_token(subject=agent.id, settings=settings)
    return TokenResponse(access_token=token, expires_at=expires_at)


@router.get("/auth/agent/me", response_model=AgentProfile, tags=["Authentication"])
async def profile(agent: CurrentAgent) -> Agent:
    return agent


@router.get("/avia/locations", response_model=list[LocationOut], tags=["Flights"])
async def locations(
    agent: CurrentAgent,
    query: Annotated[str, Query(alias="q", max_length=80)] = "",
) -> list[dict[str, str]]:
    del agent
    return search_locations(query)


@router.post(
    "/avia/offers",
    response_model=SearchAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Flights"],
)
async def start_offer_search(
    payload: SearchRequest,
    agent: CurrentAgent,
    service: Annotated[SearchService, Depends(search_service)],
) -> SearchAccepted:
    search = await service.start(agent.id, payload)
    return SearchAccepted(
        search_id=search.id,
        status=search.status,
        poll_url=f"/travel/avia/offers/search/{search.id}",
        expires_at=search.expires_at,
    )


@router.get("/avia/offers/search/{search_id}", response_model=SearchResult, tags=["Flights"])
async def poll_offer_search(
    search_id: str,
    agent: CurrentAgent,
    service: Annotated[SearchService, Depends(search_service)],
) -> SearchResult:
    search = await service.get(search_id, agent.id)
    error = None
    if search.error_code:
        error = {"code": search.error_code, "message": search.error_message or "Search failed"}
    return SearchResult(search_id=search.id, status=search.status, offers=search.offers, error=error)


@router.get("/avia/offers/{offer_id}", response_model=OfferDetail, tags=["Flights"])
async def offer_details(
    offer_id: str,
    agent: CurrentAgent,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfferDetail:
    offer = await session.scalar(
        select(Offer)
        .join(FlightSearch)
        .where(Offer.id == offer_id, FlightSearch.agent_id == agent.id)
    )
    if not offer:
        raise NotFoundError("Offer not found")
    return OfferDetail.model_validate({
        "id": offer.id,
        "origin": offer.origin,
        "destination": offer.destination,
        "departure_at": offer.departure_at,
        "arrival_at": offer.arrival_at,
        "carrier": offer.carrier,
        "flight_number": offer.flight_number,
        "fare_family": offer.fare_family,
        "baggage": offer.baggage,
        "total_amount": offer.total_amount,
        "currency": offer.currency,
        "expires_at": offer.expires_at,
        "provider": offer.provider,
        "fare_rules": offer.raw_payload,
    })


@router.post("/avia/orders", response_model=OrderOut, status_code=201, tags=["Orders"])
async def create_order(
    payload: OrderCreate,
    agent: CurrentAgent,
    service: Annotated[BookingService, Depends(booking_service)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> Order:
    return await service.create_order(agent.id, payload, idempotency_key)


@router.post("/avia/orders/{order_id}/issue", response_model=IssueResult, tags=["Orders"])
async def issue_order(
    order_id: str,
    agent: CurrentAgent,
    service: Annotated[BookingService, Depends(booking_service)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> IssueResult:
    order, updated_agent, payment_status = await service.issue_order(
        agent.id, order_id, idempotency_key
    )
    return IssueResult(
        order=OrderOut.model_validate(order),
        balance=updated_agent.balance,
        payment_status=payment_status,
    )


@router.get("/avia/orders/{order_id}", response_model=OrderOut, tags=["Orders"])
async def get_order(
    order_id: str,
    agent: CurrentAgent,
    service: Annotated[BookingService, Depends(booking_service)],
) -> Order:
    return await service.get_order(agent.id, order_id)


@router.get(
    "/avia/orders/{order_id}/ticket",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/pdf": {}}}},
    tags=["Orders"],
)
async def get_ticket(
    order_id: str,
    agent: CurrentAgent,
    service: Annotated[BookingService, Depends(booking_service)],
) -> StreamingResponse:
    order = await service.get_order(agent.id, order_id)
    pdf = build_ticket_pdf(order)
    return StreamingResponse(
        BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="ticket-{order.ticket_number}.pdf"'},
    )


health_router = APIRouter(tags=["Health"])


@health_router.get("/health/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse(status="ok")


@health_router.get("/health/ready", response_model=HealthResponse)
async def ready(session: Annotated[AsyncSession, Depends(get_session)]) -> HealthResponse:
    await session.execute(select(1))
    return HealthResponse(status="ready")
