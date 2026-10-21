"""Small async TTL cache for upstream aggregates."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any


class TTLCache:
    def __init__(self) -> None:
        self._values: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get_or_create(
        self,
        key: str,
        ttl: float,
        factory: Callable[[], Awaitable[Any]],
    ) -> Any:
        now = time.monotonic()
        cached = self._values.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._values.get(key)
            now = time.monotonic()
            if cached is not None and cached[0] > now:
                return cached[1]
            value = await factory()
            self._values[key] = (now + ttl, value)
            return value
