#!/usr/bin/env python3
"""
WiFi Speaker — Windows Client
- Streams ALL system audio via WASAPI loopback to RPi
- Sets laptop volume to 0 while streaming, restores on exit
- Volume keys control RPi independently

Usage:
    py -3.11 wifi_speaker.py
    py -3.11 wifi_speaker.py --host 192.168.1.50
    py -3.11 wifi_speaker.py --list

Install:
    pip install pyaudiowpatch pycaw comtypes
"""

import sys, socket, struct, argparse, threading, time, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [WIN] %(message)s")
log = logging.getLogger("wifi-speaker-win")

RATE      = 48000
CHANNELS  = 2
CHUNK     = 4096
RPC_PORT  = 8888
RECONNECT = 3
VOL_MAGIC = 0xFFFFFFFF

try:
    import pyaudiowpatch as pyaudio
    WASAPI = True
except ImportError:
    try:
        import pyaudio
        WASAPI = False
    except ImportError:
        print("ERROR: pip install pyaudiowpatch")
        sys.exit(1)

try:
    import comtypes
    from comtypes import CLSCTX_ALL, GUID
    from pycaw.pycaw import IMMDeviceEnumerator, IAudioEndpointVolume
    from ctypes import POINTER, cast
    PYCAW = True
except Exception:
    PYCAW = False


# ── Windows volume control ────────────────────────────────────────────────────

def _build_endpoint():
    e = comtypes.CoCreateInstance(GUID('{BCDE0395-E52F-467C-8E3D-C4579291692E}'), IMMDeviceEnumerator, CLSCTX_ALL)
    d = e.GetDefaultAudioEndpoint(0, 1)
    v = d.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(v, POINTER(IAudioEndpointVolume))

_ep = None
def get_ep():
    global _ep
    if _ep is None:
        _ep = _build_endpoint()
    return _ep

def win_get_volume() -> float:
    try:
        return float(get_ep().GetMasterVolumeLevelScalar())
    except Exception:
        return 1.0

def win_set_volume(vol: float):
    try:
        get_ep().SetMasterVolumeLevelScalar(max(0.0, min(1.0, vol)), comtypes.GUID())
    except Exception as e:
        log.warning(f"SetVolume failed: {e}")


# ── Volume monitor ────────────────────────────────────────────────────────────
# Strategy:
#   - We zero Windows volume so laptop is silent
#   - We track RPi volume separately in _rpi_vol
#   - When user presses volume key, Windows briefly jumps from 0
#   - We detect that jump, update _rpi_vol by the same step, re-zero Windows
#   - We use a "settling" flag to ignore the change we ourselves make

class VolumeMonitor:
    def __init__(self, on_change):
        self._on_change = on_change
        self._rpi_vol   = 1.0
        self._settling  = False   # True right after WE set Windows volume
        self._lock      = threading.Lock()
        self._running   = False

    def start(self, initial_rpi_vol: float):
        if not PYCAW:
            return
        self._rpi_vol = initial_rpi_vol
        self._running = True
        threading.Thread(target=self._poll, daemon=True).start()
        log.info("Volume monitor active — volume keys control RPi output.")

    def _poll(self):
        # After startup, ignore volume changes for 1 second
        # to let Windows volume settle at 0
        time.sleep(1.0)
        prev_win = win_get_volume()   # should be ~0 by now

        while self._running:
            time.sleep(0.12)
            try:
                with self._lock:
                    settling = self._settling
                if settling:
                    # We just set Windows volume ourselves — skip this reading
                    with self._lock:
                        self._settling = False
                    prev_win = win_get_volume()
                    continue

                cur_win = win_get_volume()
                delta   = cur_win - prev_win

                if abs(delta) > 0.01:   # user pressed a volume key
                    with self._lock:
                        new_rpi = max(0.0, min(1.0, self._rpi_vol + delta))
                        self._rpi_vol  = new_rpi
                        self._settling = True   # tell next poll to ignore our re-zero

                    log.info(f"Volume → {int(new_rpi * 100)}%")
                    self._on_change(new_rpi)

                    # Re-zero Windows so laptop stays silent
                    win_set_volume(0.0)
                    prev_win = 0.0
                else:
                    prev_win = cur_win

            except Exception:
                pass

    def get_rpi_vol(self) -> float:
        with self._lock:
            return self._rpi_vol

    def stop(self):
        self._running = False


def make_vol_packet(vol: float) -> bytes:
    return struct.pack("!If", VOL_MAGIC, float(vol))


# ── Audio device helpers ──────────────────────────────────────────────────────

def list_devices(pa):
    print("\n── Audio devices ──────────────────────────────────────")
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d["maxInputChannels"] < 1:
            continue
        tag = " [LOOPBACK]" if d.get("isLoopbackDevice") else ""
        print(f"  [{i:2d}] {d['name']}{tag}")
        print(f"        ch={d['maxInputChannels']}  rate={int(d['defaultSampleRate'])}")
    print()

def find_loopback(pa):
    if not WASAPI:
        return None
    try:
        info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        name = pa.get_device_info_by_index(info["defaultOutputDevice"])["name"]
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            if d.get("isLoopbackDevice") and d["maxInputChannels"] > 0 and name in d["name"]:
                log.info(f"Auto-selected WASAPI loopback: [{i}] {d['name']}")
                return i
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            if d.get("isLoopbackDevice") and d["maxInputChannels"] > 0:
                log.info(f"Using loopback: [{i}] {d['name']}")
                return i
    except Exception as e:
        log.warning(f"WASAPI failed: {e}")
    return None

def open_stream(pa, device_index):
    fmt = pyaudio.paInt16
    if device_index is not None:
        return pa.open(format=fmt, channels=CHANNELS, rate=RATE,
                       input=True, input_device_index=device_index,
                       frames_per_buffer=CHUNK)
    lb = find_loopback(pa)
    if lb is not None:
        try:
            return pa.open(format=fmt, channels=CHANNELS, rate=RATE,
                           input=True, input_device_index=lb,
                           frames_per_buffer=CHUNK)
        except Exception as e:
            log.warning(f"Loopback open failed: {e}")
    log.warning("Falling back to microphone.")
    return pa.open(format=fmt, channels=CHANNELS, rate=RATE,
                   input=True, frames_per_buffer=CHUNK)


# ── Network scan ──────────────────────────────────────────────────────────────

def discover_rpi(port, timeout=4.0):
    log.info("Scanning network for RPi...")
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        return None
    subnet = ".".join(local_ip.split(".")[:3])
    found, lock = [], threading.Lock()
    def probe(ip):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.35)
                if s.connect_ex((ip, port)) == 0:
                    with lock: found.append(ip)
        except Exception:
            pass
    threads = [threading.Thread(target=probe, args=(f"{subnet}.{i}",), daemon=True)
               for i in range(1, 255)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=timeout)
    if found:
        log.info(f"Found RPi at: {found[0]}")
        return found[0]
    log.error("RPi not found — use --host <IP>")
    return None


# ── Main streaming loop ───────────────────────────────────────────────────────

def stream_audio(host, port, device_index):
    pa = pyaudio.PyAudio()
    try:
        stream = open_stream(pa, device_index)
    except Exception as e:
        log.error(f"Audio device error: {e}")
        pa.terminate()
        sys.exit(1)

    # Step 1: read Windows volume BEFORE we touch it
    original_vol = win_get_volume()
    log.info(f"Windows volume: {int(original_vol * 100)}%  (will be restored on exit)")

    pending_vol = [None]
    vol_lock    = threading.Lock()

    def on_vol_change(vol):
        with vol_lock:
            pending_vol[0] = vol

    monitor = VolumeMonitor(on_change=on_vol_change)

    # Step 2: start monitor with original_vol as initial RPi volume
    monitor.start(initial_rpi_vol=original_vol)

    # Step 3: silence laptop
    win_set_volume(0.0)
    log.info("Laptop silenced — audio playing from RPi only.")
    log.info("Press volume keys to adjust RPi volume.")

    try:
        while True:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(5)
                    sock.connect((host, port))
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    sock.settimeout(None)
                    log.info(f"Connected to RPi at {host}:{port}")

                    # Send RPi its initial volume
                    rpi_vol = monitor.get_rpi_vol()
                    sock.sendall(make_vol_packet(rpi_vol))
                    log.info(f"RPi volume: {int(rpi_vol * 100)}%")

                    while True:
                        try:
                            with vol_lock:
                                vp = pending_vol[0]
                                pending_vol[0] = None
                            if vp is not None:
                                sock.sendall(make_vol_packet(vp))
                            data = stream.read(CHUNK, exception_on_overflow=False)
                            sock.sendall(struct.pack("!I", len(data)) + data)
                        except (BrokenPipeError, OSError):
                            log.warning("Connection lost — reconnecting...")
                            break
            except (ConnectionRefusedError, OSError, TimeoutError):
                log.warning(f"Cannot reach {host}:{port} — retrying in {RECONNECT}s")
                time.sleep(RECONNECT)

    except KeyboardInterrupt:
        log.info("Stopped.")
    finally:
        monitor.stop()
        # Restore Windows volume
        win_set_volume(original_vol)
        log.info(f"Laptop volume restored to {int(original_vol * 100)}%.")
        stream.stop_stream()
        stream.close()
        pa.terminate()


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="WiFi Speaker — Windows client")
    p.add_argument("--host", "-H", default=None)
    p.add_argument("--port", "-p", type=int, default=RPC_PORT)
    p.add_argument("--device", "-d", type=int, default=None)
    p.add_argument("--list", "-l", action="store_true")
    return p.parse_args()

if __name__ == "__main__":
    args = parse_args()
    pa   = pyaudio.PyAudio()
    if args.list:
        list_devices(pa)
        pa.terminate()
        sys.exit(0)
    pa.terminate()
    host = args.host or discover_rpi(args.port)
    if not host:
        sys.exit(1)
    stream_audio(host=host, port=args.port, device_index=args.device)
