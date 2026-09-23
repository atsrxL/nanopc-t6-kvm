#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Save real AU payloads and timestamps for explicit target acceptance, not synthetic video."""
import argparse
import asyncio
import contextlib
import json
from pathlib import Path
import time
from t6_kvm.protocol import AU,read_frame,RecoveryGate

async def dump(sock: str,out: Path,seconds: float):
    out.mkdir(mode=0o750,parents=False,exist_ok=False)
    streams={};metrics={};gate=RecoveryGate();reader=writer=None
    began=time.monotonic(); deadline=began+seconds
    try:
        reader,writer=await asyncio.open_unix_connection(sock);writer.write(b'K');await writer.drain()
        with (out/'frames.jsonl').open('x') as log:
            while time.monotonic()<deadline:
                try: frame=await asyncio.wait_for(read_frame(reader),max(.01,deadline-time.monotonic()))
                except TimeoutError: break
                row={'arrival_monotonic':time.monotonic(),'kind':frame.kind,'epoch':frame.epoch,
                     'sequence':frame.sequence,'pts_us':frame.pts_us,'width':frame.width,'height':frame.height,
                     'bytes':len(frame.data),'key':frame.key}
                if frame.kind!=AU:
                    row['status']=json.loads(frame.data);gate.reset();writer.write(b'K');row['saved']=False
                elif gate.accept(frame):
                    row['saved']=True
                    if frame.epoch not in streams:
                        streams[frame.epoch]=(out/f'epoch-{frame.epoch:016x}.h264').open('xb')
                        metrics[frame.epoch]={'width':frame.width,'height':frame.height,'count':0,'first_pts_us':frame.pts_us}
                    streams[frame.epoch].write(frame.data)
                    m=metrics[frame.epoch];m['count']+=1;m['last_pts_us']=frame.pts_us
                else:
                    row['saved']=False;writer.write(b'K')
                log.write(json.dumps(row)+'\n');await writer.drain()
    finally:
        for f in streams.values(): f.close()
        if writer:
            writer.close()
            with contextlib.suppress(OSError): await writer.wait_closed()
        for m in metrics.values():
            dt=m.get('last_pts_us',m['first_pts_us'])-m['first_pts_us']
            m['saved_au_fps_from_pts']=(m['count']-1)*1e6/dt if dt>0 else None
        (out/'summary.json').write_text(json.dumps({'elapsed_seconds':time.monotonic()-began,
          'epochs':metrics,'hardware_acceptance':'NOT DETERMINED; independently decode and inspect frames.jsonl'},indent=2)+'\n')
    if not metrics: raise RuntimeError('No decodable-boundary AU sequence received; NOT a successful capture')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--socket',default='/run/t6-kvm/frames.sock')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--seconds',type=float,default=10)
    a=p.parse_args()
    if not 1<=a.seconds<=600: raise SystemExit('seconds must be 1..600')
    asyncio.run(dump(a.socket,a.output,a.seconds))
if __name__=='__main__': main()
