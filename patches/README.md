# Guarded patch generation

Run `python3 tools/patch_kvmd.py /path/to/pinned/kvmd` to print an ordinary unified diff. Nothing changes without `--apply`.

Accepted HEAD only: `78ff181e95b14327831441d58f2f7f4cb2181cde` (v4.120). Five files are affected: vnc/server.py, vnc/__init__.py, clients/streamer.py, kvmd/server.py, vnc/rfb/__init__.py. All edits are prepared and syntax-checked before writing; before/after SHA256 values are saved with the applied checkout.

This archive intentionally does not include a fabricated “applied upstream diff”: a full pinned checkout could not be downloaded into this environment. Unit tests exercise transformations on clearly labeled fixtures. The AArch64 build must apply them to the actual fixed source and preserve the resulting diff before installation.
