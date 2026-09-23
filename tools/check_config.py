#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate the full configuration against PINNED installed kvmd, without startup."""
import argparse
from pathlib import Path
import tempfile
from kvmd.apps import ConfigPaths, _init_config
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--directory',type=Path,default=Path('/etc/t6-kvm'))
p.add_argument('--prefix',type=Path,help='Substitute the staged release path during schema-only build checks')
a=p.parse_args(); d=a.directory.resolve()
with tempfile.TemporaryDirectory(prefix='t6-config-check-') as temp:
    empty=Path(temp)/'empty';empty.mkdir()
    override=d/'override.d'
    main=d/'main.yaml'
    if a.prefix:
        staged=Path(temp)/'main.yaml'
        staged.write_text(main.read_text().replace('/opt/t6-kvm/current',str(a.prefix.resolve())))
        main=staged
    cfg=_init_config(ConfigPaths(str(main),str(d/'legacy-auth.yaml'),str(override if override.is_dir() else empty),str(d/'override.yaml')),{},load_all=True)
    assert cfg.kvmd.auth.enabled and not cfg.vnc.auth.vncauth.enabled
    assert cfg.kvmd.atx.type=='disabled' and cfg.kvmd.msd.type=='disabled'
    print('PASS: kvmd configuration schema/import validation; no services or hardware started')
