# Windows TigerVNC high-resolution H264 investigation

Checked 2026-09-23 against official v1.16.2 and current master source.

Source: https://github.com/TigerVNC/tigervnc/blob/v1.16.2/common/rfb/H264WinDecoderContext.cxx
Upstream proposed fix: https://github.com/TigerVNC/tigervnc/pull/2153 (open, not merged when checked).

Constructor allocates decoded_buffer from GetOutputStreamInfo before the actual stream arrives (lines105–126). MF_E_TRANSFORM_STREAM_CHANGE handler (203 onward) updates the media type/converter but does not resize decoded_buffer. ProcessOutput loop lacks handling for unexpected failures. PR2153 reports a 4,147,200-byte placeholder buffer on Windows11 versus5,529,600 bytes minimum for2560x1440 NV12. It reports E_FAIL0x80004005,1080p works,1440p black, and working1440p60/4K30 after resizing decoded buffer and handling failures. These Windows runtime results belong to the upstream author, not our own tests.

Our evidence: Windows user reports1080p renders while1440p/4K black. Current live2560x1440 AU begins SPS/PPS, baseline level5.1; independent RFB/PyAV decoding previously passed. Mac binary lacks H264 and instead exposed the separate Tight2048-width issue, now fixed. Evidence strongly matches upstream Windows bug; exact user executable version and runtime HRESULT remain unverified.

Remedy for native high-resolution H264: patched Windows viewer implementing buffer reallocation on stream change, releasing/replacing converter sample buffers, and bounded/error-handled ProcessOutput. JPEG tiles are a fallback; selecting JPEG quality alone does not disable H264 advertisement with current server preference logic. No client binary installed or server mode changed during this source investigation.
