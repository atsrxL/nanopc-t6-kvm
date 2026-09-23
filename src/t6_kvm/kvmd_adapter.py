# SPDX-License-Identifier: GPL-3.0-or-later
"""Adapter loaded by the guarded kvmd-v4.120 patch; no new RFB implementation."""
import asyncio
import contextlib
import os
import time
from .config import load
from .protocol import read_frame, Frame, AU, RecoveryGate, H264, ProtocolError
from .buffer import FrameBuffer
from .ownership import Owner, Lease
from kvmd.clients.streamer import BaseStreamerClient, StreamerTempError

CONFIG = os.environ.get("T6_KVM_CONFIG","/etc/t6-kvm/streamer.toml")
_owner = None

def owner():
    global _owner
    if _owner is None:
        _owner = Owner(load(CONFIG).policy)
    return _owner

def begin_client(client):
    task = asyncio.current_task()
    client._t6_lease = Lease(task.cancel)

async def claim_client(client):
    # Called ONLY inside success branches of existing upstream authentication.
    return await owner().admit(client._t6_lease,authenticated=True)

def finish_client(client):
    owner().release(client._t6_lease)

class T6StreamerClient(BaseStreamerClient):
    def __init__(self):
        self.config = load(CONFIG)
        self.writer = None
        self.last_request = 0.0

    def __str__(self):
        return "T6 ordered MPP H264"

    def get_format(self):
        return H264

    def request_key(self):
        if self.writer and time.monotonic()-self.last_request > .25:
            self.writer.write(b"K")
            self.last_request = time.monotonic()

    @contextlib.asynccontextmanager
    async def reading(self):
        writer = None
        try:
            reader,writer = await asyncio.open_unix_connection(self.config.frame_socket)
            self.writer = writer
            gate = RecoveryGate()
            self.last_request = 0
            self.request_key()
            async def receive(key_required):
                if key_required:
                    gate.reset()
                    self.request_key()
                while True:
                    f = await asyncio.wait_for(read_frame(reader),self.config.stall_seconds)
                    if f.kind != AU:
                        raise StreamerTempError(f.data.decode(errors="replace"))
                    if gate.accept(f):
                        return f.kvmd()
                    self.request_key()
            yield receive
        except (OSError,ProtocolError,asyncio.IncompleteReadError,TimeoutError) as ex:
            raise StreamerTempError(str(ex)) from ex
        finally:
            self.writer = None
            if writer:
                writer.close()
                with contextlib.suppress(OSError):
                    await writer.wait_closed()

class VncFrameBuffer:
    """Final VNC boundary also gates loss; covers slow client update requests."""
    def __init__(self, request_key):
        self.inner = FrameBuffer(load(CONFIG).queue_frames,request_key)
        self.jpeg = None

    def put(self, value):
        if value.get("format") != H264:
            self.inner.reset()
            # An explicit status carries the immutable JPEG waiting screen.
            self.jpeg = value
            self.inner.put(Frame.status(message="waiting"))
            return True
        return self.inner.put(Frame.from_kvmd(value).validate())

    async def get(self):
        value = await self.inner.get()
        if value.kind != AU:
            return self.jpeg
        return value.kvmd()
