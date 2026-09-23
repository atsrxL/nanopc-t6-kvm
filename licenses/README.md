# License and upstream provenance

New project source and the kvmd derivative patch are GPL-3.0-or-later. See ../LICENSE.

No full kvmd, uStreamer, MPP or librga checkout, prebuilt vendor library, third-party font, or target binary is bundled as a runtime dependency in this source archive. The original user-supplied handoff archive is retained verbatim for provenance; it includes upstream reference snippets and notices.

Core dependency licenses and exact commits are recorded in ../sources.lock.json. kvmd/uStreamer are GPL-3.0-or-later; Rockchip MPP includes Apache-2.0 and per-file SPDX alternatives such as Apache-2.0 OR MIT; librga carries its own COPYING/per-file notices. Do not replace per-file notices with the project license.

The target build script preserves top-level LICENSE/COPYING/NOTICE files and LICENSES directories from each actual fetched checkout. Before redistributing a built stage, review the exact collected notices and provide corresponding source as required for the components you actually distribute. The lock file and fetch script are provenance aids, not a legal clearance or a complete transitive SBOM.
