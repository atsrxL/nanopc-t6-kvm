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
from kvmd.clients.streamer import BaseStreamerClient, StreamerTempError, StreamerFormats

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
        if self.writer and time.monotonic()-self.last_request > .03:
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

class T6JpegStreamerClient(BaseStreamerClient):
    """Decode the shared H264 stream; encode independent JPEGs only on demand."""
    def __init__(self):
        self.source = T6StreamerClient()

    def __str__(self):
        return "T6 Tight/JPEG compatibility (15 fps cap)"

    def get_format(self):
        return StreamerFormats.JPEG

    @contextlib.asynccontextmanager
    async def reading(self):
        import av
        import io
        decoder = av.CodecContext.create("h264", "r")
        decoder.thread_count = 2
        decoder.thread_type = "SLICE"
        last_jpeg = 0.0
        epoch = None

        def convert(frame, emit):
            pictures = decoder.decode(av.Packet(frame["data"]))
            if not pictures or not emit:
                return None
            picture = pictures[-1]
            image = picture.to_image()
            tiles = []
            for y in range(0, image.height, 2048):
                for x in range(0, image.width, 2048):
                    part = image.crop((x, y, min(x+2048,image.width), min(y+2048,image.height)))
                    output = io.BytesIO()
                    part.save(output, format="JPEG", quality=70)
                    tiles.append((x,y,part.width,part.height,output.getvalue()))
            return {"online": True, "width": picture.width, "height": picture.height,
                    "format": StreamerFormats.JPEG, "data": tiles}

        async with self.source.reading() as read:
            # Keep draining the AU socket while expensive 4K conversion runs.
            # Overflow drops a GOP and requests an IDR, bounding latency.
            pending = FrameBuffer(8, self.source.request_key)

            async def collect():
                try:
                    while True:
                        pending.put(Frame.from_kvmd(await read(False)))
                except Exception as ex:
                    pending.reset()
                    pending.queue.put_nowait(ex)

            collector = asyncio.create_task(collect())

            async def receive(_key_required):
                nonlocal last_jpeg, decoder, epoch
                while True:
                    item = await pending.get()
                    if isinstance(item, Exception):
                        raise item
                    frame = item.kvmd()
                    if epoch != frame["t6_epoch"] or frame.get("key"):
                        # Every key AU includes SPS/PPS, also recovering queue loss.
                        decoder = av.CodecContext.create("h264", "r")
                        decoder.thread_count = 2
                        decoder.thread_type = "SLICE"
                        epoch = frame["t6_epoch"]
                    now = time.monotonic()
                    try:
                        result = await asyncio.to_thread(convert, frame, now-last_jpeg >= 1/15)
                    except av.FFmpegError as ex:
                        self.source.request_key()
                        raise StreamerTempError(str(ex)) from ex
                    if result is not None:
                        last_jpeg = now
                        return result
            try:
                yield receive
            finally:
                collector.cancel()
                await asyncio.gather(collector, return_exceptions=True)
