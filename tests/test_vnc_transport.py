import asyncio
import unittest
from unittest.mock import Mock, AsyncMock
from t6_kvm import vnc_transport as v

class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_healthy_receiver(self):
        w=Mock();w.drain=AsyncMock()
        await v.drain(w)
        w.transport.abort.assert_not_called()

    async def test_slow_receiver_remains_connected(self):
        w=Mock();w.drain=lambda: asyncio.sleep(.6)
        await v.drain(w)
        w.transport.abort.assert_not_called()

    async def test_cancel_propagates(self):
        w=Mock();w.drain=AsyncMock(side_effect=asyncio.CancelledError)
        with self.assertRaises(asyncio.CancelledError):await v.drain(w)
        w.transport.abort.assert_not_called()
