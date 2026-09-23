#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit dedicated credentials/certificate creation. Never a default password."""
import argparse
import grp
import ipaddress
import os
from pathlib import Path
import re
import subprocess
import tempfile
from admin import ETC,BASE,owned_dir,backup_file,atomic,ensure_stopped,no_symlink

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('user');p.add_argument('--replace-user',action='store_true')
    p.add_argument('--cert-name',required=True,help='Real client-visible DNS name or IP for certificate SAN')
    p.add_argument('--rotate-cert',action='store_true');p.add_argument('--apply',action='store_true');a=p.parse_args()
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}',a.user): raise SystemExit('Use a simple lowercase username')
    try: san='IP:'+str(ipaddress.ip_address(a.cert_name))
    except ValueError:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,250}',a.cert_name): raise SystemExit('Invalid certificate DNS name')
        san='DNS:'+a.cert_name
    print(f'Dedicated htpasswd user {a.user}, certificate SAN {san}. No service restart.')
    if not a.apply: print('DRY RUN: no changes');return
    if os.geteuid()!=0: raise SystemExit('Root required for --apply')
    owned_dir(ETC);owned_dir(BASE);ensure_stopped()
    gid=grp.getgrnam('t6-kvm').gr_gid
    for name in ('htpasswd','vnc.key','vnc.crt'): no_symlink(ETC/name)
    backup_file(ETC/'htpasswd')
    subprocess.run([str(BASE/'current/bin/t6-kvmd-htpasswd'),'set' if a.replace_user else 'add',a.user,'--quiet'],check=True)
    os.chmod(ETC/'htpasswd',0o640);os.chown(ETC/'htpasswd',0,gid)
    existing=any((ETC/n).exists() for n in ('vnc.key','vnc.crt'))
    if existing and not a.rotate_cert:
        print('Existing certificate/key preserved; --rotate-cert is required to replace them.');return
    with tempfile.TemporaryDirectory(prefix='.t6-cert-',dir=ETC) as tmp:
        key,crt=Path(tmp)/'key',Path(tmp)/'crt'
        subprocess.run(['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256',
                        '-nodes','-days','365','-subj','/CN='+a.cert_name,'-addext','subjectAltName='+san,
                        '-keyout',str(key),'-out',str(crt)],check=True)
        for dest,src in ((ETC/'vnc.key',key),(ETC/'vnc.crt',crt)):
            if dest.exists(): backup_file(dest)
            atomic(dest,src.read_bytes(),0o640,gid=gid)
    subprocess.run(['openssl','x509','-in',str(ETC/'vnc.crt'),'-noout','-fingerprint','-sha256'],check=True)
    print('Verify/pin this certificate in the client. No services started; private key was not printed.')
if __name__=='__main__': main()
