## EDID deployment and source readback

Added 2560x1440@59.9506 and 2560x1600@59.9716 DTDs within existing two-block EDID, retained 1080p preferred timing and CTA 4K video codes. Both checksums valid; T6 ioctl write/readback exact. PC EDID readback independently decoded both new timings. PC normal DRM modes list still omits them (driver filtering remains unresolved). 1080p stream recovered at 59.99fps. Boot helper persists EDID from /etc/t6-kvm/edid.bin before starting capture. Backup /root/agent.backup/t6-edid-20260923-161502. No source reboot or boot override.

## 1440p60 and 1600p60 native modes

Extended tightly-packed DMA-BUF import to BGR888 with byte stride width*3, MPP hardware RGB conversion. Real CVT-RB HDMI 2560x1440@59.9466 produced 601 frames, 59.9503fps; 2560x1600@59.9680 produced 600 frames, 59.9740fps. Both no sequence gaps and complete independent decode. Static color bars decoded; colorimetric precision not calibrated. No scaling; dimensions follow HDMI timing. Source DRM temporary modesets restore 1080p; EDID unchanged (these modes may not appear in normal OS selection). Backup /root/agent.backup/t6-rgb-dma. First CPU-copy 1440 trial ~39fps, optimized BGR import ~60fps. Existing 4K NV12 branch retained.

## Real 4K60 achieved with DMA-BUF import

Native tightly packed one-plane NV12 (64-aligned width, 16-aligned height, exact sizeimage) now exports V4L2 buffers and imports into MPP; retain dequeued buffer until synchronous encoded AU completes, then QBUF. Explicit CPU fallback if export/import/layout is unavailable. No frame-pixel memcpy on eligible path. Real 4K60 HDMI: 1200 frames in 20 seconds, 60.0187 fps, zero sequence gaps, all 1200 frames independently decoded. Second moving-pattern run: 600 frames in 10 seconds, 60.0041 fps; independent decode checked separately. Input ~59.996Hz, output status 60.0fps, copy_mode DMABUF import. Source modeset is temporary and auto-restores 1080p. Client 4K60 rendering and long soak not yet certified. Source/runtime small worker_status copy flag normalization applies next streamer restart; copy_mode is already correct. Artifact clips remain in T6 hwtest; build retained VM301 /root/t6-kvm-artifacts-20260923/dmabuf. Temporary build removed and one-hour VM301 graceful shutdown scheduled. Backup /root/agent.backup/t6-dmabuf.

## Real HDMI 4K60 tests and NV12 fix

PC DRM temporary modeset successfully produced 3840x2160p59.996. Actual receiver format NV12, one plane, stride 3840, sizeimage 12441600, colorspace REC709, ycbcr_enc XV709, limited range. Allowed XV709 matrix (same BT709 coefficients) while preserving YUV code values; gamut behavior not calibrated. Initial CPU staging pipeline yielded 32.63 fps. Added bounded native NV12 direct copy to MPP buffer with correct padded Y/UV placement: 37.69 fps; 452 live HDMI frames captured over 12.02 seconds. This is 4K60 INPUT with ~38 fps OUTPUT, not achieved 4K60 encoding throughput. Temporary source modesets auto-restore 1080p after 90s. Original 1080p pipeline still measured 59.99fps. No persistent source display or EDID change. Raw clip retained on T6 hwtest/live4k.h264. Remaining optimization: DMABUF import or capture/encode pipelining, not yet implemented.

## Native 4K software preparation deployed

Worker/config validator now allow 3840x2160; H264 Level 5.2 selected by macroblock-rate budget. NV12 chroma uses row memcpy. Rate cap uses signal cadence rather than dequeue wall time, avoiding scheduling-jitter drops. Deployed backup /root/agent.backup/t6-4k-20260923-153943. 1080p regression: 59.88 fps, capture/encode counts identical, no worker restarts. 4K BGR/NV12 boundary tests pass under x86 ASan/UBSan and native ARM. MPP encoded 120 synthetic 3840x2160 frames in 1.727s while main 1080p remained active; ffprobe independently decoded 120 frames and reported level 52. NOT a true HDMI 4K60 benchmark. Source MS-A2 DRM exposes only 1080p max despite EDID VIC97; no EDID/mode/boot edits made. Real 4K capture performance, CMA allocation and client display still unverified. Build VM301 started by this task; temporary build removed, binary/source retained in /root/t6-kvm-artifacts-20260923/4k. One-hour graceful VM shutdown timer t6-build301-cleanup scheduled; MS-A2 host left running.

## Port 5899 management panel deployed

Authenticated LAN panel enabled at 192.168.123.99:5899. Live GET status and POST save passed; unauthorized GET returned 401. Continuous mode true/false checked against fresh RFB encoding negotiation; final mode false. Three isolated panel tests passed: authentication/CSRF, invalid bitrate preserving configuration, and bitrate/mode/account/password update with old credentials rejected. No real password was changed for tests. Real bitrate restart not exercised; configuration behavior verified in isolation. Service unit and module added to source, deployed manually. HTTP UI not yet visually reviewed in a browser. Backup: t6-panel-deploy-20260923-152009 (check exact directory on device). End-to-end latency explicitly unavailable; TCP RTT is shown separately.

## Tight/JPEG fallback deployed

Added T6JpegStreamerClient using PyAV 16.1.0 H264 decode and Pillow JPEG quality 70, capped at 15 fps, sharing the existing capture AU source. Native H264 remains first preference. JPEG-only RFB test authenticated with VNCAuth and decoded 159 complete 1920x1080 JPEGs over 12 seconds (13.24 fps, 5 distinct hashes; scene largely static). Real Jump Desktop 192.168.123.58 connected at 15:06:57, selected Tight/JPEG and remained streaming in subsequent logs. Regression: 58 tests, 57 pass, 1 skip. Input is unchanged but no new end-to-end input assertion was completed in this JPEG-specific test. Backup: /root/agent.backup/t6-jpeg-20260923-145952. Runtime dependency installed only in dedicated venv. Source dependencies and build instructions updated. Full release archive/provenance manifests not regenerated.

## Jump Desktop live negotiation diagnosis

Actual Jump connections from 192.168.123.58 at 14:56:05 and 14:56:18 passed VNCAuth. Offered encodings: [-239,-223,-26,1,2,5,6,7,8,16,1101]; Tight JPEG quality 70, no H264 encoding 50. T6 explicitly rejected via its H264-only SetEncodings guard. Therefore auth compatibility is fixed, but live JPEG/Tight fallback is needed for this client's advertised capabilities. Do not remove H264 guard without implementing a real compatible live video source. Current mode remains request-paced.

## Pacing diagnosis with fixed-60-Hz test screen

20-second side subscription: 1178 encoded frames, no AU sequence gaps. Capture/dequeue interval median 16.667 ms, P95 16.717 ms, P99 29.226 ms, max 31.914 ms; 22 intervals exceeded 25 ms. Delivery interval median 16.669 ms, P99 28.975 ms, max 34.877 ms. Dequeue-to-delivery median 13.747 ms, max 18.461 ms. Test display measured 60.0005 fps with no missed deadlines. No mouse events observed during parallel sampling, so no input-rate conclusion. Current viewer TCP RTT approximately 8 ms; prior Mac RTT does not describe this path. No pacing fix deployed from these measurements yet. Evidence on T6: hwtest/pacing-baseline.json and vnc-network-samples.json. Dequeue timestamps alone cannot distinguish driver/capture jitter from software rate-limit drops; source currently resets due to now + period, making jitter-induced drops plausible but unproven.

## ContinuousUpdates restored for comparison

Owner reported stutter in request mode and requested continuous push. Restored upstream -313 negotiation and removed the encoding-disable source transform/test. Kept bounded transport buffers and no send-abort timeout. Restarted VNC and reopened mouse test on VT11. Prior request-mode measurements below describe the superseded trial.

## Request-paced VNC deployment (2026-09-23)

Disabled server advertisement of ContinuousUpdates (-313) in pinned RFB encoding negotiation. Client-paced framebuffer requests now control video delivery, retaining bounded GOP-aware queues and transport buffers without disconnect deadlines. Real test offered -313, received no push negotiation, paused requests for 3 seconds with no unsolicited video and retained the same connection. First resumed AU arrived in 1.33 ms; subsequent 4 Hz requests remained connected; full-speed reception recovered to 58.39 fps. This measures delivery, not the age of that first AU. Regression suite: 58 tests, 57 passed and 1 skipped. Backup: /root/agent.backup/t6-vnc-pull-20260923-142447. Windows user reproduction still needs validation. Higher RTT may reduce request-paced throughput.

## Correction: keep slow clients connected

Removed the newly introduced 500 ms send-abort policy at owner request; retained bounded transport buffers and normal async backpressure. Deployed and restarted VNC. Three transport unit tests pass, including a 600 ms slow drain that does not abort. Previous slow-receiver disconnect test below describes superseded behavior. Background/fullscreen latency fix is not yet verified.

## VNC slow-receiver guard (2026-09-23)

Deployed vnc_transport.py and patched RFB stream writes to bound transport buffering and abort a send blocked for 500 ms. Backup: /root/agent.backup/t6-vnc-transport-20260923-141324. Real RFB continuous-update client with 4 KiB receive buffer paused reads for 3 seconds: server logged slow-receiver abort and client confirmed closure, draining only 18,472 bytes. Normal 12-second RFB reception tested separately. Windows background/fullscreen reproduction still requires user validation; client-side queues are outside this guard. Only VNC service restarted; capture stayed running.

## Latency measurement (2026-09-23)

Temporary VT10 raw-input black/white screen toggled with ten Space presses via T6 HID HTTP API; restored VT9 btop and removed test process afterward. T6 monotonic timestamps bracketed request initiation and complete encoded AU delivery, avoiding inter-host clock skew. Offline FFmpeg decoded all 647 frames; all ten visual transitions matched. Input-to-encoded-AU median 70.47 ms, range 63.93–81.95 ms; 58.81 fps. Includes curl launch/API, USB HID, PC rendering, HDMI capture and MPP; excludes Windows VNC input/network, VNC output queues, client decode and display scanout. Dequeue-to-AU delivery median 13.68 ms (not full capture latency). This is an active-frame-stream measurement, not glass-to-glass or Windows-client measurement. Raw statistics: latency.json.

## Windows TigerVNC input investigation (2026-09-23)

After owner reported visible video without apparent input, USB UDC was configured and MS-A2 identified both T6 HID interfaces (event2 keyboard, event3 absolute mouse). A Plain-auth RFB test negotiated QEMU extended keys (-258) and extended mouse (-316), sent Shift down/up and two pointer movements. PC evdev observed KEY_LEFTSHIFT 1/0 and ABS_X/Y values 10244/12146 then 15367/15183. Both HID endpoints subsequently reported online. No service restart or code change was needed. This proves the synthetic client path; owner Windows TigerVNC interaction still needs confirmation. The current PC screen is a text console, which normally does not show a mouse pointer.

## Authentication update (2026-09-23)

Owner-requested account changed to kvm; operator removed. Default VeNCrypt security changed from X509Plain to Plain (256), without certificates or encryption. Repository configuration and patch generator updated; only VNC restarted, capture kept running. Live checks passed: correct login, wrong-password rejection, framebuffer update, old controller surviving failed login, and authenticated takeover. Configuration/account/RFB backups are under /root/agent.backup/t6-auth-20260923-133859. Earlier X509Plain evidence below describes the prior configuration.

# T6 live build / deployment result — 2026-09-23

Installed release: dev20260923c on NanoPC-T6 LTS (192.168.123.99).
Source baseline: 9a4bc6a3e87aee4628c5522cde2345487ff7de38 plus the accompanying source fixes.

## Verified

- All four pinned upstream checkouts fetched and checked; final guarded patch applied to seven files of real kvmd v4.120.
- Real pinned MPP and native capture worker compiled and linked for ARM64 in Debian trixie/QEMU on existing MS-A2 VM 301.
- 54/54 Python tests; native-core C test; ASan/UBSan C test (QEMU requires detect_leaks=0, so leak sanitizer was not tested).
- Complete kvmd imports, configuration schema, stage hashes and installer dry-run passed; deployed binary links the release-local MPP on actual T6.
- Dedicated USB gadget created with exactly keyboard and mouse functions; account access limited to video0, mpp_service, renderD128 and owned HID nodes. Original ACL saved under /root/agent.backup/t6-kvm-device-acl-20260923.txt. ACLs are runtime-only.
- Both systemd services started and had zero automatic restarts during smoke tests. VNC listens only on 127.0.0.1:5900. Neither service is enabled at boot.
- Actual RFB socket/TLS test: certificate verified, only X509Plain offered, valid login, wrong password rejected without disconnecting existing controller, authenticated takeover, offline framebuffer update. This custom protocol client is NOT TigerVNC decode acceptance.
- After explicit stop, /run/t6-kvm and its sockets disappeared; services restarted. Existing application containers remained running and reported their prior health states.

## Remaining hardware acceptance

- HDMI QUERY_DV_TIMINGS returns ENOLINK (67); USB UDC remains not attached. Physical connection requested.
- No actual capture, MPP encoding, H.264 decode, 1080p60/1440p60, USB host enumeration/key action, hotplug or long-soak acceptance.
- Optional OCR library is absent and warns once at startup; OCR is outside this project scope.
- Immediately after systemctl start, VNC may bind before kvmd Unix socket is ready; tests wait for readiness/retry.

## Artifacts and operation

- Installed: /opt/t6-kvm/releases/dev20260923c; current symlink points there. Prior releases retained for rollback.
- Target artifacts/logs: /nvme/t6-kvm-artifacts-20260923/.
- Build artifacts/logs: VM 301 /root/t6-kvm-artifacts-20260923/.
- Final archive: stage-003.tar.gz, SHA256 35bf289a6e4509cef631b7f1caae90337e346a58f9c9eb5e48075a6ca52c0266.
- VNC user operator; generated password stored only at target /root/t6-kvm-operator-password (0600). Certificate: /etc/t6-kvm/vnc.crt.
- Certificate SHA256: 85:65:51:6D:E7:85:83:0D:72:A4:43:60:BA:54:FB:50:33:30:DD:79:3F:D7:2C:40:F3:54:51:AB:09:5F:2D:6B.
- Connect using SSH local forward to 127.0.0.1:5900; validate the server certificate for 192.168.123.99. Direct LAN listening was not enabled.
- VM and host were already running; left running, no shutdown scheduled. Task containers, temporary images, source/dependency/build tree and transfer servers cleaned; final archives and evidence retained. Surge temporary rule removed.

## PC input test, 2026-09-23 12:54–13:00

- PC signal: 1920x1080 progressive, measured clock approximately 148.492 MHz. USB UDC configured; owned HID node permissions restored after role switch.
- QUERY_DV_TIMINGS and G_DV_TIMINGS returned identical structures. Fixed native/capture.c to avoid redundant S_DV_TIMINGS when already identical; exact CEA-clock matching rejects measured clock otherwise.
- Cross-compiled strict-warning ARM64 worker against the same pinned MPP in VM 301. Trial binary retained at target /nvme/t6-kvm-artifacts-20260923/hwtest/bin/t6-capture; installed release was not overwritten.
- Actual capture reached REQBUFS but failed: CMA reserved alloc 1519 pages returned -16/EBUSY; 6,221,824-byte DMA allocation failed. About 7 GB MemAvailable and 185 MB CmaFree do not guarantee a contiguous/migratable allocation. Kernel CONFIG_COMPACTION is disabled; compact_memory interface absent. No kernel, boot configuration, cache flush or reboot performed.
- No video AU or encoding success claimed. Evidence: target hwtest/native.log, wire.bin, cma-failure.log; build artifacts on VM 301 under /root/t6-kvm-artifacts-20260923/hwtest/.
- USB keyboard neutral/all-release report: 8 bytes accepted, UDC configured. Actual typed characters/mouse motion not visually verified.
- Both services restored active, zero restarts. Temporary build tree and transfer server cleaned; existing build VM left running.

## Authorized reboot and actual encode, 2026-09-23 12:58–13:01

- User authorized reboot; new boot ID 537e3977-cdc1-4365-92b4-8487b7d47ab6. CMA free immediately after boot: 253764 kB.
- Timing-fixed worker successfully allocated capture buffers and invoked pinned MPP hardware encoder. Observed HDMI input 1920x1080 BGR24, 59.995152 Hz.
- 12-second trial generated 24 valid AU frames, seq 1..24, PTS 40359877..51897156 us: approximately 1.99 encoded fps. 60fps target NOT met.
- VM 301 FFmpeg decoded all 24 frames without error; ffprobe identified H264 1920x1080. Target evidence hwtest/wire-reboot.bin, reboot.h264, reboot-frames.json, native-reboot.log; decoder evidence VM 301 hwtest/reboot.h264 and decode-reboot.log (empty).
- Installed timing-fixed release dev20260923d, preserving previous releases; restored runtime device ACL and two-HID gadget after reboot. USB configured; TLS/auth/takeover protocol smoke passed. Both services active, zero restarts; existing containers running, all reported healthchecks healthy.
- Actual TigerVNC display, actual keyboard/mouse behavior and performance target remain unaccepted. Temporary evidence HTTP server stopped and staging copy removed.

- Service-account follow-up: MPP required /dev/dma_heap/system-uncached. Original ACL saved at /root/agent.backup/t6-kvm-dma-heap-acl-20260923.txt; granted only t6-kvm rw. Retest showed MPP initialization succeeded under the service account and protocol smoke passed (hwtest/rfb-dma-fixed.log).

## Usable 1080p release — 2026-09-23 13:30

Current deployment: dev20260923g, LAN VNC 192.168.123.99:5900, X509Plain/operator.

- Performance root cause: repeated CPU access to uncached capture buffers and scalar BGR conversion. Cached staging plus NEON conversion improved measured capture from 1.99 to 58.90 fps. A 1000-case randomized BT.601/709, padded-stride comparison was byte-identical to the scalar implementation.
- Direct MPP trial: 700 frames, all decoded by FFmpeg at 1920x1080, no decode errors.
- Real VNC TLS data path: 1978 H264 frames in approximately 35 seconds, 58.24 received fps; all independently decoded without error.
- Real Debian TigerVNC 1.15.0 connected over LAN using certificate-verified X509Plain, negotiated H264, rendered Proxmox console at 1920x1080, on-screen statistics showed 59 updates/s. Screenshot/log retained on VM 301 under /root/t6-kvm-artifacts-20260923/final/.
- Fixed pinned kvmd RFB keysym map initialization from empty dictionary to None so lazy-loading occurs. PC-side evdev confirmed T press/release, Backspace press/release, absolute mouse X/Y events. Captured HDMI image displayed test character; Backspace removed it. No login was submitted.
- Final authentication regression passed: invalid password leaves controller connected, successful authentication takes over. Python regression 54/54 passed.
- Enabled t6-kvmd and t6-kvmd-vnc. Added t6-kvm-hardware.service plus explicit dependency drop-in to restore approved device ACL and owned gadget on boot. Explicit hardware review remains release-bound. Device-role changes/foreign gadgets fail closed. Boot service start tested, but another full reboot was not performed.
- Streamer now runs continuously (forever=true), retaining capture allocation across VNC disconnects to reduce CMA reallocation exposure. Observed 59.19 encoded fps, zero worker restarts and approximately 90 MB kvmd service memory during the final observation interval. This is a short soak, not hours-long acceptance.
- Reboot-related CMA allocation failure remains an operational risk with this kernel (COMPACTION disabled); no kernel or boot memory configuration was changed.
- 1440p, physical HDMI hotplug and long-duration stress remain unvalidated. No 4K scaler implemented.
