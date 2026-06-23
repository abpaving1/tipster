import asyncio
import redis.asyncio as redis
from config import settings

PROCESSING_QUEUE = "queue:picks:processing"

async def main():
    r = redis.from_url(settings.redis_url, decode_responses=True)
    items = await r.lrange(PROCESSING_QUEUE,0,-1)
    for item in items:
        await r.lpush(settings.redis_picks_queue, item)
    await r.delete(PROCESSING_QUEUE)
    print(f"Recovered {len(items)} messages")

asyncio.run(main())
