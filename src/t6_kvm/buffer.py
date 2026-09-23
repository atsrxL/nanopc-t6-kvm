# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from collections.abc import Callable
from .protocol import Frame, RecoveryGate, AU

class FrameBuffer:
    """Bounded queue; overflow flushes the GOP instead of dropping one P frame."""
    def __init__(self, capacity: int, request_key: Callable[[],None]):
        if not 1 <= capacity <= 8:
            raise ValueError("capacity must be 1..8")
        self.queue: asyncio.Queue[Frame] = asyncio.Queue(capacity)
        self.gate = RecoveryGate()
        self.request_key = request_key
        self.dropped = 0

    def reset(self):
        while not self.queue.empty():
            self.queue.get_nowait()
            self.dropped += 1
        self.gate.reset()

    def put(self, frame: Frame) -> bool:
        if frame.kind != AU:
            self.reset()
            self.queue.put_nowait(frame)
            return True
        if self.queue.full():
            self.reset()
            self.request_key()
        if not self.gate.accept(frame):
            self.dropped += 1
            self.request_key()
            return False
        self.queue.put_nowait(frame)
        return True

    async def get(self) -> Frame:
        return await self.queue.get()
