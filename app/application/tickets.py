from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.domain.enums import OrderStatus
from app.exceptions import ConflictError
from app.infrastructure.models import Order


def build_ticket_pdf(order: Order) -> bytes:
    if order.status != OrderStatus.ISSUED or not order.ticket_number:
        raise ConflictError("Ticket is available only for an issued order")

    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Ticket {order.ticket_number}",
    )
    styles = getSampleStyleSheet()
    passenger = order.passenger
    route = f"{order.offer.origin}  ->  {order.offer.destination}"
    rows = [
        ["Booking reference", order.booking_reference],
        ["Ticket number", order.ticket_number],
        ["Passenger", f"{passenger['first_name']} {passenger['last_name']}"],
        ["Route", route],
        ["Flight", f"{order.offer.carrier} {order.offer.flight_number}"],
        ["Departure", order.offer.departure_at.isoformat()],
        ["Fare", f"{order.offer.fare_family}; {order.offer.baggage}"],
        ["Total", f"{order.amount} {order.currency}"],
    ]
    table = Table(rows, colWidths=[52 * mm, 103 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E8F5EE")),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#135D3B")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#C8D8D0")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    document.build(
        [
            Paragraph("IOKA FLIGHT TICKET", styles["Title"]),
            Spacer(1, 8 * mm),
            table,
            Spacer(1, 8 * mm),
            Paragraph(
                "Keep this document and a valid identity document with you during travel.",
                styles["BodyText"],
            ),
        ]
    )
    return output.getvalue()
