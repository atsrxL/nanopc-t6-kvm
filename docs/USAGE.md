# T6 KVM — deployed 1080p usage

Current device: 192.168.123.99, release dev20260923g.

Use TigerVNC with H264 support (Debian TigerVNC 1.15.0 tested). Connect to 192.168.123.99::5900; username kvm, with the password chosen by the device owner. The former operator account has been removed.

Default security is VeNCrypt Plain: select SecurityTypes=Plain in TigerVNC. No certificate import or X509CA setting is required. Authentication is required, but the connection is not encrypted. To opt into X509Plain, configure the certificate, private key, and TLS ciphers in main.yaml and configure client certificate trust.

The services now start automatically. t6-kvm-hardware.service restores the explicitly reviewed device ACL and creates only this project's two HID functions if the gadget configuration is empty. Main-service drop-in: /etc/systemd/system/t6-kvmd.service.d/hardware.conf. Foreign gadgets or USB Host mode must be resolved explicitly; the helper does not change USB role.

Input: HDMI IN 1920x1080 at 60Hz. Connect T6 USB-C Device port to controlled PC USB Host port. Current real tests measured approximately 58–59 fps, actual TigerVNC display and PC keyboard/mouse input events.

Streamer stays running between clients to retain capture buffers. If CMA allocation fails after heavy workloads or signal changes, inspect journalctl -k and /proc/meminfo; a user-approved reboot recovered it in testing. Do not reboot or stop unrelated applications automatically.

Stop: sudo systemctl stop t6-kvmd-vnc t6-kvmd. Start: sudo systemctl start t6-kvmd t6-kvmd-vnc. To redo hardware preparation after an explicit USB role change, stop both main services, restart t6-kvm-hardware, then start the main services.

Rollback: stop main services, use tools/admin.py rollback --release <retained-release> --apply, then update the release-bound hardware review after checking configuration compatibility. Boot helper/drop-in and LAN/forever configuration are separate deployed settings; older releases without prepare_hardware.py require removing their dependency before starting.

Uninstall additionally requires disabling/removing the hardware helper unit and dependency drop-in; the original admin.py handles only its two tracked main units. Preserve configuration and backups.

VNC transport buffering is bounded (SO_SNDBUF request 64 KiB, asyncio 64/16 KiB, TCP_NOTSENT_LOWAT 16 KiB where supported). Slow receivers wait for backpressure without a forced 500 ms disconnect. The application frame queue remains bounded and recovers with a keyframe after overflow. Windows background/fullscreen latency is still under investigation.

ContinuousUpdates (-313) is enabled again at the owner's request for comparison of smoothness. Clients that advertise it may enable continuous push. Bounded transport buffers remain; no 500 ms disconnect policy is active. The prior request-paced trial passed pause/resume tests but felt less smooth to the owner. Background/fullscreen behavior with continuous push and bounded buffers still needs evaluation.

Current mode: client-requested updates (ContinuousUpdates disabled again by owner request). Live device additionally supports classic password-only VNCAuth for Jump Desktop compatibility, using /etc/t6-kvm/vncpasswd (root:t6-kvm 0640). VeNCrypt/Plain account login remains available. Jump previously disconnected at VeNCrypt subtype selection, before video negotiation. Classic auth has been tested; actual Jump video compatibility is pending. H264 remains mandatory; clients without encoding 50 cannot yet receive live video.

Tight/JPEG live fallback is now deployed. Clients advertising H264 (50) select the native hardware stream first; JPEG-only clients select software H264 decoding plus JPEG quality 70, capped at 15 fps. Measured JPEG throughput: 13.24 fps at 1920x1080. PyAV/Pillow are required. Jump Desktop completed authentication and entered live streaming in real logs. Earlier H264-only limitations above describe the previous implementation. ContinuousUpdates remains disabled (request mode).

Control panel: http://192.168.123.99:5899, HTTP Basic authentication using the current KVM account. t6-kvm-panel.service is enabled. Status includes HDMI resolution, observed encoder fps, client IP/port, send queue, TCP RTT and last selected encoding; full end-to-end latency is not measured. Settings persist H264 bitrate (100–20000 kbps), ContinuousUpdates negotiation and username/password. Classic VNC compatibility limits new passwords to 8 visible ASCII characters; blank preserves the password. JPEG stays quality 70 / 15 fps cap. Changes restart VNC, or both main services for bitrate. panel.json controls mode; snapshots are under /root/agent.backup/t6-panel-* with two retained. Panel unit runs as root to edit configuration and restart only the dedicated services; installer/uninstaller integration remains manual, as with hardware helper.

4K software preparation: deployed worker and configuration validator now accept up to 3840x2160 native SDR input. H264 Level 5.2 selected above Level 5.1 macroblock-rate budget. Live limits on this T6 raised to 3840x2160; default sample configuration remains conservative 1080p. No scaler or zero-copy path added. Actual HDMI input remains 1080p because source DRM modes omit 4K despite EDID advertising it. MPP synthetic 4K120-frame encode/decode passed; this does not certify HDMI 4K60 throughput.

4K60 update: eligible tightly packed NV12 now exports V4L2 DMA-BUFs and imports them into MPP. Each buffer remains dequeued until its encoded frame completes; nonmatching layouts retain CPU fallback. Real HDMI 3840x2160 ~59.997Hz produced 1200 frames in 20 seconds (~60.02fps), all independently decoded. This validates server capture/encoding, not Windows display throughput or long-duration stability. Source temporary modeset still restores 1080p afterward.

Additional real HDMI mode tests: 2560x1440 at 59.95fps and 2560x1600 at 59.97fps, each 10s with no encoded sequence gaps. BGR24 DMA-BUF import lets MPP perform RGB conversion, removing CPU conversion. Decoded geometry verified. RGB colorimetric accuracy is not calibrated. The server follows actual HDMI timing and sends DesktopSize on changes; the viewer may scale locally but does not select the source GPU mode. EDID was not changed to add these modes; tests used temporary PC DRM custom CVT-RB timings, restored afterward.

EDID: config/edid/t6-1440-1600-4k.bin retains 1080p preferred and existing CTA 4K VICs, adds CVT-RB DTDs 2560x1440@59.9506 and 2560x1600@59.9716. Deployed as /etc/t6-kvm/edid.bin; hardware boot helper applies it before capture. apply_edid.py requires capture stopped, validates both checksums and verifies readback. Original EDID backup on T6: /root/agent.backup/t6-edid-20260923-161502/original.bin. Source PC read back both new DTDs but its DRM modes list still filters them; this does not guarantee appearance in every OS display selector. Temporary explicit DRM modesets have already validated both modes end-to-end through encoding.
