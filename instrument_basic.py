import rtmidi
import time
import fluidsynth

fs = fluidsynth.Synth()
fs.start(driver="coreaudio")
sfid = fs.sfload("/Users/david/Downloads/Sonatina_Symphonic_Orchestra_SF2/Sonatina_Symphonic_Orchestra.sf2")
#sfid = fs.sfload("/Users/david/Downloads/MuseScore_General.sf2")
fs.program_select(0, sfid, 0, 1)

midi_in = rtmidi.RtMidiIn()
ports = midi_in.getPortCount()
for i in range(ports):
    name = midi_in.getPortName(i)
    print(f"{i}: {name}")
    if "Camera MIDI" in name:
        midi_in.openPort(i)
        print("Opened MIDI port!")
        break
else:
    raise RuntimeError("Camera MIDI port not found.")

print("Polling for MIDI events...")
while True:
    msg = midi_in.getMessage()
    if msg:
        message = msg.getRawData()  # <-- Fix here!
        status = message[0] & 0xF0
        channel = message[0] & 0x0F
        if status == 0x90 and message[2] > 0:
            note = message[1]
            velocity = message[2]
            print(f"Note ON - Channel: {channel}, Note: {note}, Velocity: {velocity}")
            # DRUMs fs.program_select(0, sfid, 0, 36)
            fs.program_select(0, sfid, 0, channel)
            fs.noteon(0, note, velocity)
        elif status == 0x80 or (status == 0x90 and message[2] == 0):
            note = message[1]
            print(f"Note OFF - Channel: {channel}, Note: {note}")
            fs.noteoff(0, note)
    time.sleep(0.01)
