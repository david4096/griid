import rtmidi
import time
import fluidsynth
import curses  # Use curses for detecting key presses

def main(stdscr):
    # Clear screen
    stdscr.clear()

    fs = fluidsynth.Synth()
    fs.start(driver="coreaudio")
    sfid = fs.sfload("/Users/david/Downloads/Sonatina_Symphonic_Orchestra_SF2/Sonatina_Symphonic_Orchestra.sf2")
    fs.program_select(0, sfid, 0, 1)
    fs.cc(0, 7, 127)  # Set volume to max for channel 0

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
    
    program = 12
    stdscr.addstr(0, 0, f"Current Program: {program}")
    stdscr.refresh()

    # Set nodelay to make getch non-blocking
    stdscr.nodelay(True)

    # Polling loop for MIDI events
    stdscr.addstr(1, 0, "Use UP and DOWN arrow keys to change the program number.")
    stdscr.refresh()

    while True:
        # Check if there's a key press
        key = stdscr.getch()

        if key == curses.KEY_UP:
            program = (program + 1) % 128  # Loop back to 0 after 127
            stdscr.clear()
            stdscr.addstr(0, 0, f"Program changed to: {program}")
            stdscr.refresh()
        elif key == curses.KEY_DOWN:
            program = (program - 1) % 128  # Loop back to 127 after 0
            stdscr.clear()
            stdscr.addstr(0, 0, f"Program changed to: {program}")
            stdscr.refresh()

        # Poll MIDI input messages
        msg = midi_in.getMessage()
        if msg:
            message = msg.getRawData()
            status = message[0] & 0xF0
            channel = message[0] & 0x0F
            if status == 0x90 and message[2] > 0:
                note = message[1]
                velocity = message[2]
                print(f"Note ON - Channel: {channel}, Note: {note}, Velocity: {velocity}")
                fs.program_select(0, sfid, 0, program)
                fs.noteon(0, note - 20, velocity)
            elif status == 0x80 or (status == 0x90 and message[2] == 0):
                note = message[1]
                print(f"Note OFF - Channel: {channel}, Note: {note}")
                fs.noteoff(0, note)

        time.sleep(0.01)  # Small delay for polling MIDI events

# Run the curses main function
curses.wrapper(main)
