# WiFi Speaker — Full Setup Guide

Turn your Raspberry Pi (Bookworm) into a WiFi speaker.
Stream all system audio from Windows or mic audio from Android — just like a Bluetooth speaker but over WiFi.

```
┌─────────────────────┐
│  Windows Laptop     │  WASAPI loopback
│  (ALL system audio) │──────────────────────┐
└─────────────────────┘    TCP :8888          │
                                              ▼
                                  ┌───────────────────┐
                                  │  Raspberry Pi     │──▶ 🔊 Speaker
                                  │  (Bookworm)       │
                                  └───────────────────┘
┌─────────────────────┐              ▲
│  Android Phone      │  TCP :8888   │
│  (mic audio / APK)  │──────────────┘
└─────────────────────┘
```

---

## Raspberry Pi Setup

### 1. Install system packages
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y alsa-utils python3-pyaudio portaudio19-dev
```

### 2. Verify your speaker works
```bash
aplay -l                     # list sound cards
speaker-test -c2 -t wav      # should hear audio from speaker
```
If silent:
```bash
sudo raspi-config
# System Options → Audio → choose your output (HDMI / 3.5mm)
```

### 3. Run the server
```bash
python3 rpi_server.py
```
Note the IP address printed (e.g. `192.168.1.50`). Keep this terminal open.

### 4. Auto-start on boot (optional but recommended)
```bash
sudo nano /etc/systemd/system/wifi-speaker.service
```
Paste:
```ini
[Unit]
Description=WiFi Speaker
After=network-online.target
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
sudo systemctl status wifi-speaker   # should show "active (running)"
```

---

## Windows Laptop Setup

### 1. Install Python 3.10+
Download from https://python.org — tick **"Add Python to PATH"** during install.

### 2. Install the package
```cmd
pip install -r requirements_windows.txt
```

### 3. Run
```cmd
python wifi_speaker.py
```
It will auto-scan for the RPi. Or specify directly:
```cmd
python wifi_speaker.py --host 192.168.1.50
```

### 4. Pick the right audio device (first time)
```cmd
python wifi_speaker.py --list
```
Look for a device tagged `[LOOPBACK ✓]` — this captures ALL audio (Spotify, YouTube, etc.).
```cmd
python wifi_speaker.py --host 192.168.1.50 --device 3
```

### What gets streamed
`pyaudiowpatch` uses **WASAPI loopback** — it captures the signal going to your speakers/headphones at the OS level. This means:
- Spotify, YouTube, VLC, games — everything
- No mic noise
- No extra software needed

### Useful flags
| Flag | Description |
|------|-------------|
| `--host <IP>` | RPi IP address |
| `--device <N>` | Audio device index |
| `--list` | List all audio devices |
| `--volume 0.8` | Volume multiplier (0.0–2.0) |

---

## Android APK Setup

### Option A — Build it yourself (Linux or WSL2)

**Prerequisites:**
```bash
sudo apt install -y python3-pip git zip unzip openjdk-17-jdk \
    autoconf libtool pkg-config zlib1g-dev libncurses5-dev \
    libncursesw5-dev cmake libffi-dev libssl-dev build-essential ccache

pip install -r requirements_android_build.txt
```

**Build:**
```bash
cd android/
buildozer android debug
```
First build takes ~15–25 minutes (downloads Android SDK/NDK).
Output: `android/bin/wifispeaker-1.0-*-debug.apk`

**Install via USB:**
```bash
adb install bin/wifispeaker-*.apk
```
**Or transfer the APK to your phone** via USB/Google Drive → tap the file → allow "Install unknown apps" once.

---

### Option B — Build on Google Colab (no Linux needed)

1. Go to https://colab.research.google.com
2. Create a new notebook
3. Run:
```python
!sudo apt install -y python3-pip git zip unzip openjdk-17-jdk \
    autoconf libtool pkg-config zlib1g-dev libncurses5-dev \
    libncursesw5-dev cmake libffi-dev libssl-dev build-essential ccache
!pip install buildozer==1.5.0 Cython==0.29.37
```
4. Upload `android/` folder contents, then:
```python
%cd android
!buildozer android debug
```
5. Download the APK from the `bin/` folder.

---

### Using the Android App

1. Open **WiFi Speaker** on your phone
2. Enter the RPi IP (e.g. `192.168.1.50`) or tap **Scan for RPi**
3. Tap **Connect & Stream**
4. Grant microphone permission when asked
5. Speak or play audio near the mic — it will come out your RPi speaker

> **Note:** Android only allows mic capture from apps, not system audio (streaming Spotify from Android to RPi requires a third-party audio router app like SoundWire on Android — the mic stream is always available without root).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No sound on RPi | Run `speaker-test -c2 -t wav` and check `raspi-config` audio output |
| Windows can't connect | Check RPi IP with `hostname -I`, ensure same WiFi, check firewall |
| Crackling audio | Increase `QUEUE_MAX` in `rpi_server.py` (default 80) |
| High latency | Decrease `QUEUE_MAX` |
| APK build fails | Ensure JDK 17 is installed: `java -version` |
| Android mic not working | Revoke and re-grant microphone permission in phone Settings |

### Open firewall ports on RPi (if needed)
```bash
sudo ufw allow 8888/tcp
sudo ufw allow 8080/tcp
```

### Check RPi server logs
```bash
sudo journalctl -u wifi-speaker -f
```
