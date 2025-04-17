import cv2
import numpy as np
import yaml
import rtmidi
import time
import moderngl
import moderngl_window as mglw
from moderngl_window import geometry
from threading import Thread
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Define a 7-tone major scale (intervals from base note)
MAJOR_SCALE = [0, 2, 3, 5, 7, 9, 10]

class ConfigReloader(FileSystemEventHandler):
    def __init__(self, filepath, callback):
        self.filepath = filepath
        self.callback = callback

    def on_modified(self, event):
        if os.path.abspath(event.src_path) == os.path.abspath(self.filepath):
            print("Configuration file changed. Reloading...")
            self.callback()

class CameraMIDIDevice(mglw.WindowConfig):
    title = "Camera MIDI Instrument"
    gl_version = (3, 3)
    window_size = (1280, 720)
    aspect_ratio = 16/9
    resizable = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.load_config()

        self.texture = self.ctx.texture(self.window_size, 3, dtype='f1')
        self.quad = geometry.quad_2d()
        self.program = self.ctx.program(
            vertex_shader="""
            #version 330
            in vec2 in_position;
            out vec2 uv;
            void main() {
                gl_Position = vec4(in_position, 0.0, 0.5);
                uv = in_position * 0.5 + 0.5;
            }
            """,
            fragment_shader="""
            #version 330
            uniform sampler2D tex;
            in vec2 uv;
            out vec4 fragColor;
            void main() {
                fragColor = texture(tex, uv);
            }
            """
        )

        self.midi_out = rtmidi.RtMidiOut()
        self.midi_out.openVirtualPort("Camera MIDI")

        self.note_state = [[False] * self.grid_cols for _ in range(self.grid_rows)]
        self.active_cells = [[0.0] * self.grid_cols for _ in range(self.grid_rows)]
        self.last_colors = [[(1.0, 0.5, 0.2)] * self.grid_cols for _ in range(self.grid_rows)]
        self.last_frame = None

        self.thread = Thread(target=self.camera_loop, daemon=True)
        self.thread.start()

        # Setup watchdog to reload config
        event_handler = ConfigReloader("config.yml", self.load_config)
        observer = Observer()
        observer.schedule(event_handler, path=".", recursive=False)
        observer.start()

    def load_config(self):
        with open("config.yml", "r") as f:
            self.config = yaml.safe_load(f)

        self.grid_rows = self.config['grid']['rows']
        self.grid_cols = self.config['grid']['cols']
        self.frame_width = 160 * self.grid_cols
        self.frame_height = 120 * self.grid_rows
        self.frame_rate = self.config['camera']['fps']
        self.camera_index = self.config['camera']['index']

        self.capture = cv2.VideoCapture(self.camera_index)
        self.capture.set(cv2.CAP_PROP_FPS, self.frame_rate)

        self.square_config = [[None] * self.grid_cols for _ in range(self.grid_rows)]
        for square in self.config['midi']['squares']:
            self.square_config[square['row']][square['col']] = square

    def camera_loop(self):
        interval = 1.0 / self.frame_rate
        while True:
            ret, frame = self.capture.read()
            if not ret:
                continue
            frame = cv2.resize(frame, (self.frame_width, self.frame_height))
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self.process_frame(frame_rgb)
            self.last_frame = frame_rgb
            time.sleep(interval)

    def process_frame(self, frame):
        h, w, _ = frame.shape
        cell_h = h // self.grid_rows
        cell_w = w // self.grid_cols

        for row in range(self.grid_rows):
            for col in range(self.grid_cols):
                cell_cfg = self.square_config[row][col]
                if cell_cfg is None:
                    continue

                cell = frame[row * cell_h:(row + 1) * cell_h, col * cell_w:(col + 1) * cell_w]
                avg_color = np.mean(cell.reshape(-1, 3), axis=0)
                gray = cv2.cvtColor(cell, cv2.COLOR_RGB2GRAY)
                luminosity = np.mean(gray)

                threshold = self.config['midi']['trigger']['threshold']
                channel = cell_cfg['channel']
                base_note = cell_cfg['base_note']
                use_scale = cell_cfg.get('color_scale_mapping', False)

                note = base_note

                if use_scale:
                    avg_color_uint8 = np.uint8([[avg_color]])
                    hsv = cv2.cvtColor(avg_color_uint8, cv2.COLOR_RGB2HSV)
                    hue = hsv[0][0][0]
                    scale_idx = int((hue / 180.0) * len(MAJOR_SCALE)) % len(MAJOR_SCALE)
                    note += MAJOR_SCALE[scale_idx]

                if luminosity > threshold and not self.note_state[row][col]:
                    velocity = int(np.clip(avg_color[0] / 255.0 * 127, 112, 127))
                    print(f"Note ON  - Ch:{channel} Note:{note} Vel:{velocity} at ({row},{col})")
                    midi_message = rtmidi.MidiMessage.noteOn(channel, note, velocity)
                    self.midi_out.sendMessage(midi_message)
                    self.note_state[row][col] = True
                    self.active_cells[row][col] = 1.0
                    self.last_colors[row][col] = tuple(avg_color / 255.0)

                elif luminosity <= threshold - 5 and self.note_state[row][col]:
                    self.midi_out.sendMessage(rtmidi.MidiMessage.noteOff(channel, note))
                    print(f"Note OFF - Ch:{channel} Note:{note} at ({row},{col})")
                    self.note_state[row][col] = False

        self.last_frame = frame

    def render(self, time, frametime):
        if self.last_frame is not None:
            display_frame = cv2.resize(self.last_frame, self.window_size)
            flipped = np.flip(display_frame, axis=0)
            self.texture.write(flipped.tobytes())

        self.texture.use()
        self.quad.render(self.program)

        self.draw_grid_overlay()
        self.draw_cell_feedback(frametime)

    def draw_grid_overlay(self):
        self.ctx.enable_only(moderngl.BLEND)
        line_color = (0.2, 0.7, 1.0, 0.5)
        overlay_prog = self.ctx.program(
            vertex_shader="""
            #version 330
            in vec2 in_position;
            void main() {
                gl_Position = vec4(in_position, 0.0, 1.0);
            }
            """,
            fragment_shader="""
            #version 330
            out vec4 fragColor;
            uniform vec4 color;
            void main() {
                fragColor = color;
            }
            """
        )
        overlay_prog['color'].value = line_color

        lines = []
        for r in range(1, self.grid_rows):
            y = 2.0 * (1 - r / self.grid_rows) - 1.0
            lines += [(-1.0, y), (1.0, y)]
        for c in range(1, self.grid_cols):
            x = 2.0 * (c / self.grid_cols) - 1.0
            lines += [(x, -1.0), (x, 1.0)]

        vbo = self.ctx.buffer(np.array(lines, dtype='f4'))
        vao = self.ctx.simple_vertex_array(overlay_prog, vbo, 'in_position')
        vao.render(moderngl.LINES)

    def draw_cell_feedback(self, frametime):
        feedback_prog = self.ctx.program(
            vertex_shader="""
            #version 330
            in vec2 in_position;
            void main() {
                gl_Position = vec4(in_position, 0.0, 1.0);
            }
            """,
            fragment_shader="""
            #version 330
            out vec4 fragColor;
            uniform vec4 color;
            void main() {
                fragColor = color;
            }
            """
        )
        for row in range(self.grid_rows):
            for col in range(self.grid_cols):
                if self.active_cells[row][col] > 0.01:
                    x1 = 2.0 * (col / self.grid_cols) - 1.0
                    x2 = 2.0 * ((col + 1) / self.grid_cols) - 1.0
                    y1 = 2.0 * (1 - (row + 1) / self.grid_rows) - 1.0
                    y2 = 2.0 * (1 - row / self.grid_rows) - 1.0
                    quad_coords = [
                        (x1, y1), (x2, y1), (x1, y2),
                        (x1, y2), (x2, y1), (x2, y2)
                    ]
                    alpha = self.active_cells[row][col]
                    r, g, b = self.last_colors[row][col]
                    feedback_prog['color'].value = (r, g, b, alpha)
                    vbo = self.ctx.buffer(np.array(quad_coords, dtype='f4'))
                    vao = self.ctx.simple_vertex_array(feedback_prog, vbo, 'in_position')
                    vao.render(moderngl.TRIANGLES)
                    self.active_cells[row][col] *= 0.92

    def on_render(self, time, frametime):
        self.render(time, frametime)

    def close(self):
        self.capture.release()
        self.midi_out.closePort()

if __name__ == '__main__':
    mglw.run_window_config(CameraMIDIDevice)
