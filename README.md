<div align="center">

# 📡 WiFi Speaker

### Turn your Raspberry Pi into a wireless speaker over WiFi

Stream all system audio from your **Windows laptop** or **Android phone** to any speaker connected to your Raspberry Pi — no Bluetooth pairing, no range limits, no audio compression.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![RPi](https://img.shields.io/badge/Raspberry_Pi-Bookworm-C51A4A?style=flat-square&logo=raspberry-pi&logoColor=white)](https://raspberrypi.org)
[![Windows](https://img.shields.io/badge/Windows-10%2F11-0078D6?style=flat-square&logo=windows&logoColor=white)](https://microsoft.com)
[![Android](https://img.shields.io/badge/Android-APK-3DDC84?style=flat-square&logo=android&logoColor=white)](https://android.com)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Working-brightgreen?style=flat-square)]()
[![Audio](https://img.shields.io/badge/Audio-48kHz_Stereo-blueviolet?style=flat-square)]()

</div>

---

## 🎯 What is WiFi Speaker?

WiFi Speaker turns your Raspberry Pi into a network audio receiver. Any device on your local WiFi can stream audio to it — like a Bluetooth speaker, but with:

| Feature | Bluetooth Speaker | WiFi Speaker |
|---------|------------------|--------------|
| Range | ~10 meters | Entire home |
| Pairing | Required every time | Auto-discovers |
| Audio quality | Compressed | Lossless PCM |
| Multiple senders | ❌ | ✅ |
| Volume sync | Manual | Automatic |
| Setup | Simple | One-time |

---

## 🏗️ How it works

```
┌──────────────────────┐
│   Windows Laptop     │  WASAPI loopback
│   All system audio   │──────────────────────┐
│   Volume keys sync   │      TCP :8888        │
└──────────────────────┘                       ▼
                                 ┌─────────────────────┐
                                 │   Raspberry Pi      │──▶ 🔊 Speaker
                                 │   rpi_server.py     │
                                 │   Auto-starts       │
                                 │   on boot           │
                                 └─────────────────────┘
┌──────────────────────┐                  ▲
│   Android Phone      │   TCP :8888      │
│   Mic audio / APK    │──────────────────┘
│   Browser tab audio  │   HTTP :8080
└──────────────────────┘
```

The RPi runs a persistent TCP audio server that accepts raw PCM streams from any connected client and plays them through `aplay`. Multiple devices can connect simultaneously.

---

## 📁 Project Structure

```
wifi-speaker/
├── rpi/
│   └── rpi_server.py              # RPi audio server
├── windows/
│   ├── wifi_speaker.py            # Windows streaming client
│   └── WiFi Speaker.bat           # Double-click launcher
├── android/
│   ├── main.py                    # Android app source (Kivy)
│   ├── buildozer.spec             # APK build config
│   └── wifispeaker-1.0-debug.apk  # Pre-built APK
└── README.md
```

---

## 🚀 Setup Guide

### 🍓 Part 1 — Raspberry Pi Server

**Requirements:** Raspberry Pi OS Bookworm · Speaker on 3.5mm or HDMI

#### Install

```bash
sudo apt update
sudo apt install -y alsa-utils python3-pyaudio portaudio19-dev
```

#### Verify your speaker works

```bash
speaker-test -c2 -t wav
```

If silent, configure audio output:
```bash
sudo raspi-config
# System Options → Audio → choose output (3.5mm or HDMI)
```

#### Run the server

```bash
python3 rpi_server.py
```

The server prints your RPi's IP address — note it down.

```
╔══════════════════════════════════════════════╗
║        WiFi Speaker — RPi Server             ║
╠══════════════════════════════════════════════╣
║  IP Address  :  192.168.1.7                  ║
║  Audio port  :  8888                         ║
║  Status page :  http://192.168.1.7:8080      ║
╚══════════════════════════════════════════════╝
```

#### Auto-start on boot (recommended)

```bash
sudo nano /etc/systemd/system/wifi-speaker.service
```

Paste:

```ini
[Unit]
Description=WiFi Speaker
After=network-online.target sound.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/wifi-speaker/rpi/rpi_server.py
WorkingDirectory=/home/pi/wifi-speaker/rpi
Restart=always
RestartSec=5
User=pi

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable wifi-speaker
sudo systemctl start wifi-speaker
sudo systemctl status wifi-speaker
```

---

### 💻 Part 2 — Windows Client

**Requirements:** Windows 10/11 · Python 3.11+

#### Install dependencies

```powershell
pip install pyaudiowpatch pycaw comtypes
```

#### Run

```powershell
# Auto-discovers RPi on your network
py -3.11 wifi_speaker.py

# Or double-click:
WiFi Speaker.bat

# Or specify IP directly:
py -3.11 wifi_speaker.py --host 192.168.1.7
```

#### What happens automatically

| Action | Result |
|--------|--------|
| Script starts | Scans network, finds RPi |
| Connected | Laptop speaker silenced |
| Audio plays | Streams to RPi speaker |
| Volume key pressed | RPi volume changes instantly |
| Ctrl+C | Laptop volume restored |

#### CLI options

| Flag | Description |
|------|-------------|
| `--host <IP>` | Skip scan, connect directly |
| `--list` | Show all audio devices |
| `--device <N>` | Use specific audio device |

#### How system audio capture works

The Windows client uses **WASAPI loopback** via `pyaudiowpatch` — it captures the audio signal going to your speakers at the OS level before it reaches the hardware. This means everything you hear — Spotify, YouTube, games, notifications — gets streamed to the RPi. No virtual audio cables or extra software needed.

---

### 📱 Part 3 — Android

Android has two modes depending on what you want to stream.

#### Mode A — Mic audio (APK)

The pre-built APK streams your phone's **microphone** to the RPi speaker. Useful for hands-free calls, voice, or playing music out loud near the mic.

**Install:**
1. Download `wifispeaker-1.0-debug.apk` from the [Releases](../../releases) page
2. On your phone: **Settings → Apps → Special app access → Install unknown apps** → allow your file manager
3. Tap the APK → **Install**
4. Open **WiFi Speaker** → enter RPi IP → tap **Connect & Stream**
5. Allow microphone permission

> **Note:** Android restricts system audio capture for third-party apps since Android 10. The APK streams mic audio only. For music streaming, use Mode B below.

#### Mode B — Browser tab audio (no app needed)

Stream any audio playing in Chrome — YouTube, Spotify Web, SoundCloud — directly to the RPi speaker.

1. Open **Chrome** on your Android phone
2. Go to `http://192.168.1.7:8080`
3. Tap **Connect**
4. When prompted, choose **Share tab audio**
5. Switch to another tab and play music — audio goes to RPi

This works on any Android phone with Chrome, no APK needed.

#### Build APK from source

Requirements: Linux / WSL2 / Kali

```bash
# Install build tools
sudo apt install -y default-jdk git zip unzip autoconf libtool \
    pkg-config zlib1g-dev libncurses-dev cmake libffi-dev \
    libssl-dev build-essential ccache python3-dev python3-venv

# Create virtual environment
python3 -m venv ~/buildozer-env
source ~/buildozer-env/bin/activate
pip install buildozer Cython setuptools

# Install Java 17 (required — Java 21 is not compatible with Gradle 8)
wget https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.9%2B9/OpenJDK17U-jdk_x64_linux_hotspot_17.0.9_9.tar.gz
tar -xzf OpenJDK17U-jdk_x64_linux_hotspot_17.0.9_9.tar.gz
export JAVA_HOME=~/jdk-17.0.9+9
export PATH=$JAVA_HOME/bin:$PATH

# Build
cd android/
buildozer android debug

# Copy APK to Windows (WSL)
cp bin/*.apk /mnt/c/Users/<you>/Downloads/
```

---

## 🔊 Audio Streaming Details

### Protocol

All clients communicate with the RPi server using a simple framed TCP protocol:

```
Audio packet  :  [4-byte uint32 length] + [raw PCM bytes]
Volume packet :  [0xFFFFFFFF magic]     + [4-byte float32 volume 0.0–1.0]
```

### Audio format

| Parameter | Value |
|-----------|-------|
| Sample rate | 48000 Hz |
| Channels | 2 (stereo) for Windows · 1 (mono) for Android |
| Bit depth | 16-bit signed integer |
| Encoding | Little-endian PCM |

### Volume control

Windows volume is tracked independently from RPi volume:
- Script reads Windows volume on startup
- Sets Windows volume to 0 (laptop silent)
- Sends original volume to RPi
- Volume key presses are detected as deltas and forwarded to RPi
- On exit, Windows volume is restored

---

## 🔧 Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| No sound on RPi | Wrong audio output | `sudo raspi-config` → Audio |
| Crackling / dropouts | Buffer too small | Increase `QUEUE_MAX` in `rpi_server.py` |
| High latency | Buffer too large | Decrease `QUEUE_MAX` |
| Windows can't find RPi | Different network / firewall | Use `--host <IP>` directly |
| Wrong sample rate | Realtek 48kHz vs 44.1kHz | Set `RATE = 48000` in both files |
| Laptop not silencing | pycaw COM error | Reinstall: `pip install pycaw comtypes` |
| APK install blocked | Unknown sources disabled | Settings → Apps → Install unknown apps |
| APK build fails Java error | Java 21 incompatible | Install Java 17 (see build guide) |

#### Useful RPi commands

```bash
# Check server status
sudo systemctl status wifi-speaker

# Watch live logs
sudo journalctl -u wifi-speaker -f

# Restart server
sudo systemctl restart wifi-speaker

# Test speaker
speaker-test -c2 -t wav

# List audio devices
aplay -l
```

#### Open firewall ports on RPi

```bash
sudo ufw allow 8888/tcp
sudo ufw allow 8080/tcp
```

---

## 📦 Dependencies

### Raspberry Pi
| Package | Purpose |
|---------|---------|
| `alsa-utils` | `aplay` command for audio playback |
| `python3-pyaudio` | Audio I/O library |
| `portaudio19-dev` | PortAudio backend |

### Windows
| Package | Purpose |
|---------|---------|
| `pyaudiowpatch` | WASAPI loopback — captures all system audio |
| `pycaw` | Windows Core Audio API — volume monitoring |
| `comtypes` | Windows COM interface layer |

### Android (build only)
| Package | Purpose |
|---------|---------|
| `kivy` | Cross-platform UI framework |
| `pyjnius` | Android Java bridge for mic access |
| `buildozer` | Compiles Python to APK |

---

## 🗺️ Roadmap

- [ ] Android system audio streaming (requires root or Android 10+ MediaProjection API)
- [ ] iOS support via browser WebAudio
- [ ] Multi-room audio (stream to multiple RPis simultaneously)
- [ ] EQ and audio effects on RPi side
- [ ] Web dashboard for managing connections

---

## 🤝 Contributing

Pull requests are welcome!

1. Fork the repo
2. Create your branch: `git checkout -b feature/my-feature`
3. Commit: `git commit -m "Add my feature"`
4. Push: `git push origin feature/my-feature`
5. Open a Pull Request

---

## 📄 License

MIT License — free to use, modify and distribute.

---

<div align="center">

Made with ❤️ using Python · Raspberry Pi OS Bookworm · Windows WASAPI · Android Kivy

**[⬇️ Download APK](../../releases/latest)** · **[📖 Wiki](../../wiki)** · **[🐛 Report Bug](../../issues)**

</div>
