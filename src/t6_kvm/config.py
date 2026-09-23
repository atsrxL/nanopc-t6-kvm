# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict config: unsupported transformations are errors, not hidden fallbacks."""
from dataclasses import dataclass, fields
from pathlib import Path
import tomllib

@dataclass(frozen=True)
class Config:
    device: str = "/dev/video0"
    native: str = "/opt/t6-kvm/current/bin/t6-capture"
    http_socket: str = "/run/t6-kvm/streamer.sock"
    frame_socket: str = "/run/t6-kvm/frames.sock"
    fps: int = 60
    bitrate_kbps: int = 20000
    gop: int = 60
    max_width: int = 1920
    max_height: int = 1080
    expected_width: int = 0
    expected_height: int = 0
    queue_frames: int = 3
    stall_seconds: float = 8.0
    policy: str = "takeover"
    input_mode: str = "native"
    copy_mode: str = "copy"

    def validate(self) -> "Config":
        for f in fields(self):
            value = getattr(self, f.name)
            default = f.default
            # bool is an int subclass but is never a valid numeric option here.
            if type(default) is int and type(value) is not int:
                raise ValueError(f"{f.name}: expected integer")
            if type(default) is str and not isinstance(value, str):
                raise ValueError(f"{f.name}: expected string")
        for name, lo, hi in (("fps",1,60),("bitrate_kbps",100,35000),("gop",1,120),
                             ("max_width",64,2560),("max_height",64,1440),("queue_frames",1,8)):
            if not lo <= getattr(self,name) <= hi:
                raise ValueError(f"{name}: expected {lo}..{hi}")
        if isinstance(self.stall_seconds,bool) or not isinstance(self.stall_seconds,(int,float)) or not 2 <= self.stall_seconds <= 60:
            raise ValueError("stall_seconds: expected 2..60")
        if bool(self.expected_width) != bool(self.expected_height):
            raise ValueError("expected_width/height must both be zero or set")
        for axis in ("width","height"):
            if not 0 <= getattr(self,"expected_"+axis) <= getattr(self,"max_"+axis):
                raise ValueError("expected dimensions exceed maximum")
            if getattr(self,"expected_"+axis)%2 or getattr(self,"max_"+axis)%2:
                raise ValueError("4:2:0 requires even dimensions")
        if self.input_mode != "native":
            raise ValueError("Only native input is implemented; 4K→1440p/RGA scaling is NOT implemented")
        if self.copy_mode != "copy":
            raise ValueError("Only explicit CPU-copy NV12 is implemented; no zero-copy claim")
        if self.policy not in ("takeover","reject"):
            raise ValueError("policy must be takeover or reject")
        for name in ("device","native","http_socket","frame_socket"):
            p = Path(getattr(self,name))
            if not p.is_absolute() or ".." in p.parts:
                raise ValueError(f"{name}: require absolute normalized path")
        for name in ("http_socket","frame_socket"):
            if len(getattr(self,name).encode()) > 100:
                raise ValueError("Unix socket path too long")
        if self.http_socket == self.frame_socket:
            raise ValueError("HTTP and frame sockets must differ")
        return self

    def native_argv(self) -> list[str]:
        return [self.native,"--device",self.device,"--fps",str(self.fps),
                "--bitrate",str(self.bitrate_kbps*1000),"--gop",str(self.gop),
                "--max-width",str(self.max_width),"--max-height",str(self.max_height),
                "--expected-width",str(self.expected_width),"--expected-height",str(self.expected_height)]

def load(path: str) -> Config:
    with open(path,"rb") as f:
        data = tomllib.load(f)
    unknown = set(data)-{f.name for f in fields(Config)}
    if unknown:
        raise ValueError(f"Unknown config keys: {sorted(unknown)}")
    return Config(**data).validate()
