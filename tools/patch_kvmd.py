#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Apply reviewable AST-targeted modifications only to clean pinned kvmd source.

Dry-run by default. All files are transformed and syntax-checked before writes.
An ordinary unified diff is emitted for review; no rewriting of RFB core.
"""
import argparse
import ast
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import textwrap

COMMIT = "78ff181e95b14327831441d58f2f7f4cb2181cde"

def one(s,old,new):
    if s.count(old)!=1:
        raise ValueError(f"Expected exactly one anchor: {old[:100]!r}; found {s.count(old)}")
    return s.replace(old,new,1)

def method(s,cls,name,new):
    tree=ast.parse(s)
    found=[n for c in tree.body if isinstance(c,ast.ClassDef) and c.name==cls
           for n in c.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
    if len(found)!=1:
        raise ValueError(f"Expected {cls}.{name}")
    n=found[0]
    if n.decorator_list:
        raise ValueError(f"Unexpected decorators: {cls}.{name}")
    lines=s.splitlines(keepends=True)
    lines[n.lineno-1:n.end_lineno]=[textwrap.indent(textwrap.dedent(new).strip()+"\n","    ")]
    return "".join(lines)

def transform_server(s):
    s=one(s,"from .render import make_text_jpeg", "from .render import make_text_jpeg\n"
          "from t6_kvm.kvmd_adapter import (VncFrameBuffer, begin_client, claim_client, finish_client)\n"
          "from t6_kvm.protocol import Frame as T6Frame, RecoveryGate as T6Gate")
    s=one(s,'self.__fb_queue: "asyncio.Queue[dict]" = asyncio.Queue()',
          'self.__fb_queue = VncFrameBuffer(self.__t6_request_key)\n        self.__t6_applied_encodings = None')
    s=method(s,"_Client","run",'''
        async def run(self) -> None:
            begin_client(self)
            try:
                await self._run(kvmd=self.__kvmd_task_loop(),
                                streamer=self.__streamer_task_loop(),
                                fb_sender=self.__fb_sender_task_loop())
            finally:
                try:
                    await aiotools.shield_fg(self.__cleanup())
                finally:
                    finish_client(self)
    ''')
    s=method(s,"_Client","_authorize_userpass",'''
        async def _authorize_userpass(self, user: str, passwd: str) -> bool:
            self.__kvmd_session = self.__kvmd.make_session()
            if not user or not (await self.__kvmd_session.auth.check(user, passwd)):
                return False
            if not (await claim_client(self)):
                return False
            self.__stage1_authorized.set_passed()
            return True
    ''')
    s=method(s,"_Client","_on_authorized_vncpass",'''
        async def _on_authorized_vncpass(self) -> None:
            self.__kvmd_session = self.__kvmd.make_session()
            if not (await claim_client(self)):
                raise RfbError("T6: existing controller retained; takeover/reject policy")
            self.__stage1_authorized.set_passed()
    ''')
    s=method(s,"_Client","_authorize_none",'''
        async def _authorize_none(self) -> bool:
            return False  # Dedicated T6 instance never permits network None auth.
    ''')
    s=method(s,"_Client","__queue_frame",'''
        def __t6_request_key(self) -> None:
            self.__fb_has_key = False
            for streamer in self.__streamers:
                request = getattr(streamer, "request_key", None)
                if request:
                    request()

        async def __queue_frame(self, frame: (dict | str)) -> None:
            if isinstance(frame, str):
                frame = await self.__make_text_frame(frame)
                self.__t6_request_key()
            if not self.__fb_queue.put(frame):
                self.__t6_request_key()
    ''')
    s=method(s,"_Client","__fb_sender_task_loop",'''
        async def __fb_sender_task_loop(self) -> None:
            gate = T6Gate()
            async for _ in self._send_fb_allowed():
                while True:
                    frame = await self.__fb_queue.get()
                    if frame["format"] != StreamerFormats.H264:
                        gate.reset()
                        self.__fb_has_key = False
                        break
                    if gate.accept(T6Frame.from_kvmd(frame)):
                        break
                    self.__t6_request_key()
                if (self._width, self._height) != (frame["width"], frame["height"]):
                    self.__shared_params.width = frame["width"]
                    self.__shared_params.height = frame["height"]
                    if not self._encodings.has_resize:
                        raise RfbError("T6: resolution changed; client lacks resize; reconnect")
                    await self._send_resize(frame["width"], frame["height"])
                if frame["format"] == StreamerFormats.JPEG:
                    await self._send_fb_jpeg(frame["data"])
                else:
                    if not self._encodings.has_h264:
                        raise RfbError("T6: client withdrew H264; no live JPEG fallback")
                    await self._send_fb_h264(frame["data"])
                    self.__fb_has_key = True
    ''')
    s=method(s,"_Client","_on_set_encodings",'''
        async def _on_set_encodings(self) -> None:
            assert self.__stage1_authorized.is_passed()
            assert self.__kvmd_session
            if not self._encodings.has_h264:
                raise RfbError("T6 requires negotiated H264 support in the actual TigerVNC build; "
                               "JPEG live video is not implemented")
            if not self._encodings.has_tight:
                raise RfbError("T6 requires Tight support for offline diagnostic screens")
            selected = (self._encodings.tight_jpeg_quality, self.__desired_fps, True)
            if selected != self.__t6_applied_encodings:
                has_quality = (await self.__kvmd_session.streamer.get_state())["features"]["quality"]
                quality = self._encodings.tight_jpeg_quality if has_quality else None
                await self.__kvmd_session.streamer.set_params(quality, self.__desired_fps)
                self.__t6_applied_encodings = selected
                get_logger(0).info("%s [T6]: negotiated H264=True, fps cap=%d", self._remote, self.__desired_fps)
            self.__stage2_encodings_accepted.set_passed(multi=True)
    ''')
    ast.parse(s)
    return s

def transform_init(s):
    s=one(s,"from .server import VncServer","from .server import VncServer\nfrom t6_kvm.kvmd_adapter import T6StreamerClient")
    # Exact AST assignment, not a greedy cross-file regex.
    tree=ast.parse(s)
    matches=[]
    for n in ast.walk(tree):
        targets = n.targets if isinstance(n, ast.Assign) else ([n.target] if isinstance(n, ast.AnnAssign) else [])
        if any(isinstance(t, ast.Name) and t.id == "streamers" for t in targets):
            matches.append(n)
    if len(matches)!=1:
        raise ValueError("Could not identify streamers assignment")
    node=matches[0]; lines=s.splitlines(keepends=True)
    lines[node.lineno-1:node.end_lineno]=["    streamers = [T6StreamerClient()]\n"]
    return "".join(lines)

def transform_streamer(s):
    s=one(s,"import ustreamer\n", "try:\n    import ustreamer\nexcept ModuleNotFoundError as ex:\n"
          "    if ex.name != 'ustreamer':\n        raise\n    ustreamer = None\n")
    return one(s,"            with ustreamer.Memsink(**self.__kwargs) as sink:",
               "            if ustreamer is None:\n                raise StreamerPermError('Optional ustreamer memsink module absent')\n"
               "            with ustreamer.Memsink(**self.__kwargs) as sink:")

def transform_kvmd(s):
    s=method(s,"KvmdServer","_on_ws_added",'''
        def _on_ws_added(self, ws: WsSession) -> None:
            self.__auth_manager.start_ws_session(ws.token)
            self.__hid.clear_events()
            self.__t6_hid_owner = ws
            self.__streamer_notifier.notify()
    ''')
    return method(s,"KvmdServer","_on_ws_removed",'''
        def _on_ws_removed(self, ws: WsSession) -> None:
            self.__auth_manager.stop_ws_session(ws.token)
            if getattr(self, "_KvmdServer__t6_hid_owner", None) is ws:
                self.__hid.clear_events()
                self.__t6_hid_owner = None
            self.__streamer_notifier.notify()
    ''')


def transform_rfb(s):
    # Restrict the existing VeNCrypt negotiation; no new RFB implementation.
    anchor='        await self._write_struct("VeNCrypt auth types list", "B" + "L" * len(auth_types), len(auth_types), *auth_types)'
    s=one(s, anchor, '        if 262 not in auth_types:\n'
          '            raise RfbError("T6 requires certificate-backed X509Plain authentication")\n'
          '        auth_types = {262: auth_types[262]}  # No plaintext/anonymous TLS downgrade\n'+anchor)
    anchor='        user = (await self._read_text("VeNCrypt user", user_length)).strip()'
    return one(s, anchor, '        if not 0 < user_length <= 256 or not 0 < passwd_length <= 4096:\n'
               '            raise RfbError("T6: credential length exceeds bounded handshake limits")\n'+anchor)

TRANSFORMS={"kvmd/apps/vnc/server.py":transform_server,
            "kvmd/apps/vnc/__init__.py":transform_init,
            "kvmd/clients/streamer.py":transform_streamer,
            "kvmd/apps/kvmd/server.py":transform_kvmd,
            "kvmd/apps/vnc/rfb/__init__.py":transform_rfb}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("checkout",type=Path)
    p.add_argument("--apply",action="store_true")
    args=p.parse_args(); root=args.checkout.resolve()
    def git(*argv):
        return subprocess.check_output(["git","-C",str(root),*argv],text=True).strip()
    if git("rev-parse","HEAD")!=COMMIT:
        raise SystemExit("Refusing non-pinned kvmd commit (uploaded modern snapshots are NOT this baseline)")
    if git("status","--porcelain","--untracked-files=no"):
        raise SystemExit("Refusing dirty checkout; review/recreate a fresh source worktree")
    # Verify upstream auth endpoint retains the socket-credential exclusion.
    auth=(root/"kvmd/apps/kvmd/api/auth.py").read_text()
    if '@exposed_http("GET", "/auth/check", allow_usc=False)' not in auth:
        raise SystemExit("Authentication contract changed; manual review required")
    changes={}; hashes={}
    for rel,transform in TRANSFORMS.items():
        path=root/rel
        if path.is_symlink():
            raise SystemExit("Refusing symlink source")
        old=path.read_text(); new=transform(old); compile(new,rel,"exec")
        changes[rel]=new
        hashes[rel]={"before":hashlib.sha256(old.encode()).hexdigest(),
                     "after":hashlib.sha256(new.encode()).hexdigest()}
        print("".join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),
                                         fromfile="a/"+rel,tofile="b/"+rel)),end="")
    if args.apply:
        written=[]
        originals={rel:(root/rel).read_text() for rel in changes}
        try:
            for rel,new in changes.items():
                (root/rel).write_text(new); written.append(rel)
            (root/"t6-patch-manifest.json").write_text(json.dumps({"commit":COMMIT,"files":hashes},indent=2)+"\n")
        except BaseException:
            for rel in written:
                (root/rel).write_text(originals[rel])
            raise

if __name__=="__main__":
    main()
