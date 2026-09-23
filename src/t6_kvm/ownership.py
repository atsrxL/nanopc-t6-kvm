# SPDX-License-Identifier: GPL-3.0-or-later
"""Admission is deliberately separate from transport establishment."""
import asyncio
from dataclasses import dataclass, field
from collections.abc import Callable

@dataclass(eq=False)
class Lease:
    cancel: Callable[[],None]
    closed: asyncio.Event = field(default_factory=asyncio.Event)

class Owner:
    def __init__(self, policy="takeover", timeout=5.0):
        if policy not in ("takeover","reject"):
            raise ValueError("Invalid policy")
        self.policy, self.timeout = policy, timeout
        self.owner: Lease | None = None
        self.lock = asyncio.Lock()

    async def admit(self, candidate: Lease, *, authenticated: bool) -> bool:
        if not authenticated:
            return False
        async with self.lock:
            previous = self.owner
            if previous is candidate:
                return True
            if previous:
                if self.policy == "reject":
                    return False
                previous.cancel()
                try:
                    await asyncio.wait_for(previous.closed.wait(),self.timeout)
                except TimeoutError:
                    # Never overlap control if cleanup did not finish.
                    return False
            self.owner = candidate
            return True

    def release(self, lease: Lease):
        # Must not acquire lock: old cleanup runs while takeover holds it.
        if self.owner is lease:
            self.owner = None
        lease.closed.set()

class HidOwner:
    """Old websocket teardown cannot clear a newer websocket's keys."""
    def __init__(self):
        self.owner = None
    def added(self, ws, clear):
        clear()
        self.owner = ws
    def removed(self, ws, clear):
        if self.owner is ws:
            clear()
            self.owner = None
