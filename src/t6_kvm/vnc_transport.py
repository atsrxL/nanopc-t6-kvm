# SPDX-License-Identifier: GPL-3.0-or-later
"""Bound transport buffering without disconnecting slow interactive clients."""
import socket



def configure(writer):
    # Prevent Linux send-buffer autotuning from hiding seconds of stale video.
    sock = writer.get_extra_info("socket")
    if sock is not None:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
        if hasattr(socket, "TCP_NOTSENT_LOWAT"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NOTSENT_LOWAT, 16384)
    writer.transport.set_write_buffer_limits(high=65536, low=16384)


async def drain(writer):
    # Backpressure must not disconnect an otherwise healthy interactive client.
    await writer.drain()


def continuous_updates_enabled():
    import json
    from pathlib import Path
    try:
        return json.loads(Path('/etc/t6-kvm/panel.json').read_text()).get('continuous', False) is True
    except (OSError, ValueError):
        return False
