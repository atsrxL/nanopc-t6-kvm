#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Build in a new staging directory, not /usr or /etc. No apt, no service changes.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [[ $# != 5 || $1 != --apply || $2 != --sources || $4 != --output ]]; then
    echo "Build plan: pinned MPP + native worker + patched kvmd + dedicated Python 3.13 venv."
    echo "Usage: $0 --apply --sources /absolute/deps --output /absolute/new-stage"
    echo "No changes made. Read docs/BUILD.md first."
    exit 0
fi
SOURCES=$(realpath -e -- "$3")
OUT=$(realpath -m -- "$5")
[[ $OUT != *' '* && $OUT != / && $OUT != /opt/t6-kvm* ]] || { echo "Use a NEW user-owned work directory, without spaces" >&2; exit 2; }
[[ $(uname -m) == aarch64 || $(uname -m) == arm64 ]] || { echo 'Target stage requires AArch64; run offline tests on x86 instead' >&2; exit 2; }
[[ ! -e $OUT && ! -L $OUT ]] || { echo 'Output exists; refusing overwrite' >&2; exit 2; }
PYTHON=${PYTHON:-python3}
"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3,13), "Python 3.13 required"'
"$PYTHON" "$ROOT/tools/fetch_sources.py" --directory "$SOURCES" # read-only plan, not a fetch
"$PYTHON" - "$ROOT" "$SOURCES" <<'PY'
import json,subprocess,sys
from pathlib import Path
root,src=map(Path,sys.argv[1:])
for d in json.loads((root/'sources.lock.json').read_text())['dependencies']:
 p=src/d['name']
 got=subprocess.check_output(['git','-C',str(p),'rev-parse','HEAD'],text=True).strip()
 dirty=subprocess.check_output(['git','-C',str(p),'status','--porcelain','--untracked-files=no'],text=True).strip()
 if got!=d['commit'] or dirty: raise SystemExit(f'Wrong/dirty dependency: {p}')
PY
mkdir -p -- "$OUT"
exec > >(tee "$OUT/build.log") 2>&1
WORK="$OUT/.build"
mkdir -p "$WORK" "$OUT/bin" "$OUT/lib" "$OUT/share/extras" "$OUT/licenses"
# Build copies: upstream CMake writes generated files into its source directory.
cp -a "$SOURCES/mpp" "$WORK/mpp-src"
cp -a "$SOURCES/kvmd" "$WORK/kvmd-src"
cmake -S "$WORK/mpp-src" -B "$WORK/mpp-build" -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$OUT" -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_INSTALL_RPATH='$ORIGIN' -DBUILD_SHARED_LIBS=ON -DBUILD_TEST=OFF
cmake --build "$WORK/mpp-build" -j "${JOBS:-2}"
cmake --install "$WORK/mpp-build"
cmake -S "$ROOT" -B "$WORK/t6-build" -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DT6_BUILD_MPP=ON -DCMAKE_PREFIX_PATH="$OUT" -DCMAKE_INSTALL_PREFIX="$OUT"
cmake --build "$WORK/t6-build" -j "${JOBS:-2}"
ctest --test-dir "$WORK/t6-build" --output-on-failure
cmake --install "$WORK/t6-build"
"$PYTHON" "$ROOT/tools/patch_kvmd.py" "$WORK/kvmd-src" --apply > "$OUT/kvmd-applied.patch"
"$PYTHON" -m venv --copies --system-site-packages "$OUT/venv"
# No resolver/network activity here. Prepare documented system dependencies first.
"$OUT/venv/bin/python" -m pip install --no-index --no-deps --no-build-isolation "$ROOT" "$WORK/kvmd-src"
cp -a "$ROOT/tools" "$ROOT/config" "$ROOT/systemd" "$ROOT/docs" "$OUT/"
cp "$ROOT/sources.lock.json" "$ROOT/LICENSE" "$OUT/"
cp "$ROOT/tools/wrappers/"* "$OUT/bin/"
cp -a "$WORK/kvmd-src/contrib/keymaps" "$OUT/share/"
cp "$WORK/kvmd-src/t6-patch-manifest.json" "$OUT/"
# Keep exact license texts supplied by the fetched projects. References are not linked binaries.
for dep in kvmd mpp ustreamer librga; do
  mkdir -p "$OUT/licenses/$dep"
  find "$SOURCES/$dep" -maxdepth 1 -type f \( -iname 'LICENSE*' -o -iname 'COPYING*' -o -iname 'NOTICE*' \) \
      -exec cp '{}' "$OUT/licenses/$dep/" \;
  if [[ -d $SOURCES/$dep/LICENSES ]]; then cp -a "$SOURCES/$dep/LICENSES" "$OUT/licenses/$dep/"; fi
done
# These imports do not start capture, configure gadgets or bind sockets.
"$OUT/venv/bin/python" - <<'PY'
import importlib
for name in ['kvmd.apps.vnc','kvmd.apps.kvmd','kvmd.apps.otg','kvmd.apps.htpasswd','t6_kvm.kvmd_adapter']:
 importlib.import_module(name)
print('Pinned Python import smoke test passed; NOT a hardware test.')
PY
"$OUT/venv/bin/python" "$ROOT/tools/check_config.py" --directory "$ROOT/config" --prefix "$OUT" > "$OUT/config-validation.log"
"$OUT/venv/bin/python" -m pip freeze --all > "$OUT/python-environment.txt"
dpkg-query -W > "$OUT/debian-environment.txt"
ldd "$OUT/bin/t6-capture" > "$OUT/native-linkage.txt"
if grep -q "not found" "$OUT/native-linkage.txt"; then echo "Unresolved native dependencies" >&2; exit 2; fi
# Remove ONLY the build workspace just created by this invocation.
rm -rf -- "$WORK"
"$PYTHON" - "$OUT" <<'PY'
import hashlib,json,platform,sys,time
from pathlib import Path
p=Path(sys.argv[1]); (p/'release.json').write_text(json.dumps({
 'project':'t6-kvm','schema':1,'version':'0.1.0','architecture':platform.machine(),
 'built_at':time.time(),'kvmd_commit':'78ff181e95b14327831441d58f2f7f4cb2181cde',
 'hardware_validated':False,'target_acceptance':'NOT TESTED'},indent=2)+'\n')
# Build log is still open; it cannot have a stable digest yet.
rows={str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest()
      for f in p.rglob('*') if f.is_file() and not f.is_symlink() and f.name!='build.log'}
(p/'stage-sha256.json').write_text(json.dumps(rows,indent=2)+'\n')
PY
echo "Built stage: $OUT. No services installed/started; no target acceptance claim."
