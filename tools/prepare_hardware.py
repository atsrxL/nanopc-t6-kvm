#!/usr/bin/env python3
"""Restore explicitly approved T6 hardware setup at boot; never take over gadgets."""
import grp
import json
import os
from pathlib import Path
import stat
import subprocess
import time
from gadget import start, validate_owner, allowed_tree, OWNER

def main():
    if os.geteuid()!=0:
        raise SystemExit('Root required')
    record=json.loads(Path('/var/lib/t6-kvm/hardware-reviewed.json').read_text())
    if record.get('reviewed') is not True or record.get('release')!=str(Path('/opt/t6-kvm/current').resolve()):
        raise SystemExit('Current release must have explicit hardware review')
    nodes=['/dev/video0','/dev/mpp_service','/dev/dri/renderD128',
           '/dev/dma_heap/system-uncached']
    for _ in range(60):
        if all(Path(n).exists() for n in nodes) and Path('/sys/class/udc/fc000000.usb').exists():
            break
        time.sleep(1)
    else:
        raise SystemExit('Required hardware not ready; no USB role changes made')
    edid=Path("/etc/t6-kvm/edid.bin")
    if edid.exists():
        subprocess.run(["python3",str(Path(__file__).with_name("apply_edid.py")),str(edid)],check=True)
    for n in nodes:
        if not stat.S_ISCHR(Path(n).stat().st_mode):
            raise SystemExit('Expected character device: '+n)
    subprocess.run(['setfacl','-m','u:t6-kvm:rw',*nodes],check=True)
    if OWNER.exists():
        owner=validate_owner();allowed_tree()
        if owner.get('phase')!='ready':
            raise SystemExit('Partial gadget needs inspection')
    else:
        start()
        owner=validate_owner()
    gid=grp.getgrnam('t6-kvm').gr_gid
    for n,identity in owner['nodes'].items():
        p=Path(n);s=p.stat()
        if p.is_symlink() or not stat.S_ISCHR(s.st_mode) or [os.major(s.st_rdev),os.minor(s.st_rdev)]!=identity:
            raise SystemExit('HID identity changed')
        os.chown(p,0,gid);os.chmod(p,0o660)

if __name__=='__main__':
    main()
