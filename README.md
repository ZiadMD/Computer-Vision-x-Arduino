# CVxArduino — Face & Hand Detection → Arduino LEDs

This project demonstrates computer-vision → microcontroller interaction. It uses MediaPipe + OpenCV on the PC to detect facial expressions (smile / neutral / frown) and fingers (0–5). The PC sends short messages to an Arduino over serial; the Arduino lights LEDs according to the received message.

This README explains the code in detail, how the system works, the wiring, how to upload the Arduino sketch, how to run the Python code, tuning tips, and where to place pictures and a video demonstrating the project.

---

Table of contents
- Project overview
- Files and code walkthrough (every important function / class explained)
- Hardware parts & wiring
- Arduino sketch: behavior and upload instructions
- Python: dependencies and running (face and finger modes)
- Serial protocol and examples
- Step-by-step build & test guide (do-it-yourself)
- Tuning & troubleshooting
- Where to add photos and a demo video

---

Project overview
----------------
The goal is a simple, extensible pipeline:

1. PC camera + MediaPipe detect face/hand state.
2. Python program computes a small label or integer (for example: `"smile"` or `3`).
3. Python sends the short message over a serial port to an Arduino (USB CDC / /dev/ttyACM0).
4. Arduino translates the message to LED patterns (pins 2..6 used for finger counts, or pin 2/3 used for expression LEDs in earlier sketches).

This repository contains multiple scripts and one Arduino sketch. Pick the script that fits what you want to test:
- `facial_project.py` — MediaPipe FaceMesh to detect smile / neutral / frown and send text labels to Arduino.
- `_5Fingers.py` — (refactored, modular) MediaPipe Hands to count how many fingers are extended and send an integer 0..5 to Arduino.
- `serial_test.py` — small utility to list serial ports and send or read a line (useful to test the Arduino independently).
- `arduino_code.cpp` — the Arduino sketch to receive either textual labels (older variants) or an integer count (current version), and light LEDs accordingly.

Files in the repo (short list)
- `facial_project.py` — face expression detection, sends labels like `smile`, `neutral`, `frown`.
- `_5Fingers.py` — clean, modular finger counter; default sends integer counts `0\n`..`5\n`.
- `serial_test.py` — small serial CLI tool for manual testing of the Arduino/port.
- `arduino_code.cpp` — Arduino sketch that reads an integer and lights LEDs on pins 2..6 (first N LEDs on).
- `README.md` — this file.


Code walkthrough — detailed
--------------------------
This section explains the key code in each file and how it behaves. Read this carefully if you want to change behavior or tune detection.

1) `_5Fingers.py` (recommended for finger-count → Arduino)

- High level design
  - The script is modular: it exposes `SerialClient` and `HandCounter` classes and a `run_camera_loop()` function.
  - It uses `argparse` for CLI flags like `--port`, `--baud`, `--smooth`, `--noserial`, `--camera`, `--verbose`.

- SerialClient
  - Purpose: encapsulate pyserial usage and make it safe when pyserial isn't present or the port cannot be opened.
  - Constructor arguments: `port`, `baud`, `retries`, `delay`.
  - `open()`: attempts to open the given port (or auto-discovers `/dev/ttyACM*` or `/dev/ttyUSB*`) with retries.
  - `send_count(n)`: writes the ASCII integer plus newline `"N\n"` to the serial port. Returns True on success. Handles exceptions and closes the port if writes fail.
  - `close()`: closes port on exit.

- HandCounter
  - Purpose: encapsulate heuristics for counting fingers using MediaPipe hand landmarks.
  - Constructor: `assume_right_hand` (fallback if MediaPipe doesn't report handedness), `flipped` (True if the image frames are mirrored/flipped horizontally).
  - `count(hand_landmarks, handedness_label)`: returns an integer 0..5. It uses the following heuristics:
    - Thumb: compares thumb tip (landmark 4) and thumb IP (landmark 3). The direction depends on `hand_label` and whether the frame is mirrored. For many webcam setups where we horizontally flip the frame before displaying, the condition used is: for the right hand, thumb open if tip.x < ip.x.
    - Other fingers: for each finger tip (8, 12, 16, 20) we compare tip.y < pip.y (PIP = tip_id - 2); if tip is above pip the finger is counted as extended.
    - The final count is clamped to [0,5].

- Main loop and smoothing
  - The script opens the camera, flips the frame horizontally (mirror), processes with MediaPipe Hands, counts fingers for the first detected hand, pushes the detected count into a small `deque` buffer (`--smooth` frames) and computes the average (rounded) to produce a stabilized `avg` count.
  - The script only sends to serial when `avg` changes (simple debounce), avoiding repeated writes and flickering LEDs.

- CLI options
  - `--port`: serial device path (default `/dev/ttyACM0`). If not desired, use `--noserial`.
  - `--baud`: default 9600.
  - `--smooth`: number of frames for smoothing (default 5). Increase to make detection steadier; decrease to be more responsive.
  - `--noserial`: run without attempting to open serial port.
  - `--verbose`: enable DEBUG logging for more details.


2) `arduino_code.ino` (current version: integer counts 0..5)

- Overview
  - The sketch reads ASCII lines from Serial terminated by `\n`.
  - If the line is a valid integer, it clamps to the valid range (0..5) and calls `setLedsCount(n)`.
  - `setLedsCount(n)` lights the first `n` LEDs among `LED_PINS = {2,3,4,5,6}` and turns the rest off.
  - After updating the LEDs the sketch replies `ACK: n` on Serial for debugging.
  - On startup the sketch prints `ARDUINO READY` so the host can detect the device ready after upload/reset.

- Serial protocol (simple and human-readable)
  - PC -> Arduino: ASCII integer followed by newline (for example `3\n`).
  - Arduino -> PC: `ACK: <n>\n` (or `ERR: <text>` for invalid commands).


3) `facial_project.py` (face expression → Arduino)

- High level
  - Uses MediaPipe FaceMesh to get facial landmarks.
  - The smile/frown detector uses these landmarks: mouth left corner (61), mouth right corner (291), upper inner lip (13), lower inner lip (14). It computes mouth width vs height and normalizes by face width. A small smoothing buffer averages normalized mouth width and corner offset for stability.
  - The detector returns a label: `smile`, `frown`, or `neutral`. The default thresholds are tuned but may need adjustments for camera distance and face size.
  - The script opens serial safely and sends the text label only when it changes (debounce). It overlays the detected label and the normalized mouth width value on the camera feed.

- Where to tune
  - In `detect_smile_frown()` you can adjust `smile_norm_threshold`, `frown_norm_threshold`, and `corner_y_margin_norm` to suit your face distance and camera.
  - Buffer length for smoothing is currently 6 frames in that script; increase for steadier detection, decrease for responsiveness.


4) `serial_test.py` (manual helper)

- Usage examples
  - `python serial_test.py --list` — lists detected serial ports.
  - `python serial_test.py --port /dev/ttyACM0 --send "3\n"` — send a message and print any response.
  - `python serial_test.py --port /dev/ttyACM0 --interactive` — manually type commands and see Arduino replies.

- Helpful when you want to check whether the Arduino is responding without running the vision code.


Hardware parts & wiring
-----------------------

[![Wiring diagram](assets/circuit%20diagram.png)](wiring_diagram.png)

Minimum hardware:
- Any Arduino-compatible board with a USB serial (Uno, Nano Every, Leonardo, etc.)
- 5 LEDs (or fewer) with current-limiting resistors (220 $\ohm$ or 330 $\ohm$ )
- Jumper wires / breadboard
- USB cable from PC to Arduino

Wiring (default mapping used by `arduino_code.ino`):

- LED 1: Arduino digital pin 2 → LED (with resistor) → GND
- LED 2: Arduino digital pin 3 → LED (with resistor) → GND
- LED 3: Arduino digital pin 4 → LED (with resistor) → GND
- LED 4: Arduino digital pin 5 → LED (with resistor) → GND
- LED 5: Arduino digital pin 6 → LED (with resistor) → GND

Note: If you use a board with 3.3V logic or differently-powered LEDs, account for voltage/current appropriately. If you want to use a single RGB LED or a shift register/LED driver, update `arduino_code.ino` accordingly.


Uploading the Arduino sketch
----------------------------
Option A — Arduino IDE (easy)
1. Open Arduino IDE.
2. Copy/paste the contents of `arduino_code.cpp` into a new sketch.
3. Select Board and Port (Tools → Board, Tools → Port → `/dev/ttyACM0`).
4. Click Upload.

Option B — arduino-cli (CLI)
1. Install `arduino-cli` and set it up (see arduino-cli docs).
2. Find your board's FQBN, e.g. `arduino:avr:uno`.
3. Compile and upload:

```bash
arduino-cli compile --fqbn <your-fqbn> /path/to/arduino_code.ino
arduino-cli upload -p /dev/ttyACM0 --fqbn <your-fqbn> /path/to/arduino_code.ino
```


Python dependencies & setup
--------------------------
I tested the Python scripts with Python 3.11, but they should work on 3.8+.

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install opencv-python mediapipe pyserial
```

If you have a platform-specific wheel for MediaPipe, follow the MediaPipe installation notes for your OS.


Running the visual programs
---------------------------
1. Test serial connectivity (optional):

```bash
# list ports
python serial_test.py --list

# send a sample count (e.g., 3) and expect ACK
python serial_test.py --port /dev/ttyACM0 --baud 9600 --send "3\n"
```

2. Run finger count (visual + Arduino):

```bash
python _5Fingers.py --port /dev/ttyACM0 --baud 9600
```

Use `--noserial` to run the visual-only version if you don't want to use an Arduino.

3. Run face-expression detection (smile / neutral / frown):

```bash
python facial_project.py
```

Note: `facial_project.py` is tuned to send textual labels like `smile`/`neutral`. The shipped `arduino_code.cpp` expects integers 0..5 — if you want to use face-expression script with the current Arduino sketch, change the Arduino sketch to accept labels or modify `facial_project.py` to convert expressions into numbers.


Serial protocol summary
----------------------
- Finger counter: PC -> Arduino: `N\n` where N is an integer 0..5. Arduino replies: `ACK: N`.
- Face expression (older variant): PC -> Arduino: `smile\n` / `neutral\n` / `frown\n`. Arduino older sketches accepted these. Current `arduino_code.cpp` expects integers.


Step-by-step build & test guide (DIY)
-------------------------------------
This step-by-step will get you from nothing to a working demo.

1) Hardware assembly
  - Connect 5 LEDs to pins 2..6 (each through a resistor to GND). Make sure LEDs are oriented correctly.
  - Connect Arduino to PC via USB.

2) Upload Arduino sketch
  - Use the Arduino IDE or `arduino-cli` to upload `arduino_code.cpp`.
  - After upload, open the serial monitor at 9600 baud to see `ARDUINO READY`.

3) Test Arduino with `serial_test.py`
  - Run `python serial_test.py --list` to find your port.
  - Run `python serial_test.py --port /dev/ttyACM0 --send "2\n"` and verify the first two LEDs light and the script prints `ACK: 2`.

4) Install Python deps and run `_5Fingers.py`
  - Create a venv and install dependencies (see above).
  - Run `python _5Fingers.py --port /dev/ttyACM0`.
  - Hold up a number of fingers and watch the LED pattern change after a short smoothing delay.

5) (Optional) Facial expression mode
  - Upload a different Arduino sketch that understands `smile`/`neutral` if you want to use `facial_project.py` directly, or modify `facial_project.py` to map labels to integers.


Tuning & troubleshooting
------------------------
- No serial port / permission denied: Add your user to `dialout` (Linux):

```bash
sudo usermod -a -G dialout $USER
# log out and log in again
```

- Device busy: close other programs that may hold the port (Arduino IDE serial monitor). Check `lsof /dev/ttyACM0` or `fuser -v /dev/ttyACM0`.

- Finger detection errors:
  - Increase smoothing (`--smooth 7`) to reduce jitter.
  - If thumb detection is inverted, change `HandCounter(flipped=True)` to `flipped=False` or adjust the thumb heuristic in `HandCounter.count()`.
  - Lighting conditions and camera angle influence detection; brighter, front-facing light works best.

- Face expression detection tuning: adjust thresholds in `facial_project.py` inside `detect_smile_frown()` (smile/frown ratio thresholds and corner margin).
