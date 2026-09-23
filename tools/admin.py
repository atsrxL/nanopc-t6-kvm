#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated install/rollback/uninstall. Every mutation requires --apply.

No apt, kernel, firewall, network, gadget, device permission, service start or
reboot actions. Uninstall retains releases, configs, account and backups.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import grp
import re
import shutil
import stat
import subprocess
import time

PROJECT='t6-kvm'
BASE=Path('/opt/t6-kvm')
ETC=Path('/etc/t6-kvm')
STATE=Path('/var/lib/t6-kvm')
BACKUPS=Path('/root/agent.backup')
UNITS=('t6-kvmd.service','t6-kvmd-vnc.service')

def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()
def no_symlink(p: Path):
    for item in (p,*p.parents):
        if item.is_symlink(): raise ValueError(f'Refusing symlink: {item}')
def atomic(path: Path, data: bytes, mode=0o600, uid=0, gid=0):
    no_symlink(path)
    tmp=path.with_name(path.name+f'.t6-new-{os.getpid()}')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(data);f.flush();os.fsync(f.fileno());os.fchmod(f.fileno(),mode)
            if os.geteuid()==0: os.fchown(f.fileno(),uid,gid)
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)
def write_json(path,obj,**kwargs):
    atomic(path,(json.dumps(obj,indent=2)+'\n').encode(),**kwargs)
def owned_dir(path,*,create=False,gid=0):
    no_symlink(path)
    marker=path/'.t6-owned'
    if path.exists():
        if not marker.is_file() or marker.read_text().strip()!=PROJECT:
            raise ValueError(f'Existing directory is not owned by this project: {path}')
        if path.stat().st_uid!=0 or path.stat().st_mode&0o022:
            raise ValueError(f'Unsafe ownership/mode: {path}')
    elif create:
        path.mkdir(mode=0o750,parents=False)
        if os.geteuid()==0: os.chown(path,0,gid)
        atomic(marker,(PROJECT+'\n').encode())
    else: raise ValueError(f'Project not installed: {path}')
def checked_config_path(path: Path) -> Path:
    """Reject path traversal and symlinks before reading a dedicated config."""
    if not path.is_absolute() or '..' in path.parts or not path.is_relative_to(ETC):
        raise ValueError('Only dedicated /etc/t6-kvm files may be selected')
    no_symlink(path)
    if not path.resolve().is_relative_to(ETC):
        raise ValueError('Config path escapes the dedicated directory')
    return path

def backup_file(path: Path,root=BACKUPS):
    """Only exact owned backup records are rotated, maximum two per source item."""
    no_symlink(path);no_symlink(root)
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Backup requires a regular, non-symlink file')
    root.mkdir(mode=0o700,parents=False,exist_ok=True)
    if root.stat().st_uid!=os.geteuid() or root.stat().st_mode&0o077:
        raise ValueError('Backup directory must be owner-only (0700); not changed automatically')
    s=path.stat(); key=hashlib.sha256(str(path).encode()).hexdigest()[:20]
    rec={'project':PROJECT,'path':str(path),'created_ns':time.time_ns(),
         'uid':s.st_uid,'gid':s.st_gid,'mode':stat.S_IMODE(s.st_mode),
         'data':base64.b64encode(path.read_bytes()).decode()}
    dest=root/f't6-kvm.{key}.{rec["created_ns"]}.json'
    write_json(dest,rec,uid=os.geteuid(),gid=os.getegid())
    owned=[]
    for p in root.glob(f't6-kvm.{key}.*.json'):
        if p.is_symlink(): continue
        try:
            r=json.loads(p.read_text())
            if r.get('project')==PROJECT and r.get('path')==str(path): owned.append((r['created_ns'],p))
        except (ValueError,OSError,KeyError): pass
    for _,old in sorted(owned)[:-2]: old.unlink()
    return dest

def ensure_stopped():
    for name in UNITS:
        p=subprocess.run(['systemctl','show',name,'--property=ActiveState','--value'],capture_output=True,text=True,check=True)
        if p.stdout.strip() not in ('inactive','failed',''):
            raise ValueError(f'Stop only {name} explicitly before this operation')
def read_manifest():
    owned_dir(BASE)
    p=BASE/'install.json';no_symlink(p)
    m=json.loads(p.read_text())
    if m.get('project')!=PROJECT: raise ValueError('Invalid install manifest')
    return m
def resolve_release(name):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}',name) or name in ('.','..'):
        raise ValueError('Invalid release identifier')
    p=BASE/'releases'/name;no_symlink(p)
    m=json.loads((p/'release.json').read_text())
    if m.get('project')!=PROJECT: raise ValueError('Foreign release')
    return p

def check_stage(stage):
    stage=stage.resolve(strict=True)
    rec=json.loads((stage/'release.json').read_text())
    if rec.get('project')!=PROJECT or rec.get('kvmd_commit')!='78ff181e95b14327831441d58f2f7f4cb2181cde':
        raise ValueError('Not an approved built stage; source ZIP cannot be installed directly')
    sums=json.loads((stage/'stage-sha256.json').read_text())
    for rel,expected in sums.items():
        p=stage/rel
        if Path(rel).is_absolute() or '..' in Path(rel).parts or p.is_symlink() or not p.resolve().is_relative_to(stage):
            raise ValueError('Unsafe stage hash entry')
        if digest(p)!=expected: raise ValueError(f'Stage hash mismatch: {rel}')
    for p in stage.rglob('*'):
        if p.is_symlink() and not p.resolve().is_relative_to(stage): raise ValueError(f'External stage symlink: {p}')
        if not (p.is_file() or p.is_dir() or p.is_symlink()): raise ValueError(f'Special stage file: {p}')
        if p.is_file() and not p.is_symlink() and p.name not in ('build.log','stage-sha256.json'):
            if str(p.relative_to(stage)) not in sums: raise ValueError(f'Unmanifested file: {p}')
    for name in ('bin/t6-capture','bin/t6-kvmd','bin/t6-kvmd-vnc','venv/bin/python'):
        if not (stage/name).is_file(): raise ValueError(f'Incomplete stage: {name}')
    return stage

def unit_conflicts(manifest):
    for name in UNITS:
        p=Path('/etc/systemd/system')/name;no_symlink(p)
        if p.exists() and digest(p)!=manifest.get('units',{}).get(name):
            raise ValueError(f'Foreign or locally modified unit; preserved: {p}')

def switch_release(name,manifest):
    resolve_release(name)
    cur=BASE/'current'
    if cur.exists() or cur.is_symlink():
        if not cur.is_symlink() or cur.resolve().parent!=BASE/'releases': raise ValueError('Foreign current path')
    if (BASE/'install.json').exists(): backup_file(BASE/'install.json')
    previous=manifest.get('current')
    tmp=BASE/f'.current-{os.getpid()}'
    if tmp.exists() or tmp.is_symlink(): raise ValueError('Unexpected pending current link')
    tmp.symlink_to(Path('releases')/name)
    os.replace(tmp,cur)
    manifest.update(project=PROJECT,current=name,previous=previous)
    write_json(BASE/'install.json',manifest)

def install(stage,name,apply):
    stage=check_stage(stage)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}',name): raise ValueError('Invalid release ID')
    initial=not BASE.exists()
    m={'project':PROJECT,'units':{}} if initial else read_manifest()
    for p in (ETC,STATE):
        if p.exists(): owned_dir(p)
    unit_conflicts(m)
    dest=BASE/'releases'/name
    if dest.exists() or dest.is_symlink(): raise ValueError('Release already exists; use another release ID')
    print(f'Install {stage} -> {dest}; create/update only {UNITS}; preserve config on upgrades; NO START')
    if not apply: return
    ensure_stopped()
    if initial:
        for lookup in (pwd.getpwnam,grp.getgrnam):
            try: lookup(PROJECT)
            except KeyError: continue
            raise ValueError('Dedicated account/group already exists without an install manifest')
        subprocess.run(['groupadd','--system',PROJECT],check=True)
        subprocess.run(['useradd','--system','--gid',PROJECT,'--home-dir','/nonexistent','--no-create-home','--shell','/usr/sbin/nologin',PROJECT],check=True)
    gid=grp.getgrnam(PROJECT).gr_gid
    owned_dir(BASE,create=True,gid=gid);owned_dir(ETC,create=True,gid=gid);owned_dir(STATE,create=True,gid=gid)
    releases=BASE/'releases';no_symlink(releases);releases.mkdir(mode=0o755,exist_ok=True)
    shutil.copytree(stage,dest,symlinks=True)
    # The builder runs as a normal account; installed executable code must not be writable by it.
    for p in (dest,*dest.rglob('*')):
        os.chown(p,0,0,follow_symlinks=False)
        if not p.is_symlink(): p.chmod(stat.S_IMODE(p.stat().st_mode)&~0o022)
    if initial:
        for fn in ('main.yaml','override.yaml','meta.yaml','platform','streamer.toml'):
            atomic(ETC/fn,(stage/'config'/fn).read_bytes(),0o640,gid=gid)
        (ETC/'override.d').mkdir(mode=0o750);os.chown(ETC/'override.d',0,gid)
        atomic(ETC/'htpasswd',b'',0o640,gid=gid) # Empty file = nobody authorized, not a default password.
    for name_ in UNITS:
        dest_unit=Path('/etc/systemd/system')/name_
        if dest_unit.exists(): backup_file(dest_unit)
        atomic(dest_unit,(stage/'systemd'/name_).read_bytes(),0o644)
        m['units'][name_]=digest(dest_unit)
    switch_release(name,m)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    print('Installed, disabled/not started by this tool. Credentials, USB and permissions remain explicit steps.')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=['install','rollback','uninstall','backup','restore'])
    p.add_argument('--stage',type=Path);p.add_argument('--release');p.add_argument('--path',type=Path)
    p.add_argument('--apply',action='store_true');a=p.parse_args()
    if a.apply and os.geteuid()!=0: raise SystemExit('Root required only for --apply')
    try:
        if a.operation=='install':
            if not a.stage or not a.release: raise ValueError('--stage and --release required')
            install(a.stage,a.release,a.apply)
        elif a.operation=='rollback':
            m=read_manifest();name=a.release or m.get('previous')
            if not name: raise ValueError('No previous release recorded')
            resolve_release(name);print(f'Switch only /opt/t6-kvm/current to {name}; configs unchanged; NO START')
            if a.apply: ensure_stopped();switch_release(name,m)
        elif a.operation=='uninstall':
            m=read_manifest();unit_conflicts(m)
            print('Remove only unmodified project unit files and owned current link; retain releases/configs/account/backups')
            if a.apply:
                ensure_stopped()
                if Path('/run/t6-kvm-otg/owner.json').exists(): raise ValueError('Stop owned gadget explicitly before uninstall')
                for name in UNITS:
                    subprocess.run(['systemctl','disable',name],check=True)
                    (Path('/etc/systemd/system')/name).unlink(missing_ok=True)
                cur=BASE/'current'
                if cur.is_symlink() and cur.resolve().parent==BASE/'releases': cur.unlink()
                elif cur.exists(): raise ValueError('Foreign current path; not removed')
                subprocess.run(['systemctl','daemon-reload'],check=True)
        elif a.operation=='backup':
            owned_dir(ETC)
            if not a.path: raise ValueError('--path required')
            checked_config_path(a.path);print(f'Back up {a.path} under {BACKUPS}, retain at most two owned copies')
            if a.apply: print(backup_file(a.path))
        else:
            owned_dir(ETC)
            if not a.path or a.path.parent!=BACKUPS: raise ValueError('Select a project JSON backup in /root/agent.backup')
            no_symlink(a.path);r=json.loads(a.path.read_text());dest=Path(r['path'])
            if r.get('project')!=PROJECT: raise ValueError('Not an owned config backup')
            checked_config_path(dest);data=base64.b64decode(r['data'],validate=True);print(f'Restore {dest}; NO START')
            if a.apply:
                ensure_stopped();backup_file(dest);atomic(dest,data,r['mode'],r['uid'],r['gid'])
    except (ValueError,OSError,KeyError,subprocess.CalledProcessError) as ex: raise SystemExit(str(ex)) from ex
    if not a.apply: print('DRY RUN: no changes performed.')
if __name__=='__main__': main()
