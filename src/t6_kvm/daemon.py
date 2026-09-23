# SPDX-License-Identifier: GPL-3.0-or-later
"""kvmd-owned streamer child: Unix HTTP status + ordered AU socket + native worker."""
import argparse
import asyncio
import contextlib
import dataclasses
import fcntl
import json
import logging
import os
from pathlib import Path
import signal
import socket
import time
from collections import deque

from aiohttp import web
from .config import Config, load
from .protocol import Frame, AU, read_frame, RecoveryGate, ProtocolError
from .buffer import FrameBuffer

LOG = logging.getLogger("t6-streamer")

class OwnedSocket:
    """Never unlink a pre-existing endpoint, including somebody else's stale one."""
    def __init__(self, path: str):
        self.path = Path(path)
        self.sock = None
        self.identity = None

    def bind(self):
        parent = self.path.parent.stat()
        if parent.st_uid != os.geteuid() or parent.st_mode & 0o022:
            raise PermissionError(f"Socket directory must be owned and non-writable by others: {self.path.parent}")
        if self.path.exists() or self.path.is_symlink():
            raise FileExistsError(f"Refusing to replace existing endpoint: {self.path}")
        self.sock = socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            self.sock.bind(str(self.path))
            s = self.path.lstat()
            self.identity = (s.st_dev,s.st_ino)
            os.chmod(self.path,0o660)
            self.sock.listen(8)
            self.sock.setblocking(False)
            return self.sock
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.sock:
            self.sock.close()
        with contextlib.suppress(FileNotFoundError):
            s = self.path.lstat()
            if (s.st_dev,s.st_ino) == self.identity:
                self.path.unlink()

async def stop_child(proc):
    if proc is None:
        return
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(),3)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
    else:
        await proc.wait()

class Broker:
    def __init__(self, config: Config):
        self.config = config.validate()
        self.proc = None
        self.buffers: set[FrameBuffer] = set()
        self.clients: set[asyncio.Task] = set()
        self.tasks = []
        self.key_time = 0.0
        self.wait_key_since = 0.0
        self.gate = RecoveryGate()
        self.times: deque[float] = deque(maxlen=600)
        self.state = {"online":False,"input":None,"output":None,"encoded_frames":0,
                      "encoded_fps_observed":0.0,"restarts":0,"last_error":"Not started",
                      "copy_mode":"CPU-copy","scaling":False,"hardware_validated":False}

    def request_key(self):
        now = time.monotonic()
        if self.proc and self.proc.returncode is None and now-self.key_time >= .03:
            try:
                self.proc.stdin.write(b"K")
                self.key_time = now
            except (BrokenPipeError, ConnectionResetError):
                pass

    def status(self, message: str):
        self.gate.reset()
        self.times.clear()
        self.state.update(online=False,last_error=message,encoded_fps_observed=0.0)
        frame = Frame.status(online=False,message=message)
        for buf in tuple(self.buffers):
            buf.put(frame)

    def publish(self, frame: Frame):
        if frame.kind != AU:
            info = json.loads(frame.data)
            if "input_path" in info:
                self.state["copy_mode"] = info["input_path"]
                return
            if "input" in info:
                self.state["input"] = info["input"]
            if "capture_frames" in info:
                self.state["capture_frames_worker"] = info["capture_frames"]
            if "capture_frames" in info:
                info["copy"] = self.state.get("copy_mode") != "DMABUF import"
            self.state["worker_status"] = info
            if not info.get("online",False):
                self.status(str(info.get("message","No input signal")))
            return
        if not self.gate.accept(frame):
            self.request_key()
            if not self.wait_key_since:
                self.wait_key_since = time.monotonic()
            if time.monotonic()-self.wait_key_since > self.config.stall_seconds:
                raise ProtocolError("No usable IDR after recovery timeout")
            return
        self.wait_key_since = 0
        now = time.monotonic()
        self.times.append(now)
        while self.times and now-self.times[0] > 5:
            self.times.popleft()
        rate = ((len(self.times)-1)/(now-self.times[0])
                if len(self.times)>1 and now>self.times[0] else 0.0)
        self.state.update(online=True,last_error=None,
                          output={"width":frame.width,"height":frame.height,"codec":"H264",
                                  "epoch":frame.epoch,"sequence":frame.sequence},
                          encoded_frames=self.state["encoded_frames"]+1,
                          encoded_fps_observed=round(rate,2))
        for buf in tuple(self.buffers):
            buf.put(frame)

    async def serve_client(self, reader, writer):
        task = asyncio.current_task()
        if len(self.clients) >= 4:
            writer.close()
            await writer.wait_closed()
            return
        self.clients.add(task)
        buf = FrameBuffer(self.config.queue_frames,self.request_key)
        self.buffers.add(buf)
        self.request_key()
        async def commands():
            while data := await reader.read(64):
                if any(byte != ord("K") for byte in data):
                    raise ProtocolError("Unknown control byte")
                self.request_key()
        async def frames():
            while True:
                frame = await buf.get()
                writer.write(frame.pack())
                await asyncio.wait_for(writer.drain(),2)
        tasks = [asyncio.create_task(commands()),asyncio.create_task(frames())]
        try:
            done,_ = await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                t.result()
        except (OSError,ProtocolError,TimeoutError) as ex:
            LOG.info("AU client disconnected: %s",ex)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            self.buffers.discard(buf)
            self.clients.discard(task)
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def worker_loop(self):
        while True:
            self.key_time = 0
            self.wait_key_since = 0
            self.status("Starting capture worker")
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *self.config.native_argv(),stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,stderr=None,limit=4*1024*1024+48)
                while True:
                    frame = await asyncio.wait_for(read_frame(self.proc.stdout),self.config.stall_seconds)
                    self.publish(frame)
            except asyncio.CancelledError:
                raise
            except (OSError,ProtocolError,asyncio.IncompleteReadError,TimeoutError) as ex:
                LOG.warning("Capture stopped: %s",ex)
                self.status(f"{type(ex).__name__}: {ex}")
            finally:
                await stop_child(self.proc)
                self.proc = None
            self.state["restarts"] += 1
            await asyncio.sleep(2)

    async def http_state(self, request):
        # kvmd-v4.120 HttpStreamerClientSession.get_state() unwraps result.
        result = {"encoder":{"type":"MPP H264","quality":0},
                  "source":{"online":self.state["online"],
                            "resolution": self.state["output"] or {"width":0,"height":0},
                            "desired_fps":self.config.fps},
                  "stream":{"clients":len(self.buffers)},
                  "h264":{"bitrate":self.config.bitrate_kbps,"gop":self.config.gop},
                  "t6":dict(self.state)}
        return web.json_response({"ok":True,"result":result})

    async def unsupported(self, request):
        return web.json_response({"ok":False,"error":"H264-only backend: JPEG stream/snapshot unavailable"},status=501)

    async def run(self, stop: asyncio.Event):
        frame_sock, http_sock = OwnedSocket(self.config.frame_socket),OwnedSocket(self.config.http_socket)
        server = runner = None
        worker = None
        lock_path = Path(self.config.frame_socket).with_suffix(".lock")
        lock_fd = os.open(lock_path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
        try:
            fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            server = await asyncio.start_unix_server(self.serve_client,sock=frame_sock.bind())
            app = web.Application(client_max_size=1024)
            app.router.add_get("/state",self.http_state)
            app.router.add_get("/snapshot",self.unsupported)
            app.router.add_get("/stream",self.unsupported)
            runner = web.AppRunner(app,access_log=None)
            await runner.setup()
            await web.SockSite(runner,http_sock.bind()).start()
            worker = asyncio.create_task(self.worker_loop())
            stop_waiter = asyncio.create_task(stop.wait())
            try:
                done,_ = await asyncio.wait([worker,stop_waiter],return_when=asyncio.FIRST_COMPLETED)
                if worker in done:
                    worker.result()
            finally:
                stop_waiter.cancel()
                await asyncio.gather(stop_waiter,return_exceptions=True)
        finally:
            if server:
                server.close()
                await server.wait_closed()
            if worker:
                worker.cancel()
                await asyncio.gather(worker,return_exceptions=True)
            clients = list(self.clients)
            for t in clients:
                t.cancel()
            await asyncio.gather(*clients,return_exceptions=True)
            if runner:
                await runner.cleanup()
            frame_sock.close()
            http_sock.close()
            os.close(lock_fd)

async def run(config):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM,signal.SIGINT):
        loop.add_signal_handler(sig,stop.set)
    await Broker(config).run(stop)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="t6-streamer 0.1.0")
    parser.add_argument("--features", action="store_true")
    parser.add_argument("--config",default="/etc/t6-kvm/streamer.toml")
    parser.add_argument("--unix")
    parser.add_argument("--desired-fps",type=int)
    parser.add_argument("--h264-bitrate",type=int)
    parser.add_argument("--h264-gop",type=int)
    args = parser.parse_args()
    if args.features:
        print("+ H264\n- JPEG\n- RGA")
        return
    config = load(args.config)
    override = {k:v for k,v in (("http_socket",args.unix),("fps",args.desired_fps),
                ("bitrate_kbps",args.h264_bitrate),("gop",args.h264_gop)) if v is not None}
    config = dataclasses.replace(config,**override).validate()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run(config))

if __name__ == "__main__":
    main()
