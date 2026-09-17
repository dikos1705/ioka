from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderSearchRequest:
    origin: str
    destination: str
    departure_date: date
    adults: int
    cabin_class: str


@dataclass(frozen=True)
class ProviderOffer:
    provider_offer_id: str
    origin: str
    destination: str
    departure_at: datetime
    arrival_at: datetime
    carrier: str
    flight_number: str
    fare_family: str
    baggage: str
    total_amount: Decimal
    currency: str
    expires_at: datetime
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class ProviderBooking:
    provider_booking_id: str
    booking_reference: str


@dataclass(frozen=True)
class ProviderTicket:
    ticket_number: str
    issued_at: datetime


class AirlineProvider(Protocol):
    name: str

    async def search(self, request: ProviderSearchRequest) -> list[ProviderOffer]: ...

    async def book(
        self,
        provider_offer_id: str,
        passenger: dict[str, Any],
        idempotency_key: str,
    ) -> ProviderBooking: ...

    async def issue(self, provider_booking_id: str, idempotency_key: str) -> ProviderTicket: ...
