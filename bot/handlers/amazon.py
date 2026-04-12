import asyncio
import logging

from ai_sdk import tool as ai_tool
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from pydantic import BaseModel

from bot.config import settings

router = Router()
logger = logging.getLogger(__name__)

COMMANDS = {"orders": "Show Amazon orders — upcoming deliveries and recent arrivals"}

_ARRIVING_KEYWORDS = ("arriving", "out for delivery", "on the way")
_DELIVERED_KEYWORDS = ("delivered",)


def _classify(status: str) -> str:
    low = status.lower()
    if any(k in low for k in _ARRIVING_KEYWORDS):
        return "upcoming"
    if any(k in low for k in _DELIVERED_KEYWORDS):
        return "delivered"
    return "unknown"


def _fetch_orders() -> str:
    if not settings.amazon_username or not settings.amazon_password:
        return (
            "Amazon credentials are not configured. "
            "Set AMAZON_USERNAME and AMAZON_PASSWORD in your .env file."
        )

    from amazonorders.orders import AmazonOrders
    from amazonorders.session import AmazonSession

    try:
        session = AmazonSession(
            username=settings.amazon_username,
            password=settings.amazon_password,
            otp_secret_key=settings.amazon_otp_secret or None,
        )
        session.login()
        orders = AmazonOrders(session).get_order_history(time_filter="last30", full_details=True)
    except Exception as exc:
        logger.exception("Amazon fetch failed")
        return f"Failed to fetch Amazon orders: {exc}"

    upcoming: list[str] = []
    delivered: list[str] = []

    for order in orders:
        try:
            status = order.simple_parse(selector=".od-status-message") or ""
            status = str(status).strip()
        except Exception:
            status = ""

        items = getattr(order, "items", None) or []
        item_names = [
            getattr(item, "title", None) or getattr(item, "asin", "Unknown item")
            for item in items
        ]
        items_str = ", ".join(item_names[:2])
        if len(item_names) > 2:
            items_str += f" (+{len(item_names) - 2} more)"

        order_id = getattr(order, "order_number", None) or "?"
        order_date = getattr(order, "order_placed_date", None)
        date_str = order_date.strftime("%b %d") if hasattr(order_date, "strftime") else str(order_date or "")

        label = f"• <b>{items_str}</b> (#{order_id}, placed {date_str})"
        if status:
            label += f"\n  {status}"

        category = _classify(status)
        if category == "upcoming":
            upcoming.append(label)
        elif category == "delivered":
            delivered.append(label)

    parts: list[str] = []
    if upcoming:
        parts.append("<b>Upcoming deliveries:</b>\n" + "\n\n".join(upcoming))
    if delivered:
        parts.append("<b>Recently delivered:</b>\n" + "\n\n".join(delivered))
    if not parts:
        return "No upcoming or recently delivered orders found in the last 30 days."

    return "\n\n".join(parts)


class _NoParams(BaseModel):
    pass


AI_TOOLS = [
    ai_tool(
        name="list_amazon_orders",
        description=(
            "Fetch the user's Amazon order history for the last 30 days. "
            "Returns upcoming deliveries (arriving soon, out for delivery) and recently "
            "delivered packages. Use when the user asks about Amazon orders, packages, "
            "deliveries, or shipments."
        ),
        parameters=_NoParams,
        execute=_fetch_orders,
    )
]


_MAX_MSG = 4096


def _chunk(text: str) -> list[str]:
    """Split text into Telegram-safe chunks, breaking on double newlines."""
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = (current + "\n\n" + paragraph).lstrip("\n") if current else paragraph
        if len(candidate) <= _MAX_MSG:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # paragraph itself may exceed limit — hard-split as last resort
            while len(paragraph) > _MAX_MSG:
                chunks.append(paragraph[:_MAX_MSG])
                paragraph = paragraph[_MAX_MSG:]
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


@router.message(Command("orders"))
async def cmd_orders(message: Message) -> None:
    await message.answer("Fetching your Amazon orders…")
    result = await asyncio.to_thread(_fetch_orders)
    for chunk in _chunk(result):
        await message.answer(chunk)
