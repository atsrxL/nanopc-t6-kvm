#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in, isolated keyboard/mouse gadget using PINNED kvmd descriptors.

Refuses ANY existing gadget/HID nodes on start, including unbound gadgets.
Never mounts configfs, loads modules, changes role, touches EDID or networks.
This is a target-only experimental operation, NOT exercised by offline tests.
"""
import argparse
import contextlib
import grp
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time
from admin import atomic,write_json,no_symlink,ensure_stopped

ROOT=Path('/sys/kernel/config/usb_gadget')
GADGET=ROOT/'t6-kvm'
RUN=Path('/run/t6-kvm-otg')
OWNER=RUN/'owner.json'
UDC='fc000000.usb'
SERIAL='T6KVM001'
PROFILE='c.1'
def boot_id(): return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
def check_empty(root=ROOT,dev=Path('/dev'),udc=Path('/sys/class/udc')/UDC):
    if not root.is_dir() or not udc.is_dir(): raise ValueError('Existing configfs mount and expected UDC are required')
    if list(root.iterdir()): raise ValueError('An existing gadget is present (even if unbound); refusing takeover')
    if list(dev.glob('hidg*')): raise ValueError('Existing HID nodes; refusing ambiguous minor-number mapping')
    function=udc/'function'
    if function.exists() and function.read_text().strip(): raise ValueError('UDC is already in use')
def identity(path):
    s=path.stat();return [s.st_dev,s.st_ino]
def validate_owner():
    no_symlink(OWNER)
    r=json.loads(OWNER.read_text())
    if r.get('project')!='t6-kvm' or r.get('boot_id')!=boot_id(): raise ValueError('Gadget ownership/boot identity mismatch')
    if GADGET.exists() and r.get('gadget_identity')!=identity(GADGET): raise ValueError('Gadget inode changed; do not remove')
    return r
def allowed_tree():
    if (GADGET/'functions').exists():
        if {p.name for p in (GADGET/'functions').iterdir()}-{'hid.usb0','hid.usb1'}:
            raise ValueError('Unknown functions found; nothing removed')
    if (GADGET/'configs').exists() and {p.name for p in (GADGET/'configs').iterdir()}-{PROFILE}:
        raise ValueError('Unknown gadget configuration; nothing removed')
    if (GADGET/'strings/0x409/serialnumber').exists():
        value=(GADGET/'strings/0x409/serialnumber').read_text().strip()
        if value and value!=SERIAL: raise ValueError('Gadget serial changed; nothing removed')
def cleanup():
    validate_owner();allowed_tree()
    profile=GADGET/f'configs/{PROFILE}'
    if profile.exists():
        for link in profile.iterdir():
            if link.is_symlink() and (link.name not in ('hid.usb0','hid.usb1') or link.resolve()!=GADGET/'functions'/link.name):
                raise ValueError('Unexpected gadget link; nothing unbound or removed')
    if GADGET.exists():
        (GADGET/'UDC').write_text('\n')
        for n in (0,1):
            p=GADGET/f'configs/{PROFILE}/hid.usb{n}'
            if p.is_symlink():
                if p.resolve()!=GADGET/f'functions/hid.usb{n}': raise ValueError('Unknown function link')
                p.unlink()
        for rel in (f'configs/{PROFILE}/strings/0x409',f'configs/{PROFILE}',
                    'functions/hid.usb1','functions/hid.usb0','strings/0x409'):
            p=GADGET/rel
            if p.exists(): p.rmdir()
        GADGET.rmdir()
    OWNER.unlink()
    # RUN may contain operator evidence; never recursively delete it.
    with contextlib.suppress(OSError): RUN.rmdir()
def start():
    from kvmd.apps.otg.hid.keyboard import make_keyboard_hid
    from kvmd.apps.otg.hid.mouse import make_mouse_hid
    check_empty();ensure_stopped();no_symlink(RUN)
    if RUN.exists(): raise ValueError('Existing gadget work directory: inspect it; do not overwrite')
    gid=grp.getgrnam('t6-kvm').gr_gid
    RUN.mkdir(mode=0o750);os.chown(RUN,0,gid)
    r={'project':'t6-kvm','boot_id':boot_id(),'gadget_identity':None,'udc':UDC,'phase':'creating','nodes':{}}
    write_json(OWNER,r,mode=0o640,gid=gid)
    try:
        GADGET.mkdir();r['gadget_identity']=identity(GADGET);write_json(OWNER,r,mode=0o640,gid=gid)
        def put(rel,value): (GADGET/rel).write_text(str(value))
        for key,value in {'idVendor':'0x1d6b','idProduct':'0x0104','bcdUSB':'0x0200','bcdDevice':'0x0100'}.items(): put(key,value)
        (GADGET/'strings/0x409').mkdir()
        for key,value in {'manufacturer':'T6 KVM experimental','product':'T6 keyboard and absolute mouse','serialnumber':SERIAL}.items(): put('strings/0x409/'+key,value)
        profile=GADGET/f'configs/{PROFILE}';profile.mkdir();(profile/'strings/0x409').mkdir()
        (profile/'strings/0x409/configuration').write_text('T6 HID only')
        (profile/'MaxPower').write_text('250')
        for n,hid in enumerate((make_keyboard_hid(),make_mouse_hid(True,True))):
            f=GADGET/f'functions/hid.usb{n}';f.mkdir()
            for key,value in {'protocol':hid.protocol,'subclass':hid.subclass,'report_length':hid.report_length}.items(): (f/key).write_text(str(value))
            (f/'report_desc').write_bytes(hid.report_descriptor)
            if (f/'no_out_endpoint').exists(): (f/'no_out_endpoint').write_text('1')
            (profile/f'hid.usb{n}').symlink_to(f)
        put('UDC',UDC)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and not all(Path(f'/dev/hidg{n}').exists() for n in (0,1)): time.sleep(.1)
        if sorted(p.name for p in Path('/dev').glob('hidg*'))!=['hidg0','hidg1']: raise ValueError('Unexpected HID allocation; aborting')
        for n in (0,1):
            p=Path(f'/dev/hidg{n}');no_symlink(p);s=p.stat()
            if not stat.S_ISCHR(s.st_mode): raise ValueError('HID node is not a character device')
            os.chown(p,0,gid);os.chmod(p,0o660) # These nodes did not exist before this tool created the gadget.
            r['nodes'][str(p)]=[os.major(s.st_rdev),os.minor(s.st_rdev)]
        r['phase']='ready';write_json(OWNER,r,mode=0o640,gid=gid)
    except BaseException:
        # Best effort ONLY for our verified inode/whitelist; retain evidence on conflict.
        try: cleanup()
        except Exception as ex: print(f'Own partial gadget retained for inspection: {ex}')
        raise
    print('Created dedicated two-HID gadget. USB host enumeration/keys have NOT been validated.')
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['start','stop'])
    p.add_argument('--apply',action='store_true');p.add_argument('--i-reviewed-usb',action='store_true');a=p.parse_args()
    print(f'{a.action}: only {GADGET}, UDC {UDC}, two HID functions; no service start')
    if not a.apply: print('DRY RUN: no changes.');return
    if os.geteuid()!=0 or not a.i_reviewed_usb: raise SystemExit('Require root, --apply and --i-reviewed-usb')
    ensure_stopped()
    if a.action=='start': start()
    else: cleanup()
if __name__=='__main__': main()
