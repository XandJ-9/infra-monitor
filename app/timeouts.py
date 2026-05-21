# -*- coding: utf-8 -*-
"""Timeout helpers for request-time external component calls."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

REQUEST_TIMEOUT_SECONDS = 6.0


async def with_timeout(awaitable: Awaitable[T], fallback: T, timeout: float = REQUEST_TIMEOUT_SECONDS) -> T:
    """Return fallback when an awaitable takes too long or raises."""
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except Exception:
        return fallback


async def sync_with_timeout(
    func: Callable[..., T],
    *args: object,
    fallback: T,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> T:
    """Run blocking work in a thread and cap how long the request waits for it."""
    return await with_timeout(asyncio.to_thread(func, *args), fallback=fallback, timeout=timeout)
