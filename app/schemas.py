from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime


class AgentProfile(ApiModel):
    id: str
    email: str
    balance: Decimal
    currency: str


class LocationOut(BaseModel):
    iata: str
    city: str
    airport: str
    country: str


class SearchRequest(BaseModel):
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    departure_date: date
    adults: int = Field(default=1, ge=1, le=9)
    cabin_class: Literal["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS"] = "ECONOMY"

    @field_validator("origin", "destination")
    @classmethod
    def normalize_iata(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized.isalpha():
            raise ValueError("IATA code must contain only letters")
        return normalized

    @field_validator("departure_date")
    @classmethod
    def ensure_not_in_past(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("departure_date cannot be in the past")
        return value


class SearchAccepted(BaseModel):
    search_id: str
    status: str
    poll_url: str
    expires_at: datetime


class OfferOut(ApiModel):
    id: str
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


class OfferDetail(OfferOut):
    provider: str
    fare_rules: dict[str, Any]


class SearchResult(BaseModel):
    search_id: str
    status: str
    offers: list[OfferOut] = Field(default_factory=list)
    error: dict[str, str] | None = None


class Passenger(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    birth_date: date
    document_number: str = Field(min_length=5, max_length=32)
    document_expiry: date
    citizenship: str = Field(min_length=2, max_length=3)

    @field_validator("first_name", "last_name", "document_number", "citizenship")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip().upper()


class OrderCreate(BaseModel):
    offer_id: str
    passenger: Passenger


class OrderOut(ApiModel):
    id: str
    status: str
    booking_reference: str
    ticket_number: str | None
    amount: Decimal
    currency: str
    passenger: dict[str, Any]
    issued_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IssueResult(BaseModel):
    order: OrderOut
    balance: Decimal
    payment_status: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]

