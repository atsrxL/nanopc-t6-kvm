# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import dataclasses
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from t6_kvm.config import Config, load
from t6_kvm.protocol import *
from t6_kvm.buffer import FrameBuffer
from t6_kvm.ownership import Owner,Lease,HidOwner
from t6_kvm.daemon import Broker,OwnedSocket,stop_child

KEY_DATA=b'\x00\x00\x00\x01\x67\x11\x00\x00\x01\x68\x22\x00\x00\x01\x65\x33'
P_DATA=b'\x00\x00\x01\x41\x11'
def frame(seq=1,key=False,epoch=1,w=1920,h=1080):
    return Frame(AU,ONLINE|(KEY if key else 0),w,h,epoch,seq,seq*10000,KEY_DATA if key else P_DATA)

class ConfigTests(unittest.TestCase):
    def test_defaults_valid(self):
        self.assertEqual(Config().validate().fps,60)
    def test_unknown_key(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.toml"; p.write_text("fpss=30\n")
            with self.assertRaises(ValueError): load(str(p))
    def test_unsupported_scaling_is_error(self):
        with self.assertRaises(ValueError): dataclasses.replace(Config(),input_mode="4k-to-1440").validate()
    def test_no_fake_zero_copy(self):
        with self.assertRaises(ValueError): dataclasses.replace(Config(),copy_mode="zero-copy").validate()
    def test_boundaries(self):
        for change in ({"fps":0},{"fps":True},{"gop":0},{"max_height":2162},
                       {"expected_width":2560},{"queue_frames":9},{"bitrate_kbps":35001},
                       {"device":"relative"},{"expected_width":1919,"expected_height":1080},
                       {"http_socket":"/tmp/s","frame_socket":"/tmp/s"},
                       {"stall_seconds":float("nan")}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                dataclasses.replace(Config(),**change).validate()
    def test_native_bitrate_units(self):
        c=Config(); argv=c.native_argv()
        self.assertEqual(argv[argv.index("--bitrate")+1],"20000000")
    def test_native_1600_dimensions(self):
        c=dataclasses.replace(Config(),max_width=2560,max_height=1600,
                              expected_width=2560,expected_height=1600).validate()
        self.assertIn("1600",c.native_argv())
    def test_native_4k_dimensions(self):
        c=dataclasses.replace(Config(),max_width=3840,max_height=2160,
                              expected_width=3840,expected_height=2160).validate()
        self.assertIn("3840",c.native_argv())
        self.assertIn("2160",c.native_argv())
        with self.assertRaises(ValueError):dataclasses.replace(c,max_width=4096).validate()
    def test_1440_does_not_pretend_1080(self):
        c=dataclasses.replace(Config(),max_width=2560,max_height=1440,
                              expected_width=2560,expected_height=1440).validate()
        self.assertIn("2560",c.native_argv())

class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_byte_fragmented_input(self):
        reader=asyncio.StreamReader()
        async def feed():
            for byte in frame(key=True).pack():
                reader.feed_data(bytes([byte])); await asyncio.sleep(0)
            reader.feed_eof()
        task=asyncio.create_task(feed())
        self.assertEqual(await read_frame(reader),frame(key=True))
        await task
    async def test_coalesced_frames(self):
        r=asyncio.StreamReader(); r.feed_data(frame(key=True).pack()+frame(2).pack()); r.feed_eof()
        self.assertTrue((await read_frame(r)).key)
        self.assertEqual((await read_frame(r)).sequence,2)
    async def test_truncated_payload(self):
        r=asyncio.StreamReader();r.feed_data(frame(key=True).pack()[:-2]);r.feed_eof()
        with self.assertRaises(asyncio.IncompleteReadError): await read_frame(r)
    async def test_oversize_rejected_before_payload(self):
        r=asyncio.StreamReader();r.feed_data(HEADER.pack(MAGIC,1,AU,48,MAX_PAYLOAD+1,3,1920,1080,1,1,1))
        with self.assertRaises(ProtocolError): await asyncio.wait_for(read_frame(r),.1)
    async def test_invalid_header(self):
        for magic,version,hlen in ((b"NOPE",1,48),(MAGIC,2,48),(MAGIC,1,64)):
            r=asyncio.StreamReader();r.feed_data(HEADER.pack(magic,version,AU,hlen,1,3,2,2,1,1,1))
            with self.assertRaises(ProtocolError): await read_frame(r)
    async def test_status_round_trip(self):
        f=Frame.status(online=False,message="ENOLINK")
        r=asyncio.StreamReader();r.feed_data(f.pack());r.feed_eof()
        self.assertEqual(await read_frame(r),f)
    def test_sps_pps_required(self):
        with self.assertRaises(ProtocolError): dataclasses.replace(frame(key=True),data=b'\x00\x00\x01\x65\x01').validate()
    def test_idr_flag_cannot_lie(self):
        with self.assertRaises(ProtocolError): dataclasses.replace(frame(),flags=3).validate()
    def test_invalid_annexb(self):
        for data in (b"abc",b"\x00\x00\x01",b"\x00\x00\x01\x80"):
            with self.assertRaises(ProtocolError): nal_types(data)
    def test_c_wire_matches_python(self):
        binary=Path(__file__).resolve().parents[1]/"build-offline/t6-native-test"
        if not binary.exists(): self.skipTest("Build offline C target first")
        actual=subprocess.check_output([str(binary),"--wire"])
        expected=Frame(AU,3,1920,1080,0x0102030405060708,9,10000,KEY_DATA).pack()
        self.assertEqual(actual,expected)

class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_join_mid_gop(self):
        gate=RecoveryGate()
        self.assertFalse(gate.accept(frame(10)))
        self.assertTrue(gate.accept(frame(11,key=True)))
        self.assertTrue(gate.accept(frame(12)))
    def test_gap_blocks_dependent_frames(self):
        g=RecoveryGate(); self.assertTrue(g.accept(frame(key=True)))
        self.assertFalse(g.accept(frame(3))); self.assertFalse(g.accept(frame(4)))
        self.assertTrue(g.accept(frame(5,key=True)));self.assertTrue(g.accept(frame(6)))
    def test_epoch_needs_new_idr(self):
        g=RecoveryGate(); g.accept(frame(key=True))
        self.assertFalse(g.accept(frame(2,epoch=2)))
        self.assertTrue(g.accept(frame(3,key=True,epoch=2)))
    def test_resize_needs_idr(self):
        g=RecoveryGate();g.accept(frame(key=True))
        self.assertFalse(g.accept(frame(2,w=2560,h=1440)))
        self.assertTrue(g.accept(frame(3,key=True,w=2560,h=1440)))
    def test_status_resets(self):
        g=RecoveryGate();g.accept(frame(key=True));g.accept(Frame.status(message="offline"))
        self.assertFalse(g.accept(frame(2)))
    async def test_overflow_flushes_gop(self):
        requests=[]; q=FrameBuffer(2,lambda: requests.append(1))
        q.put(frame(key=True));q.put(frame(2));self.assertFalse(q.put(frame(3)))
        self.assertTrue(q.queue.empty()); self.assertTrue(requests)
        self.assertFalse(q.put(frame(4)))
        self.assertTrue(q.put(frame(5,key=True)))
        self.assertEqual((await q.get()).sequence,5)
    async def test_key_at_overflow_can_recover_immediately(self):
        q=FrameBuffer(1,lambda:None);q.put(frame(key=True));q.put(frame(10,key=True))
        self.assertEqual((await q.get()).sequence,10)

class OwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_password_does_not_kick(self):
        events=[]; owner=Owner(); a=Lease(lambda: events.append("kick")); b=Lease(lambda:None)
        self.assertTrue(await owner.admit(a,authenticated=True))
        self.assertFalse(await owner.admit(b,authenticated=False));self.assertIs(owner.owner,a)
        self.assertEqual(events,[])
    async def test_takeover_waits_cleanup(self):
        owner=Owner();events=[]
        def cancel():
            events.append("cancel")
            asyncio.get_running_loop().call_later(.01,lambda:(events.append("clear"),owner.release(a)))
        a=Lease(cancel);b=Lease(lambda:None)
        await owner.admit(a,authenticated=True)
        self.assertTrue(await owner.admit(b,authenticated=True));events.append("new")
        self.assertEqual(events,["cancel","clear","new"])
        owner.release(a); self.assertIs(owner.owner,b)
    async def test_reject_policy(self):
        owner=Owner("reject");a=Lease(lambda:self.fail("Must not kick")); b=Lease(lambda:None)
        await owner.admit(a,authenticated=True)
        self.assertFalse(await owner.admit(b,authenticated=True));self.assertIs(owner.owner,a)
    async def test_timeout_fails_closed(self):
        owner=Owner(timeout=.01);a=Lease(lambda:None);b=Lease(lambda:None)
        await owner.admit(a,authenticated=True)
        self.assertFalse(await owner.admit(b,authenticated=True));self.assertIs(owner.owner,a)
    async def test_concurrent_takeovers_serialize(self):
        owner=Owner();events=[]
        def lease(name):
            result=Lease(lambda:None)
            result.cancel=lambda:(events.append(name),owner.release(result))
            return result
        a,b,c=lease("a"),lease("b"),lease("c")
        await owner.admit(a,authenticated=True)
        results=await asyncio.gather(owner.admit(b,authenticated=True),owner.admit(c,authenticated=True))
        self.assertEqual(results,[True,True]);self.assertIs(owner.owner,c);self.assertEqual(events,["a","b"])
    def test_old_ws_cleanup_cannot_clear_new_keys(self):
        owner=HidOwner();a,b=object(),object();events=[]
        owner.added(a,lambda:events.append("add-a"));owner.added(b,lambda:events.append("add-b"))
        owner.removed(a,lambda:events.append("bad-clear"));self.assertNotIn("bad-clear",events)
        owner.removed(b,lambda:events.append("clear-b"));self.assertIsNone(owner.owner)

class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_child_reaped(self):
        import sys
        proc=await asyncio.create_subprocess_exec(sys.executable,"-c","import time;time.sleep(30)")
        await stop_child(proc)
        self.assertIsNotNone(proc.returncode)
        with self.assertRaises(ProcessLookupError): os.kill(proc.pid,0)
    def test_socket_refuses_existing_file(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"s";path.write_text("owned by someone else")
            with self.assertRaises(FileExistsError):OwnedSocket(str(path)).bind()
            self.assertEqual(path.read_text(),"owned by someone else")
    def test_socket_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"s";path.symlink_to("absent")
            with self.assertRaises(FileExistsError):OwnedSocket(str(path)).bind()
            self.assertTrue(path.is_symlink())
    def test_socket_cleanup_preserves_replacement(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"s"; owned=OwnedSocket(str(path));owned.bind()
            path.unlink();path.write_text("replacement");owned.close()
            self.assertEqual(path.read_text(),"replacement")
    def test_publish_reports_observed_geometry(self):
        b=Broker(Config()); b.publish(frame(key=True,w=1280,h=720))
        self.assertEqual(b.state["output"]["width"],1280)
        self.assertEqual(b.config.max_width,1920)
        b.status("unplugged");self.assertFalse(b.state["online"])
    async def test_socket_fragmentation_and_key_request(self):
        with tempfile.TemporaryDirectory() as d:
            requests=[]
            b=Broker(Config());b.request_key=lambda:requests.append(1)
            server=await asyncio.start_unix_server(b.serve_client,path=str(Path(d)/"f"))
            reader,writer=await asyncio.open_unix_connection(str(Path(d)/"f"))
            try:
                for _ in range(20):
                    if b.buffers:break
                    await asyncio.sleep(.005)
                self.assertTrue(b.buffers)
                b.publish(frame(key=True))
                self.assertTrue((await asyncio.wait_for(read_frame(reader),1)).key)
                writer.write(b"K");await writer.drain();await asyncio.sleep(.02)
                self.assertGreaterEqual(len(requests),2)
            finally:
                writer.close();await writer.wait_closed();server.close();await server.wait_closed()
                for _ in range(20):
                    if not b.clients:break
                    await asyncio.sleep(.005)
            self.assertFalse(b.clients)

if __name__=="__main__": unittest.main()
