# SPDX-License-Identifier: GPL-3.0-or-later
"""48-byte architecture-independent framing; one AU, never one arbitrary read."""
import asyncio
import json
import re
import struct
from dataclasses import dataclass

HEADER = struct.Struct("!4sBBHIIIIQQQ")
MAGIC = b"T6AU"
AU, STATUS = 1, 2
ONLINE, KEY, DISCONTINUITY = 1, 2, 4
MAX_PAYLOAD = 4*1024*1024
H264 = 875967048

class ProtocolError(ValueError):
    pass

def nal_types(data: bytes) -> set[int]:
    """Annex-B boundary inspection, NOT a full H.264 bitstream decoder."""
    starts = list(re.finditer(b"\x00\x00(?:\x00)?\x01", data))
    if not starts or starts[0].start() != 0:
        raise ProtocolError("Expected Annex-B access unit")
    types = set()
    for i, match in enumerate(starts):
        end = starts[i+1].start() if i+1 < len(starts) else len(data)
        if match.end() >= end:
            raise ProtocolError("Empty NAL unit")
        byte = data[match.end()]
        if byte & 0x80 or (byte & 31) == 0:
            raise ProtocolError("Invalid NAL header")
        types.add(byte & 31)
    return types

@dataclass(frozen=True)
class Frame:
    kind: int
    flags: int
    width: int
    height: int
    epoch: int
    sequence: int
    pts_us: int
    data: bytes

    @property
    def key(self) -> bool:
        return bool(self.flags & KEY)

    def validate(self) -> "Frame":
        if self.kind not in (AU,STATUS) or self.flags & ~7:
            raise ProtocolError("Unsupported kind/flags")
        if not 0 < len(self.data) <= MAX_PAYLOAD:
            raise ProtocolError("Payload length out of range")
        if not all(0 <= n < 2**64 for n in (self.epoch,self.sequence,self.pts_us)):
            raise ProtocolError("Invalid counter")
        if self.kind == AU:
            if not (self.flags & ONLINE) or not self.epoch or not self.sequence:
                raise ProtocolError("AU requires online and nonzero epoch/sequence")
            if not all(0 < n <= 4096 and n%2 == 0 for n in (self.width,self.height)):
                raise ProtocolError("Invalid dimensions")
            types = nal_types(self.data)
            if not types & {1,5}:
                raise ProtocolError("AU contains no coded picture")
            # All random access units must carry their own SPS/PPS.
            if self.key != (5 in types) or (self.key and not {7,8,5} <= types):
                raise ProtocolError("IDR/key flag or SPS/PPS mismatch")
        else:
            if len(self.data) > 65536:
                raise ProtocolError("Status too large")
            try:
                value = json.loads(self.data)
            except (ValueError, UnicodeError) as ex:
                raise ProtocolError("Invalid status JSON") from ex
            if not isinstance(value,dict):
                raise ProtocolError("Status must be object")
        return self

    def pack(self) -> bytes:
        self.validate()
        return HEADER.pack(MAGIC,1,self.kind,HEADER.size,len(self.data),self.flags,
                           self.width,self.height,self.epoch,self.sequence,self.pts_us)+self.data

    def kvmd(self) -> dict:
        return {"online":bool(self.flags&ONLINE),"width":self.width,"height":self.height,
                "format":H264,"key":self.key,"data":self.data,
                "t6_epoch":self.epoch,"t6_sequence":self.sequence,"t6_pts_us":self.pts_us}

    @classmethod
    def from_kvmd(cls, f: dict) -> "Frame":
        return cls(AU,ONLINE|(KEY if f.get("key") else 0),f["width"],f["height"],
                   f["t6_epoch"],f["t6_sequence"],f["t6_pts_us"],f["data"])

    @classmethod
    def status(cls, **value) -> "Frame":
        return cls(STATUS,0,0,0,0,0,0,json.dumps(value,separators=(",",":")).encode())

async def read_frame(reader: asyncio.StreamReader) -> Frame:
    header = await reader.readexactly(HEADER.size)
    magic,version,kind,hlen,length,flags,w,h,epoch,seq,pts = HEADER.unpack(header)
    # Validate before reading/allocating an untrusted payload.
    if magic != MAGIC or version != 1 or hlen != HEADER.size or kind not in (AU,STATUS):
        raise ProtocolError("Bad frame header")
    if not 0 < length <= (65536 if kind==STATUS else MAX_PAYLOAD):
        raise ProtocolError("Payload length out of range")
    return Frame(kind,flags,w,h,epoch,seq,pts,await reader.readexactly(length)).validate()

class RecoveryGate:
    """Lose any reference AU → discard dependent pictures until SPS/PPS+IDR."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.need_key = True
        self.epoch = self.sequence = 0
        self.geometry = (0,0)

    def accept(self, f: Frame) -> bool:
        if f.kind != AU:
            self.reset()
            return False
        if (f.flags & DISCONTINUITY or f.epoch != self.epoch or
                (f.width,f.height) != self.geometry or f.sequence != self.sequence+1):
            self.need_key = True
        self.epoch,self.sequence,self.geometry = f.epoch,f.sequence,(f.width,f.height)
        if self.need_key and not f.key:
            return False
        if f.key:
            self.need_key = False
        return True
