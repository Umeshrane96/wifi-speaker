from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.slider import Slider
from kivy.clock import Clock
from kivy.core.window import Window
import threading, socket, struct, time

RATE = 48000
CHANNELS = 1
CHUNK = 2048
PORT = 8888

try:
    from jnius import autoclass
    AudioRecord = autoclass('android.media.AudioRecord')
    AudioFormat = autoclass('android.media.AudioFormat')
    MediaRecorder = autoclass('android.media.MediaRecorder$AudioSource')
    IS_ANDROID = True
except Exception:
    IS_ANDROID = False


class WiFiSpeakerApp(App):

    def build(self):
        Window.clearcolor = (0.05, 0.05, 0.05, 1)
        self._streaming = False
        self._stop = threading.Event()
        self._sock = None
        self._volume = 1.0

        root = BoxLayout(orientation='vertical', padding=24, spacing=16)
        root.add_widget(Label(text='WiFi Speaker', font_size='26sp', bold=True, size_hint_y=None, height=44))
        root.add_widget(Label(text='Stream mic audio to your Raspberry Pi', font_size='13sp', color=(0.6,0.6,0.6,1), size_hint_y=None, height=28))

        self.ip_input = TextInput(hint_text='RPi IP  e.g. 192.168.1.7', multiline=False, size_hint_y=None, height=48, font_size='16sp')
        root.add_widget(self.ip_input)

        scan_btn = Button(text='Scan for RPi', size_hint_y=None, height=42, font_size='14sp')
        scan_btn.bind(on_press=self._scan)
        root.add_widget(scan_btn)

        self.main_btn = Button(text='Connect & Stream', size_hint_y=None, height=80, font_size='18sp', bold=True, background_color=(0.67,0.55,0.98,1))
        self.main_btn.bind(on_press=self._toggle)
        root.add_widget(self.main_btn)

        self.status = Label(text='Enter RPi IP and tap Connect', font_size='13sp', color=(0.6,0.6,0.6,1), size_hint_y=None, height=28)
        root.add_widget(self.status)

        vol_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=36, spacing=12)
        vol_row.add_widget(Label(text='Volume', font_size='13sp', size_hint_x=None, width=70))
        self.slider = Slider(min=0, max=2, value=1.0, step=0.05)
        self.slider.bind(value=lambda s, v: setattr(self, '_volume', v))
        vol_row.add_widget(self.slider)
        root.add_widget(vol_row)
        root.add_widget(Label())
        return root

    def _toggle(self, *_):
        if self._streaming:
            self._stop_stream()
        else:
            self._start_stream()

    def _start_stream(self):
        host = self.ip_input.text.strip()
        if not host:
            self._set_status('Enter RPi IP first')
            return
        self._stop.clear()
        self._streaming = True
        self.main_btn.text = 'Disconnect'
        self.main_btn.background_color = (0.94, 0.27, 0.27, 1)
        self._set_status('Connecting...')
        threading.Thread(target=self._stream_thread, args=(host,), daemon=True).start()

    def _stop_stream(self):
        self._stop.set()
        self._streaming = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        Clock.schedule_once(lambda dt: self._reset_ui(), 0)

    def _reset_ui(self):
        self.main_btn.text = 'Connect & Stream'
        self.main_btn.background_color = (0.67, 0.55, 0.98, 1)
        self._set_status('Disconnected')

    def _stream_thread(self, host):
        if IS_ANDROID:
            self._stream_android(host)
        else:
            self._stream_test(host)

    def _stream_android(self, host):
        min_buf = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        rec = AudioRecord(MediaRecorder.MIC, RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, max(min_buf * 4, CHUNK * 4))
        buf = bytearray(CHUNK * 2)
        while not self._stop.is_set():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(5)
                    s.connect((host, PORT))
                    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    s.settimeout(None)
                    self._sock = s
                    Clock.schedule_once(lambda dt: self._set_status('Streaming to ' + host), 0)
                    rec.startRecording()
                    try:
                        while not self._stop.is_set():
                            n = rec.read(buf, 0, len(buf))
                            if n <= 0:
                                continue
                            chunk = bytes(buf[:n])
                            if abs(self._volume - 1.0) > 0.01:
                                import array as arr
                                sa = arr.array('h', chunk)
                                sa = arr.array('h', (max(-32768, min(32767, int(x * self._volume))) for x in sa))
                                chunk = bytes(sa)
                            s.sendall(struct.pack('!I', len(chunk)) + chunk)
                    finally:
                        rec.stop()
            except Exception:
                if not self._stop.is_set():
                    Clock.schedule_once(lambda dt: self._set_status('Retrying...'), 0)
                    time.sleep(3)
        rec.release()
        Clock.schedule_once(lambda dt: self._reset_ui(), 0)

    def _stream_test(self, host):
        import math, array as arr
        t = 0
        while not self._stop.is_set():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((host, PORT))
                    self._sock = s
                    Clock.schedule_once(lambda dt: self._set_status('Connected to ' + host), 0)
                    while not self._stop.is_set():
                        samples = arr.array('h', (int(32767 * 0.3 * math.sin(2 * math.pi * 440 * (t + i) / RATE)) for i in range(CHUNK)))
                        t += CHUNK
                        s.sendall(struct.pack('!I', len(samples) * 2) + bytes(samples))
                        time.sleep(CHUNK / RATE)
            except Exception:
                if not self._stop.is_set():
                    time.sleep(3)
        Clock.schedule_once(lambda dt: self._reset_ui(), 0)

    def _scan(self, *_):
        self._set_status('Scanning...')
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _scan_thread(self):
        try:
            local = socket.gethostbyname(socket.gethostname())
            subnet = '.'.join(local.split('.')[:3])
        except Exception:
            Clock.schedule_once(lambda dt: self._set_status('Scan failed - enter IP manually'), 0)
            return
        found = []
        lock = threading.Lock()

        def probe(ip):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.4)
                    if s.connect_ex((ip, PORT)) == 0:
                        with lock:
                            found.append(ip)
            except Exception:
                pass

        threads = [threading.Thread(target=probe, args=(subnet + '.' + str(i),), daemon=True) for i in range(1, 255)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        def upd(dt):
            if found:
                self.ip_input.text = found[0]
                self._set_status('Found RPi at ' + found[0])
            else:
                self._set_status('RPi not found - enter IP manually')
        Clock.schedule_once(upd, 0)

    def _set_status(self, msg):
        self.status.text = msg


if __name__ == '__main__':
    WiFiSpeakerApp().run()
