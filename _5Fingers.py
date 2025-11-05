import argparse
import logging
import time
from collections import deque
from typing import Optional

import cv2
import mediapipe as mp

try:
    import serial
    import serial.tools.list_ports
    from serial.serialutil import SerialException
except Exception:
    serial = None


# ---------------------------------------------------------------------------
# Configuration / Defaults
# ---------------------------------------------------------------------------
DEFAULT_PORT = "/dev/ttyACM0"
DEFAULT_BAUD = 9600
DEFAULT_SMOOTH = 5
DEFAULT_CAMERA = 0

# Mediapipe landmark ids
FINGER_TIP_IDS = [4, 8, 12, 16, 20]


# ---------------------------------------------------------------------------
# Serial helper
# ---------------------------------------------------------------------------
class SerialClient:
    """Simple serial wrapper that tries to open a port and provides a send() method.

    If pyserial is not installed or the port cannot be opened, the client becomes a
    no-op (useful for running without hardware).
    """

    def __init__(self, port: Optional[str], baud: int = DEFAULT_BAUD, retries: int = 3, delay: float = 1.0):
        self.port = port
        self.baud = baud
        self.retries = retries
        self.delay = delay
        self._ser = None
        self._available = False
        if port and serial:
            self.open()
        else:
            logging.info("Serial not available or port not provided; running in noserial mode")

    def open(self) -> None:
        candidates = [self.port] if self.port else [p.device for p in serial.tools.list_ports.comports() if ('ACM' in p.device or 'USB' in p.device)]
        for p in candidates:
            for attempt in range(1, self.retries + 1):
                try:
                    self._ser = serial.Serial(p, self.baud, timeout=1)
                    time.sleep(0.1)  # give device a moment
                    self._available = True
                    logging.info("Opened serial port %s at %d", p, self.baud)
                    return
                except SerialException as e:
                    logging.debug("Attempt %d: could not open %s: %s", attempt, p, e)
                    time.sleep(self.delay)
        logging.warning("Failed to open any serial port; continuing without serial output")

    def send_count(self, n: int) -> bool:
        """Send an integer count followed by newline. Returns True if send succeeded."""
        if not self._available or not self._ser:
            return False
        try:
            msg = f"{int(n)}\n"
            self._ser.write(msg.encode())
            logging.debug("Sent to serial: %s", msg.strip())
            return True
        except Exception as e:
            logging.warning("Serial write failed: %s", e)
            try:
                self._ser.close()
            except Exception:
                pass
            self._available = False
            self._ser = None
            return False

    def close(self) -> None:
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
            self._available = False


# ---------------------------------------------------------------------------
# Hand counting logic
# ---------------------------------------------------------------------------
class HandCounter:

    def __init__(self, assume_right_hand: bool = True, flipped: bool = True):
        self.assume_right_hand = assume_right_hand
        self.flipped = flipped

    def count(self, hand_landmarks,
              handedness_label: Optional[str] = None) -> int:
        """Return number of fingers extended (0..5).

        hand_landmarks: a mediapipe landmarks object for one hand
        handedness_label: optional string 'Right'/'Left' reported by MediaPipe
        """
        lm = hand_landmarks.landmark
        fingers = 0

        # determine hand label
        if handedness_label:
            hand_label = handedness_label
        else:
            hand_label = 'Right' if self.assume_right_hand else 'Left'

        # Thumb heuristic: compare x of tip and ip. Behavior depends on mirroring.
        thumb_tip = lm[4]
        thumb_ip = lm[3]
        # When image is flipped (mirror), x-axis is mirrored relative to camera coords.
        if hand_label == 'Right':
            if self.flipped:
                # right hand in mirrored image: thumb tip.x < ip.x when open
                if thumb_tip.x < thumb_ip.x:
                    fingers += 1
            else:
                if thumb_tip.x > thumb_ip.x:
                    fingers += 1
        else:  # Left hand
            if self.flipped:
                if thumb_tip.x > thumb_ip.x:
                    fingers += 1
            else:
                if thumb_tip.x < thumb_ip.x:
                    fingers += 1

        # Other fingers: finger tip is above pip (y smaller) when extended
        for tip_id in [8, 12, 16, 20]:
            tip = lm[tip_id]
            pip = lm[tip_id - 2]
            if tip.y < pip.y:
                fingers += 1

        # clamp to valid range
        if fingers < 0:
            fingers = 0
        if fingers > 5:
            fingers = 5
        return fingers


# ---------------------------------------------------------------------------
# Visualization helpers
# ---------------------------------------------------------------------------

def draw_overlay(frame, count: int, avg: int) -> None:
    text = f"Count: {avg}"
    cv2.putText(frame, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_camera_loop(port: Optional[str], baud: int, smooth_frames: int, noserial: bool, camera_index: int):
    # initialize serial client if requested
    serial_client = None
    if not noserial and serial:
        serial_client = SerialClient(port, baud)
    elif not serial and not noserial:
        logging.warning("pyserial not installed; running in noserial mode")
        noserial = True

    # setup video capture
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        logging.error("Could not open camera index %s", camera_index)
        return

    hand_counter = HandCounter(assume_right_hand=True, flipped=True)
    buffer = deque(maxlen=max(1, smooth_frames))
    prev_sent = None

    mp_hands = mp.solutions.hands
    with mp_hands.Hands(min_detection_confidence=0.6, min_tracking_confidence=0.6) as hands:
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    logging.warning("Frame not read from camera; exiting")
                    break
                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = hands.process(rgb)

                detected_count = 0
                handedness_label = None
                if getattr(results, 'multi_hand_landmarks', None):
                    hand_landmarks = results.multi_hand_landmarks[0]
                    try:
                        handedness_label = results.multi_handedness[0].classification[0].label
                    except Exception:
                        handedness_label = None

                    detected_count = hand_counter.count(hand_landmarks, handedness_label)
                    mp.solutions.drawing_utils.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)

                buffer.append(detected_count)
                avg = int(round(sum(buffer) / len(buffer)))

                # overlay
                draw_overlay(frame, detected_count, avg)
                cv2.imshow('Fingers', frame)

                # send to serial if changed
                if serial_client and avg != prev_sent:
                    sent = serial_client.send_count(avg)
                    if sent:
                        prev_sent = avg

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
        finally:
            cap.release()
            cv2.destroyAllWindows()
            if serial_client:
                serial_client.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description='Finger counting with MediaPipe and optional Arduino output')
    p.add_argument('--port', type=str, default=DEFAULT_PORT, help='Serial port (e.g. /dev/ttyACM0)')
    p.add_argument('--baud', type=int, default=DEFAULT_BAUD, help='Serial baud rate')
    p.add_argument('--smooth', type=int, default=DEFAULT_SMOOTH, help='Number of frames to smooth over')
    p.add_argument('--noserial', action='store_true', help='Do not open serial port (visual only)')
    p.add_argument('--camera', type=int, default=DEFAULT_CAMERA, help='Camera device index')
    p.add_argument('--verbose', action='store_true', help='Enable debug logging')
    return p.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format='[%(levelname)s] %(message)s')
    logging.info('Starting finger-counting (noserial=%s) ...', args.noserial)
    run_camera_loop(args.port, args.baud, args.smooth, args.noserial, args.camera)


if __name__ == '__main__':
    main()
