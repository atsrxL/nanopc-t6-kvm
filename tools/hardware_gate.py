#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only service startup gate. Approval is an explicit operator-created record.

The approval record binds to the exact release; it is NOT an acceptance result.
"""
import json
import os
from pathlib import Path
import stat
from t6_kvm.config import load
from gadget import validate_owner,UDC

def main():
    cfg=load('/etc/t6-kvm/streamer.toml')
    rec=json.loads(Path('/var/lib/t6-kvm/hardware-reviewed.json').read_text())
    release=str(Path('/opt/t6-kvm/current').resolve())
    if rec.get('reviewed') is not True or rec.get('release')!=release:
        raise SystemExit('Explicit hardware review must match current release; never copy an old approval blindly')
    owner=validate_owner()
    if owner.get('phase')!='ready' or owner.get('udc')!=UDC: raise SystemExit('Own gadget is not ready')
    for name in (cfg.device,'/dev/mpp_service','/dev/hidg0','/dev/hidg1'):
        p=Path(name);s=p.stat()
        if not stat.S_ISCHR(s.st_mode) or not os.access(p,os.R_OK|os.W_OK):
            raise SystemExit(f'Service account has no approved read/write access to {p}')
        if name in owner['nodes'] and [os.major(s.st_rdev),os.minor(s.st_rdev)]!=owner['nodes'][name]:
            raise SystemExit('HID device identity changed')
    print('Startup safety checks passed; NOT an HDMI/MPP/TigerVNC acceptance result')
if __name__=='__main__': main()
