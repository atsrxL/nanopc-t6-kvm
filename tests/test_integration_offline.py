# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixture-level integration; these are NOT real kvmd/TigerVNC/MPP tests."""
import ast
import asyncio
import dataclasses
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import types
import unittest
from unittest.mock import AsyncMock,Mock
import aiohttp
from t6_kvm.config import Config
from t6_kvm.daemon import Broker

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
patch=module('t6_patch_test',ROOT/'tools/patch_kvmd.py')
admin=module('t6_admin_test',ROOT/'tools/admin.py')

SERVER_FIXTURE='''from .render import make_text_jpeg
class _Client:
    def __init__(self):
        self.__fb_queue: "asyncio.Queue[dict]" = asyncio.Queue()
    async def run(self): pass
    async def _authorize_userpass(self,user,passwd): pass
    async def _on_authorized_vncpass(self): pass
    async def _authorize_none(self): pass
    async def __queue_frame(self,frame): pass
    async def __fb_sender_task_loop(self): pass
    async def __streamer_task_loop(self):
        frame = await read_frame(not self.__fb_has_key)
    async def _on_set_encodings(self): pass
'''

def transformed_client():
    tree=ast.parse(patch.transform_server(SERVER_FIXTURE))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef))
    cls.body=[n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name in
              ('_on_set_encodings','_authorize_userpass','_authorize_none')]
    namespace={'RfbError':RuntimeError,'get_logger':lambda _:types.SimpleNamespace(info=lambda *x:None),
               'claim_client':AsyncMock(return_value=True)}
    exec(compile(ast.Module(body=[cls],type_ignores=[]),'fixture','exec'),namespace)
    c=namespace['_Client']()
    c._Client__stage1_authorized=types.SimpleNamespace(is_passed=lambda:True,set_passed=Mock())
    c._Client__stage2_encodings_accepted=types.SimpleNamespace(set_passed=Mock())
    streamer=types.SimpleNamespace(get_state=AsyncMock(return_value={'features':{'quality':False}}),set_params=AsyncMock())
    c._Client__kvmd_session=types.SimpleNamespace(streamer=streamer,auth=types.SimpleNamespace(check=AsyncMock(return_value=True)))
    c._Client__kvmd=types.SimpleNamespace(make_session=lambda:c._Client__kvmd_session)
    c._Client__desired_fps=60;c._Client__t6_applied_encodings=None
    c._encodings=types.SimpleNamespace(has_h264=True,has_tight=True,tight_jpeg_quality=80)
    c._remote='offline-fixture'
    return c,namespace

class PatchTests(unittest.IsolatedAsyncioTestCase):
    def test_annotated_upstream_streamers_assignment(self):
        source='from .server import VncServer\ndef main():\n    streamers: list[BaseStreamerClient] = []\n    use(streamers)\n'
        result=patch.transform_init(source)
        self.assertIn('streamers = [T6StreamerClient(), T6JpegStreamerClient()]',result);compile(result,'fixture','exec')
    def test_plain_assignment_supported(self):
        source='from .server import VncServer\ndef main():\n    streamers = []\n'
        self.assertIn('[T6StreamerClient(), T6JpegStreamerClient()]',patch.transform_init(source))
    def test_missing_or_duplicate_anchor_rejected(self):
        for source in ('missing','xx anchor yy anchor'):
            with self.assertRaises(ValueError): patch.one(source,'anchor','replace')
    def test_all_server_transforms_compile(self):
        compile(patch.transform_server(SERVER_FIXTURE),'fixture','exec')
    def test_refuse_decorated_method(self):
        source='class X:\n    @decorator\n    def x(self): pass\n'
        with self.assertRaises(ValueError): patch.method(source,'X','x','def x(self): return 1')
    async def test_duplicate_set_encodings_does_not_reset_params(self):
        c,_=transformed_client()
        await c._on_set_encodings();await c._on_set_encodings()
        c._Client__kvmd_session.streamer.get_state.assert_awaited_once()
        c._Client__kvmd_session.streamer.set_params.assert_awaited_once_with(None,60)
    async def test_jpeg_client_without_h264_is_accepted(self):
        c,_=transformed_client();c._encodings.has_h264=False
        await c._on_set_encodings()
        c._Client__stage2_encodings_accepted.set_passed.assert_called_once_with(multi=True)
    async def test_missing_tight_is_rejected(self):
        c,_=transformed_client();c._encodings.has_tight=False
        with self.assertRaisesRegex(RuntimeError,'Tight'):await c._on_set_encodings()
    async def test_bad_password_never_calls_admission(self):
        c,n=transformed_client();c._Client__kvmd_session.auth.check.return_value=False
        self.assertFalse(await c._authorize_userpass('operator','wrong'))
        n['claim_client'].assert_not_awaited()
        c._Client__stage1_authorized.set_passed.assert_not_called()
    async def test_good_password_then_admission(self):
        c,n=transformed_client()
        self.assertTrue(await c._authorize_userpass('operator','correct'))
        c._Client__kvmd_session.auth.check.assert_awaited_once_with('operator','correct')
        n['claim_client'].assert_awaited_once_with(c)
        c._Client__stage1_authorized.set_passed.assert_called_once()
    async def test_no_none_auth(self):
        c,_=transformed_client();self.assertFalse(await c._authorize_none())
    def test_tls_patch_fail_closed(self):
        text='''class RfbClient:
    async def _send_fb_jpeg(self, data): pass
    def __init__(self):
        self.__symmap: dict[int, dict[int, int]] = {}
    async def auth(self):
        await self._write_struct("VeNCrypt auth types list", "B" + "L" * len(auth_types), len(auth_types), *auth_types)
        user = (await self._read_text("VeNCrypt user", user_length)).strip()
'''
        out=patch.transform_rfb(text);compile(out,'fixture','exec')
        self.assertIn('selected_auth = 262 if self.__x509_cert_path else 256',out)
        self.assertIn('passwd_length <= 4096',out)
        self.assertIn('self.__symmap: (dict[int, dict[int, int]] | None) = None',out)

class AdminTests(unittest.TestCase):
    def test_backup_rotates_only_owned_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);backup=p/'agent.backup';backup.mkdir(mode=0o700)
            src=p/'config';src.write_text('one')
            first=admin.backup_file(src,backup)
            foreign=first.with_name(first.name.replace('.json','.foreign.json'))
            foreign.write_text('{"project":"some-other-service"}')
            src.write_text('two');admin.backup_file(src,backup)
            src.write_text('three');admin.backup_file(src,backup)
            records=[x for x in backup.iterdir() if x!=foreign]
            self.assertEqual(len(records),2);self.assertTrue(foreign.exists());self.assertFalse(first.exists())
    def test_backup_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'real').write_text('secret');(p/'link').symlink_to(p/'real')
            with self.assertRaises(ValueError): admin.backup_file(p/'link',p/'backups')
    def test_atomic_refuses_symlink_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'real').mkdir();(p/'link').symlink_to(p/'real')
            with self.assertRaises(ValueError): admin.atomic(p/'link'/'file',b'x')
            self.assertFalse((p/'real'/'file').exists())
    def test_config_path_rejects_traversal_and_foreign_paths(self):
        for path in ('/etc/t6-kvm/../passwd', '/etc/passwd', 'etc/t6-kvm/main.yaml'):
            with self.assertRaises(ValueError): admin.checked_config_path(Path(path))
    def test_source_tree_is_not_installable_stage(self):
        with self.assertRaises((OSError,ValueError)): admin.check_stage(ROOT)
    def test_config_limits_follow_pinned_kvmd(self):
        import yaml
        cfg=yaml.safe_load((ROOT/'config/main.yaml').read_text())
        self.assertLessEqual(cfg['kvmd']['streamer']['h264_bitrate']['max'],20000)
        self.assertLessEqual(cfg['kvmd']['streamer']['h264_gop']['max'],60)
        self.assertFalse(cfg['vnc']['auth']['vncauth']['enabled'])

class DaemonFixtureTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_worker_process_http_and_clean_shutdown(self):
        # Deliberately non-decodable synthetic NAL fixtures; NEVER installed as a production backend.
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);native=d/'test-only-worker'
            native.write_text('#!'+sys.executable+'\n'+textwrap.dedent('''
                import os,time
                from t6_kvm.protocol import Frame,AU,ONLINE,KEY
                data=b'\\x00\\x00\\x01\\x67\\x11\\x00\\x00\\x01\\x68\\x22\\x00\\x00\\x01\\x65\\x33'
                n=0
                while True:
                    n+=1
                    os.write(1,Frame(AU,ONLINE|KEY,1920,1080,91,n,n*10000,data).pack())
                    time.sleep(.02)
            '''));native.chmod(0o755)
            cfg=dataclasses.replace(Config(),native=str(native),http_socket=str(d/'http.sock'),frame_socket=str(d/'frames.sock'))
            broker=Broker(cfg);stop=asyncio.Event();task=asyncio.create_task(broker.run(stop))
            try:
                for _ in range(300):
                    if broker.state['online']: break
                    if task.done(): task.result()
                    await asyncio.sleep(.01)
                self.assertTrue(broker.state['online'])
                proc=broker.proc
                async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=cfg.http_socket)) as session:
                    async with session.get('http://localhost/state') as r:
                        body=await r.json();self.assertEqual(r.status,200)
                        self.assertEqual(body['result']['source']['resolution']['width'],1920)
                        self.assertFalse(body['result']['t6']['hardware_validated'])
                    async with session.get('http://localhost/snapshot') as r: self.assertEqual(r.status,501)
            finally:
                stop.set();await asyncio.wait_for(task,5)
            self.assertIsNotNone(proc.returncode)
            self.assertFalse(Path(cfg.http_socket).exists());self.assertFalse(Path(cfg.frame_socket).exists())
