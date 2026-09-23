#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fetch exact public commits, never install software. Dry-run unless --apply."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
def call(*args):
    return subprocess.check_output(list(args),text=True).strip()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,default=ROOT/'deps')
    p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    for dep in json.loads((ROOT/'sources.lock.json').read_text())['dependencies']:
        dest=a.directory.resolve()/dep['name']
        print(f"{dep['name']}: {dep['commit']} -> {dest} ({dep['usage']})",flush=True)
        if not a.apply: continue
        if dest.is_symlink(): raise SystemExit(f'Refusing symlink: {dest}')
        if not dest.exists():
            dest.mkdir(parents=True)
            subprocess.run(['git','init','--quiet',str(dest)],check=True)
            subprocess.run(['git','-C',str(dest),'remote','add','origin',dep['repository']],check=True)
            subprocess.run(['git','-C',str(dest),'-c','protocol.file.allow=never','fetch','--depth=1','origin',dep['commit']],check=True)
            subprocess.run(['git','-C',str(dest),'checkout','--detach',dep['commit']],check=True)
        if call('git','-C',str(dest),'rev-parse','HEAD')!=dep['commit']:
            raise SystemExit(f'Existing checkout is not the required commit: {dest}; nothing overwritten')
        if call('git','-C',str(dest),'status','--porcelain','--untracked-files=no'):
            raise SystemExit(f'Existing checkout is dirty: {dest}')
    if not a.apply: print('DRY RUN: no network requests or files written.')
if __name__=='__main__': main()
