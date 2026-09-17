import asyncio
import json
from collections.abc import Awaitable, Callable

import aio_pika

SEARCH_QUEUE = "flight-searches"


class SearchBroker:
    def __init__(self, url: str) -> None:
        self.url = url

    async def publish(self, search_id: str) -> None:
        connection = await aio_pika.connect_robust(self.url)
        async with connection:
            channel = await connection.channel()
            await channel.declare_queue(SEARCH_QUEUE, durable=True)
            await channel.default_exchange.publish(
                aio_pika.Message(
                    body=json.dumps({"search_id": search_id}).encode(),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=SEARCH_QUEUE,
            )


async def consume_searches(url: str, handler: Callable[[str], Awaitable[None]]) -> None:
    connection = await aio_pika.connect_robust(url)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=8)
    queue = await channel.declare_queue(SEARCH_QUEUE, durable=True)

    async def consume(message: aio_pika.IncomingMessage) -> None:
        async with message.process(requeue=True):
            payload = json.loads(message.body)
            await handler(payload["search_id"])

    await queue.consume(consume)
    await asyncio.Future()
