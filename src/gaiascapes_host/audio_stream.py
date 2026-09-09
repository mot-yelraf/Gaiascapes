"""Bounded, on-demand relay of the Gaiascapes renderer's stereo audio.

SuperCollider sends short PCM blocks over loopback OSC while browsers listen.
The relay fans them out over HTTP without capturing other apps, recording to
disk, or allowing a slow listener to stall the renderer or other listeners.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import secrets
import socket
import struct

from .osc import encode_message

FRAMES = 512
CHANNELS = 2
QUEUE_BLOCKS = 48
MAX_LISTENERS = 16
AUDIO_TIMEOUT = 5.0


def decode_audio_packet(packet: bytes, token: str) -> bytes:
    """Validate a renderer block and convert OSC floats to framed little-endian PCM."""
    offset = 0

    def string():
        nonlocal offset
        end = packet.index(b"\0", offset)
        value = packet[offset:end].decode("ascii")
        offset = (end + 4) & ~3
        return value

    if string() != "/gaia/audio":
        raise ValueError("Unexpected audio address")
    if string() != ",sii" + "f" * (FRAMES * CHANNELS):
        raise ValueError("Unexpected audio format")
    if string() != token:
        raise ValueError("Stale audio session")
    if len(packet) != offset + 8 + FRAMES * CHANNELS * 4:
        raise ValueError("Invalid audio block length")
    sequence, sample_rate = struct.unpack_from(">ii", packet, offset)
    if sequence < 0 or not 8000 <= sample_rate <= 192000:
        raise ValueError("Invalid audio clock")
    samples = struct.unpack_from(f">{FRAMES * CHANNELS}f", packet, offset + 8)
    if not all(math.isfinite(value) for value in samples):
        raise ValueError("Invalid audio samples")
    return struct.pack("<4sII", b"GAIA", sequence, sample_rate) + struct.pack(
        f"<{len(samples)}f", *samples
    )


class RendererAudioRelay(asyncio.DatagramProtocol):
    """Share one leased renderer tap across a bounded number of HTTP listeners."""

    def __init__(self, config):
        self.config = config
        self.listeners = set()
        self.transport = None
        self.heartbeat = None
        self.token = ""
        self.lock = asyncio.Lock()
        self.last_sequence = -1
        self.last_error = ""

    def status(self) -> dict:
        """Report availability without starting audio capture."""
        local = self.config.osc_host in {"127.0.0.1", "localhost", "::1"}
        return {
            "enabled": self.config.osc_enabled,
            "supported": local,
            "listeners": len(self.listeners),
            "error": self.last_error,
        }

    def datagram_received(self, data, addr):
        """Accept authenticated session blocks from the local renderer only."""
        if addr[0] != "127.0.0.1":
            return
        try:
            block = decode_audio_packet(data, self.token)
        except (ValueError, UnicodeError, struct.error):
            return
        sequence = struct.unpack_from("<I", block, 4)[0]
        if sequence <= self.last_sequence:
            return
        self.last_sequence = sequence
        self.last_error = ""
        for queue in self.listeners:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(block)

    def _command(self, action):
        if self.transport:
            port = self.transport.get_extra_info("sockname")[1]
            self.transport.sendto(
                encode_message(f"/gaia/audio/{action}", (self.token, port)),
                ("127.0.0.1", self.config.osc_port),
            )

    async def _renew(self):
        while True:
            self._command("start")
            await asyncio.sleep(2)

    async def subscribe(self):
        """Start a tap if needed and await audio before accepting a listener."""
        if not self.config.osc_enabled:
            raise RuntimeError("SuperCollider audio is disabled. Animal recordings remain available.")
        if not self.status()["supported"]:
            raise RuntimeError("LAN listening requires SuperCollider on the Gaiascapes host.")
        queue = asyncio.Queue(maxsize=QUEUE_BLOCKS)
        async with self.lock:
            if len(self.listeners) >= MAX_LISTENERS:
                raise RuntimeError("All 16 audio listening slots are in use. Try again later.")
            if not self.transport:
                self.token = secrets.token_hex(16)
                self.last_sequence = -1
                loop = asyncio.get_running_loop()
                self.transport, _ = await loop.create_datagram_endpoint(
                    lambda: self, local_addr=("127.0.0.1", 0)
                )
                self.transport.get_extra_info("socket").setsockopt(
                    socket.SOL_SOCKET, socket.SO_RCVBUF, 256 * 1024
                )
                self.heartbeat = asyncio.create_task(self._renew())
            self.listeners.add(queue)
        try:
            first = await asyncio.wait_for(queue.get(), AUDIO_TIMEOUT)
            if first is None:
                raise RuntimeError("Host audio is shutting down.")
        except BaseException as exc:
            await self.unsubscribe(queue)
            if isinstance(exc, asyncio.TimeoutError):
                self.last_error = "No host audio received. Start or restart SuperCollider with the updated Gaiascapes receiver."
                raise RuntimeError(self.last_error) from exc
            raise
        return queue, first

    async def unsubscribe(self, queue):
        """Release a listener and stop capture when nobody remains."""
        async with self.lock:
            self.listeners.discard(queue)
            if not self.listeners:
                await self._stop()

    async def _stop(self):
        if self.heartbeat:
            self.heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.heartbeat
            self.heartbeat = None
        self._command("stop")
        if self.transport:
            self.transport.close()
            self.transport = None

    async def close(self):
        """Stop capture and wake listeners during application shutdown."""
        async with self.lock:
            for queue in self.listeners:
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(None)
            self.listeners.clear()
            await self._stop()
