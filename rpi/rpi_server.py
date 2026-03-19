#!/usr/bin/env python3
"""
WiFi Speaker — Raspberry Pi Server (Bookworm / PipeWire)
Receives PCM audio + volume control packets from Windows/Android clients.
Applies volume scaling on incoming PCM before playing through the speaker.

Run:
    python3 rpi_server.py
"""

import asyncio
import socket
import struct
import array
import threading
import logging
import signal
import sys
import subprocess

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SERVER] %(message)s"
)
log = logging.getLogger("rpi-server")

# ── Audio config (must match all clients) ─────────────────────────────────────
RATE      = 48000
CHANNELS  = 2
CHUNK     = 4096

# ── Network ───────────────────────────────────────────────────────────────────
HOST       = "0.0.0.0"
AUDIO_PORT = 8888
HTTP_PORT  = 8080

# ── Buffer ────────────────────────────────────────────────────────────────────
QUEUE_MAX  = 80      # raise if crackling, lower for less latency

# ── Packet protocol (must match Windows client) ───────────────────────────────
# Audio packet  :  [uint32 length] + [PCM bytes]
# Volume packet :  [0xFFFFFFFF]    + [float32 volume 0.0–1.0]
VOL_MAGIC = 0xFFFFFFFF
# ──────────────────────────────────────────────────────────────────────────────


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def scale_pcm(data: bytes, volume: float) -> bytes:
    """Scale int16 PCM samples by volume. Called only when volume != 1.0."""
    samples = array.array("h", data)
    scaled  = array.array("h", (
        max(-32768, min(32767, int(s * volume)))
        for s in samples
    ))
    return bytes(scaled)


class AudioMixer:
    """
    Receives PCM chunks from all clients, applies per-client volume,
    and feeds them to aplay via stdin pipe.
    """

    def __init__(self):
        self._queue   = asyncio.Queue(maxsize=QUEUE_MAX)
        self._running = False
        self._proc    = None
        # Per-client volume: client_id -> float (0.0–1.0)
        self._volumes: dict[str, float] = {}
        self._vlock   = threading.Lock()

    def set_volume(self, client_id: str, volume: float):
        with self._vlock:
            self._volumes[client_id] = max(0.0, min(1.0, volume))
        log.info(f"Volume [{client_id}] → {int(volume * 100)}%")

    def get_volume(self, client_id: str) -> float:
        with self._vlock:
            return self._volumes.get(client_id, 1.0)

    def remove_client(self, client_id: str):
        with self._vlock:
            self._volumes.pop(client_id, None)

    def _open_aplay(self):
        cmd = [
            "aplay",
            "-t", "raw",
            "-f", "S16_LE",
            f"-r{RATE}",
            f"-c{CHANNELS}",
            "--buffer-size=8192",
            "-",
        ]
        log.info(f"Starting aplay: {' '.join(cmd)}")
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    async def start(self):
        self._running = True
        loop = asyncio.get_event_loop()

        def _player():
            self._proc = self._open_aplay()
            log.info("Audio player ready.")
            while self._running:
                future = asyncio.run_coroutine_threadsafe(self._dequeue(), loop)
                try:
                    item = future.result(timeout=1.0)
                except Exception:
                    item = None
                if item and self._proc and self._proc.stdin:
                    try:
                        self._proc.stdin.write(item)
                        self._proc.stdin.flush()
                    except BrokenPipeError:
                        log.warning("aplay pipe broke — restarting")
                        self._proc = self._open_aplay()

        threading.Thread(target=_player, daemon=True).start()

    async def _dequeue(self):
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            return None

    async def push(self, client_id: str, data: bytes):
        """Apply volume then queue for playback."""
        vol = self.get_volume(client_id)
        if abs(vol - 1.0) > 0.005:
            data = scale_pcm(data, vol)
        # Drop oldest chunk if buffer full (prevents growing lag)
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            await self._queue.put(data)

    def stop(self):
        self._running = False
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass


class ClientHandler:
    """
    Handles one TCP connection.
    Reads framed packets and dispatches:
      - volume packets → mixer.set_volume()
      - audio packets  → mixer.push()
    """

    def __init__(self, reader, writer, mixer: AudioMixer, client_id: str):
        self.reader    = reader
        self.writer    = writer
        self.mixer     = mixer
        self.id        = client_id
        addr           = writer.get_extra_info("peername")
        self.addr      = f"{addr[0]}:{addr[1]}" if addr else "unknown"

    async def run(self):
        log.info(f"[+] {self.addr}  connected  (id={self.id})")
        # Default volume 100% until client sends a volume packet
        self.mixer.set_volume(self.id, 1.0)
        try:
            while True:
                # Every packet starts with a 4-byte header
                header = await self.reader.readexactly(4)
                marker = struct.unpack("!I", header)[0]

                if marker == VOL_MAGIC:
                    # Volume control packet — next 4 bytes are a float32
                    vol_bytes = await self.reader.readexactly(4)
                    volume    = struct.unpack("!f", vol_bytes)[0]
                    self.mixer.set_volume(self.id, volume)

                elif marker == 0:
                    # Graceful disconnect signal
                    break

                else:
                    # Regular audio packet — marker is the byte length
                    length = marker
                    if length > 524288:
                        log.warning(f"Oversized packet {length}B from {self.addr} — dropping")
                        break
                    data = await self.reader.readexactly(length)
                    await self.mixer.push(self.id, data)

        except asyncio.IncompleteReadError:
            pass
        except ConnectionResetError:
            pass
        finally:
            self.mixer.remove_client(self.id)
            self.writer.close()
            log.info(f"[-] {self.addr}  disconnected")


class AudioServer:
    def __init__(self, mixer: AudioMixer):
        self.mixer    = mixer
        self._counter = 0

    async def handle(self, reader, writer):
        self._counter += 1
        handler = ClientHandler(reader, writer, self.mixer, f"client-{self._counter}")
        await handler.run()

    async def start(self):
        server = await asyncio.start_server(self.handle, HOST, AUDIO_PORT)
        log.info(f"Audio server  →  {HOST}:{AUDIO_PORT}")
        async with server:
            await server.serve_forever()


# ── Minimal HTTP status page ──────────────────────────────────────────────────

STATUS_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WiFi Speaker</title>
<style>
  body{{font-family:system-ui,sans-serif;background:#0d0d0d;color:#e0e0e0;
        display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
  .card{{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:16px;
         padding:2rem 2.5rem;max-width:400px;width:100%;text-align:center}}
  h1{{margin:0 0 .3rem;font-size:1.4rem;font-weight:500}}
  .dot{{display:inline-block;width:10px;height:10px;border-radius:50%;
        background:#22c55e;margin-right:6px;animation:pulse 2s infinite}}
  @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
  p{{color:#888;font-size:.85rem;margin:.6rem 0;line-height:1.6}}
  code{{background:#252525;padding:2px 8px;border-radius:6px;font-size:.88rem;color:#a78bfa}}
</style></head>
<body><div class="card">
  <h1><span class="dot"></span>WiFi Speaker</h1>
  <p>Running on your Raspberry Pi</p>
  <p>Windows:<br><code>py -3.11 wifi_speaker.py</code></p>
  <p>Volume: move your Windows slider — syncs automatically</p>
  <p style="margin-top:1.5rem;font-size:.75rem;color:#555">
    {ip}:{port} &nbsp;·&nbsp; {rate} Hz &nbsp;·&nbsp; Stereo
  </p>
</div></body></html>
"""


async def run_http_server(ip: str):
    async def handle(reader, writer):
        try:
            await reader.read(1024)
            body = STATUS_HTML.format(ip=ip, port=AUDIO_PORT, rate=RATE).encode()
            resp = (
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                b"Connection: close\r\nContent-Length: "
                + str(len(body)).encode() + b"\r\n\r\n" + body
            )
            writer.write(resp)
            await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_server(handle, HOST, HTTP_PORT)
    log.info(f"Status page   →  http://{ip}:{HTTP_PORT}")
    async with server:
        await server.serve_forever()


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    ip = get_local_ip()
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║        WiFi Speaker — RPi Server             ║")
    print("╠══════════════════════════════════════════════╣")
    print(f"║  IP Address  :  {ip:<28} ║")
    print(f"║  Audio port  :  {AUDIO_PORT:<28} ║")
    print(f"║  Status page :  http://{ip}:{HTTP_PORT:<5}          ║")
    print("╠══════════════════════════════════════════════╣")
    print("║  Volume sync :  move Windows volume slider   ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    mixer = AudioMixer()
    await mixer.start()

    def _shutdown(sig, _):
        log.info("Shutting down...")
        mixer.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    await asyncio.gather(
        AudioServer(mixer).start(),
        run_http_server(ip),
    )


if __name__ == "__main__":
    asyncio.run(main())
