import rtmidi
import time
import os
import numpy as np
import sounddevice as sd
import soundfile as sf
import argparse
import threading
from collections import OrderedDict

parser = argparse.ArgumentParser(description="Polyphonic MIDI Sample Player")
parser.add_argument("sample_dir", help="Directory containing .wav files")
args = parser.parse_args()

# ===== Sample Loading =====
def load_samples(directory):
    samples = []
    for filename in sorted(os.listdir(directory)):
        if filename.lower().endswith(".wav"):
            filepath = os.path.join(directory, filename)
            data, sr = sf.read(filepath, dtype='float32')
            if data.ndim == 1:
                data = np.expand_dims(data, axis=1)
            samples.append((data, sr, filename))
    return samples

samples = load_samples(args.sample_dir)
base_note = 36
note_to_sample = {base_note + i: sample for i, sample in enumerate(samples)}

# ===== Fade Utility =====
def apply_fade(data, sr, ms=10):
    n = int(sr * ms / 1000)
    fade = np.linspace(0, 1, n)
    out = data.copy()
    for ch in range(out.shape[1]):
        out[:n, ch] *= fade
        out[-n:, ch] *= fade[::-1]
    return out

# ===== Voice =====
class Voice(threading.Thread):
    def __init__(self, note, data, sr, velocity, on_end):
        super().__init__()
        self.note = note
        self.data = apply_fade(data, sr)
        self.sr = sr
        self.velocity = velocity / 127.0
        self.running = True
        self.on_end = on_end
        self.daemon = True
        self.lock = threading.Lock()

    def run(self):
        stream = sd.OutputStream(samplerate=self.sr, channels=self.data.shape[1], dtype='float32')
        with stream:
            i = 0
            n = len(self.data)
            while self.running:
                with self.lock:
                    block = self.data[i:i+256] * self.velocity
                    if len(block) < 256:
                        block = np.concatenate([block, self.data[:256 - len(block)]], axis=0)
                    stream.write(block)
                    i = (i + 256) % n
        self.on_end(self.note)

    def stop(self):
        with self.lock:
            self.running = False

# ===== Voice Manager =====
class VoiceManager:
    def __init__(self, max_voices=16):
        self.voices = OrderedDict()
        self.max_voices = max_voices
        self.lock = threading.Lock()

    def on_end(self, note):
        with self.lock:
            if note in self.voices:
                del self.voices[note]

    def note_on(self, note, data, sr, velocity, filename):
        with self.lock:
            if note in self.voices:
                self.voices[note].stop()
                del self.voices[note]
            if len(self.voices) >= self.max_voices:
                _, oldest = self.voices.popitem(last=False)
                oldest.stop()
            voice = Voice(note, data, sr, velocity, self.on_end)
            self.voices[note] = voice
            voice.start()
            print(f"Note ON {note} Vel {velocity} -> {filename}")

    def note_off(self, note):
        with self.lock:
            if note in self.voices:
                self.voices[note].stop()
                del self.voices[note]
                print(f"Note OFF {note}")

# ===== MIDI Setup =====
midi_in = rtmidi.RtMidiIn()
for i in range(midi_in.getPortCount()):
    name = midi_in.getPortName(i)
    if "Camera MIDI" in name:
        midi_in.openPort(i)
        break
else:
    raise RuntimeError("Camera MIDI port not found.")

# ===== Main Loop =====
manager = VoiceManager(max_voices=16)

print("Ready.")
while True:
    msg = midi_in.getMessage()
    if msg:
        data = msg.getRawData()
        status = data[0] & 0xF0
        note = data[1]
        velocity = data[2]
        if status == 0x90 and velocity > 0:
            if note in note_to_sample:
                sample, sr, fname = note_to_sample[note]
                manager.note_on(note, sample, sr, velocity, fname)
        elif status == 0x80 or (status == 0x90 and velocity == 0):
            manager.note_off(note)
    time.sleep(0.001)
