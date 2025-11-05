Table of contents
-----------------

- [Project overview](#project-overview)
- [Code walkthrough — detailed](#code-walkthrough--detailed)
- [Hardware parts & wiring](#hardware-parts--wiring)
- [Uploading the Arduino sketch](#uploading-the-arduino-sketch)
- [Python dependencies & setup](#python-dependencies--setup)
- [Running the visual programs](#running-the-visual-programs)
- [Serial protocol summary](#serial-protocol-summary)
- [Step-by-step build & test guide (DIY)](#step-by-step-build--test-guide-diy)
- [Tuning & troubleshooting](#tuning--troubleshooting)

---

Project overview
-----------------

<table>
  <tr>
    <td align="center">
      <a href="assets/videos/_5Fingers.mp4">
        <img src="assets/images/_5Fingers%20Thumbnail.png" alt="Video 1">
      </a>
    </td>
    <td align="center">
      <a href="assets/videos/FacialExpression.mp4">
        <img src="assets/images/FacialExpression%20Thumbnail.png" alt="Video 2">
      </a>
    </td>
  </tr>
</table>


1. PC camera + MediaPipe detect face/hand state.
2. Python program computes a small label or integer (for example: `"smile"` or `3`).
3. Python sends the short message over a serial port to an Arduino (USB CDC / /dev/ttyACM0).
4. Arduino translates the message to LED patterns (pins 2..6 used for finger counts or expression signals).

This repository contains multiple scripts and one Arduino sketch. Pick the script that fits what you want to test:
- `FacialExpression.py` — MediaPipe FaceMesh to detect smile / neutral / frown and send **numeric signals** (1=frown, 2=neutral, 3=smile) to Arduino.
- `_5Fingers.py` — (refactored, modular) MediaPipe Hands to count how many fingers are extended and send an integer 0..5 to Arduino.
- `serial_test.py` — small utility to list serial ports and send or read a line (useful to test the Arduino independently).
- `arduino_code.cpp` — the Arduino sketch to receive integer counts (0..5) and light LEDs accordingly.

---

Code walkthrough — detailed
--------------------------
- ### `_5Fingers.py`

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

- ### `arduino_code.cpp`

  - Overview
    - The sketch reads ASCII lines from Serial terminated by `\n`.
    - If the line is a valid integer, it clamps to the valid range (0..5) and calls `setLedsCount(n)`.
    - `setLedsCount(n)` lights the first `n` LEDs among `LED_PINS = {2,3,4,5,6}` and turns the rest off.
    - After updating the LEDs the sketch replies `ACK: n` on Serial for debugging.
    - On startup the sketch prints `ARDUINO READY` so the host can detect the device ready after upload/reset.

  - Serial protocol (simple and human-readable)
    - PC -> Arduino: ASCII integer followed by newline (for example `3\n`).
    - Arduino -> PC: `ACK: <n>\n` (or `ERR: <text>` for invalid commands).

- ### `FacialExpression.py`

  - High level
    - Uses MediaPipe FaceMesh to get facial landmarks.
    - The smile/frown detector (`SmileDetector` class) uses these landmarks: mouth left corner (61), mouth right corner (291), upper inner lip (13), lower inner lip (14). It computes mouth width vs height and normalizes by face width. A small smoothing buffer averages normalized mouth width and corner offset for stability.
    - The detector returns a label: `smile`, `frown`, or `neutral`. The default thresholds are tuned but may need adjustments for camera distance and face size.
    - The script opens serial safely and **maps labels to numeric signals** before sending:
      - `neutral` → `2`
      - `smile` → `3`
      - `frown` → `1`
    - Sends only when the label changes (debounce). It overlays the detected label and the normalized mouth width value on the camera feed.

  - Where to tune
    - In `SmileDetector.__init__()` you can adjust `smile_thresh`, `frown_thresh`, and `corner_margin` to suit your face distance and camera.
    - Buffer length for smoothing is `buf_size` parameter (default 6 frames); increase for steadier detection, decrease for responsiveness.
    - CLI options: `--smooth N` sets the buffer size.

  - CLI options
    - `--port`: serial device path (default `/dev/ttyACM0`).
    - `--baud`: default 9600.
    - `--smooth`: number of frames to smooth over (default 6).
    - `--noserial`: run without attempting to open serial port.
    - `--camera`: camera device index (default 0).
    - `--verbose`: enable DEBUG logging.


- ### `serial_test.py`

  - Usage examples
    - `python serial_test.py --list` — lists detected serial ports.
    - `python serial_test.py --port /dev/ttyACM0 --send "3\n"` — send a message and print any response.
    - `python serial_test.py --port /dev/ttyACM0 --interactive` — manually type commands and see Arduino replies.

  - Helpful when you want to check whether the Arduino is responding without running the vision code.

---

Hardware parts & wiring
-----------------------

[![Wiring diagram](assets/circuit%20diagram.png)](wiring_diagram.png)

## Minimum hardware:
- Any Arduino-compatible board with a USB serial (Uno, Nano Every, Leonardo, etc.)
- 5 LEDs (or fewer) with current-limiting resistors (220Ω or 330Ω)
- Jumper wires / breadboard
- USB cable from PC to Arduino

## Wiring:

- LED 1: Arduino digital pin 2 → LED (with resistor) → GND
- LED 2: Arduino digital pin 3 → LED (with resistor) → GND
- LED 3: Arduino digital pin 4 → LED (with resistor) → GND
- LED 4: Arduino digital pin 5 → LED (with resistor) → GND
- LED 5: Arduino digital pin 6 → LED (with resistor) → GND
--- 

Uploading the Arduino sketch
---------------------------

### Option A — Arduino IDE
1. Open Arduino IDE.
2. Copy/paste the contents of `arduino_code.cpp` into a new sketch.
3. Select Board and Port (Tools → Board, Tools → Port → `/dev/ttyACM0`).
4. Click Upload.

### Option B — arduino-cli
1. Install `arduino-cli` and set it up (see arduino-cli docs).
2. Find your board's FQBN, e.g. `arduino:avr:uno`.
3. Compile and upload:

```bash
arduino-cli compile --fqbn <your-fqbn> /path/to/arduino_code.cpp
arduino-cli upload -p /dev/ttyACM0 --fqbn <your-fqbn> /path/to/arduino_code.cpp
```

---

Python dependencies & setup
--------------------------

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Or manually:

```bash
pip install opencv-python mediapipe pyserial
```

Running the visual programs
---------------------------
### 1. Test serial connectivity (optional):

```bash
# list ports
python serial_test.py --list

# send a sample count (e.g., 3) and expect ACK
python serial_test.py --port /dev/ttyACM0 --baud 9600 --send "3\n"
```

### 2. Run finger count (visual + Arduino):

```bash
python _5Fingers.py --port /dev/ttyACM0 --baud 9600
```

Use `--noserial` to run the visual-only version if you don't want to use an Arduino.

### 3. Run face-expression detection (smile / neutral / frown):

```bash
python FacialExpression.py --port /dev/ttyACM0
```

The script now sends numeric signals (1/2/3) to the Arduino, compatible with the current `arduino_code.cpp`.

---

Serial protocol summary
----------------------
- **Finger counter**: PC → Arduino: `N\n` where N is an integer 0..5. Arduino replies: `ACK: N`.
- **Face expression**: PC → Arduino: `1\n` (frown), `2\n` (neutral), or `3\n` (smile). Arduino replies: `ACK: N` and lights first N LEDs.

Both scripts send integers, making them compatible with the same Arduino sketch.

---

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

5) Run facial expression mode
  - Run `python FacialExpression.py --port /dev/ttyACM0`.
  - Smile, frown, or stay neutral and watch the LEDs change (1, 2, or 3 LEDs respectively).
