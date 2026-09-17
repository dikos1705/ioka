from enum import StrEnum


class SearchStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class OrderStatus(StrEnum):
    BOOKED = "BOOKED"
    ISSUING = "ISSUING"
    ISSUED = "ISSUED"
    CANCELLED = "CANCELLED"


class PaymentStatus(StrEnum):
    HELD = "HELD"
    CAPTURED = "CAPTURED"
    RELEASED = "RELEASED"


class AuditKind(StrEnum):
    PROVIDER_REQUEST = "PROVIDER_REQUEST"
    STATUS_CHANGE = "STATUS_CHANGE"

