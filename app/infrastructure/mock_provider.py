import asyncio
import hashlib
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from app.domain.provider import ProviderBooking, ProviderOffer, ProviderSearchRequest, ProviderTicket


class MockAirlineProvider:
    name = "mock-air"

    def __init__(self, delay_seconds: float = 0.15) -> None:
        self.delay_seconds = delay_seconds
        self._bookings: dict[str, ProviderBooking] = {}
        self._tickets: dict[str, ProviderTicket] = {}

    async def search(self, request: ProviderSearchRequest) -> list[ProviderOffer]:
        await asyncio.sleep(self.delay_seconds)
        seed = hashlib.sha256(
            f"{request.origin}:{request.destination}:{request.departure_date}".encode()
        ).hexdigest()
        base_price = Decimal(650_000 + int(seed[:4], 16) % 350_000)
        departure = datetime.combine(request.departure_date, time(8, 30), tzinfo=UTC)
        now = datetime.now(UTC)
        variants = [
            ("BASIC", "Carry-on 8 kg", Decimal("1.00")),
            ("FLEX", "Checked baggage 23 kg", Decimal("1.25")),
            ("BUSINESS", "Checked baggage 32 kg", Decimal("2.10")),
        ]
        return [
            ProviderOffer(
                provider_offer_id=f"{seed[:12]}-{index}",
                origin=request.origin,
                destination=request.destination,
                departure_at=departure + timedelta(hours=index * 3),
                arrival_at=departure + timedelta(hours=index * 3 + 4, minutes=20),
                carrier="Ioka Airways",
                flight_number=f"IO{210 + index}",
                fare_family=fare,
                baggage=baggage,
                total_amount=(base_price * multiplier * request.adults).quantize(Decimal("0.01")),
                currency="UZS",
                expires_at=now + timedelta(minutes=15),
                raw_payload={"source": self.name, "refundable": fare != "BASIC"},
            )
            for index, (fare, baggage, multiplier) in enumerate(variants)
        ]

    async def book(
        self,
        provider_offer_id: str,
        passenger: dict[str, Any],
        idempotency_key: str,
    ) -> ProviderBooking:
        await asyncio.sleep(self.delay_seconds)
        if idempotency_key not in self._bookings:
            digest = hashlib.sha256(idempotency_key.encode()).hexdigest().upper()
            self._bookings[idempotency_key] = ProviderBooking(
                provider_booking_id=f"BKG-{digest[:16]}",
                booking_reference=digest[:6],
            )
        return self._bookings[idempotency_key]

    async def issue(self, provider_booking_id: str, idempotency_key: str) -> ProviderTicket:
        await asyncio.sleep(self.delay_seconds)
        if idempotency_key not in self._tickets:
            digest = hashlib.sha256(f"{provider_booking_id}:{idempotency_key}".encode()).hexdigest()
            self._tickets[idempotency_key] = ProviderTicket(
                ticket_number=f"250-{int(digest[:10], 16) % 10_000_000_000:010d}",
                issued_at=datetime.now(UTC),
            )
        return self._tickets[idempotency_key]
