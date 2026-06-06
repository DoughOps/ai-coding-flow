import asyncio
from config import Settings


async def enqueue_job(*, platform: str, issue_number: int, title: str, body: str) -> None:
    pass  # stub — full implementation in Task 9


async def start_worker(settings: Settings) -> None:
    while True:
        await asyncio.sleep(3600)  # stub
