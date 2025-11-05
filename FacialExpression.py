import argparse
import logging
import time
import math
from collections import deque
from typing import Optional, Tuple

import cv2
import mediapipe as mp

try:
    import serial
    import serial.tools.list_ports
    from serial.serialutil import SerialException
except Exception:
    serial = None


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_PORT = "/dev/ttyACM0"
DEFAULT_BAUD = 9600
DEFAULT_SMOOTH = 6
DEFAULT_CAMERA = 0

# FaceMesh landmark indices used for mouth
L_IDX = 61   # left mouth corner
R_IDX = 291  # right mouth corner
U_IDX = 13   # upper inner lip
B_IDX = 14   # lower inner lip


# ---------------------------------------------------------------------------
# Serial helper
# ---------------------------------------------------------------------------
class SerialClient:
    """Simple serial wrapper that optionally opens a port and sends text lines."""

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
            logging.info("Serial disabled (no port provided or pyserial missing)")

    def open(self) -> None:
        candidates = [self.port] if self.port else [p.device for p in serial.tools.list_ports.comports() if ('ACM' in p.device or 'USB' in p.device)]
        for p in candidates:
            for attempt in range(1, self.retries + 1):
                try:
                    self._ser = serial.Serial(p, self.baud, timeout=1)
                    time.sleep(0.1)
                    self._available = True
                    logging.info("Opened serial port %s at %d", p, self.baud)
                    return
                except SerialException as e:
                    logging.debug("Attempt %d: could not open %s: %s", attempt, p, e)
                    time.sleep(self.delay)
        logging.warning("Failed to open serial port; continuing without serial output")

    def send_signal(self, label: str) -> bool:
        """Map a textual label to an integer signal and send it over serial.

        Mapping:
          - 'neutral' -> 2
          - 'smile'   -> 3
          - 'frown'   -> 1
        Unknown labels are ignored (no send) and return False.
        """
        if not self._available or not self._ser:
            return False

        mapping = {
            'neutral': 2,
            'smile': 3,
            'frown': 1,
        }
        key = (label or '').strip().lower()
        if key not in mapping:
            logging.debug("send_signal: unknown label '%s' -> not sending", label)
            return False

        val = mapping[key]
        try:
            msg = f"{val}\n".encode()
            self._ser.write(msg)
            logging.debug("Serial sent signal: %s -> %d", key, val)
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
# Smile / frown detector
# ---------------------------------------------------------------------------
class SmileDetector:
    """Encapsulates the mouth-based heuristic used to detect smile / frown / neutral.

    The detector computes normalized mouth width (mouth_w / face_w) and corner offset
    (corner_mean_y - mouth_center_y) normalized by face height. A small ring buffer
    smooths each value before thresholding.
    """

    def __init__(self, buf_size: int = DEFAULT_SMOOTH,
                 smile_thresh: float = 0.32,
                 frown_thresh: float = 0.22,
                 corner_margin: float = 0.015):
        self.mouth_buf = deque(maxlen=max(1, buf_size))
        self.corner_buf = deque(maxlen=max(1, buf_size))
        self.smile_thresh = smile_thresh
        self.frown_thresh = frown_thresh
        self.corner_margin = corner_margin

    def compute(self, face_landmarks, img_w: int, img_h: int) -> Tuple[str, float, float, float]:
        """Compute label and diagnostics.

        Returns: (label, mouth_w_norm, mouth_w, mouth_h)
        label is one of 'smile', 'frown', 'neutral'
        """
        lms = face_landmarks.landmark

        # Convert to pixel coords
        left_x, left_y = lms[L_IDX].x * img_w, lms[L_IDX].y * img_h
        right_x, right_y = lms[R_IDX].x * img_w, lms[R_IDX].y * img_h
        top_x, top_y = lms[U_IDX].x * img_w, lms[U_IDX].y * img_h
        bottom_x, bottom_y = lms[B_IDX].x * img_w, lms[B_IDX].y * img_h

        mouth_w = math.hypot(right_x - left_x, right_y - left_y)
        mouth_h = math.hypot(bottom_x - top_x, bottom_y - top_y) + 1e-6
        ratio = mouth_w / mouth_h

        # face bbox for normalization
        xs = [p.x * img_w for p in lms]
        ys = [p.y * img_h for p in lms]
        face_w = max(xs) - min(xs) + 1e-6
        face_h = max(ys) - min(ys) + 1e-6

        mouth_w_norm = mouth_w / face_w

        corners_mean_y = (left_y + right_y) / 2.0
        mouth_center_y = (top_y + bottom_y) / 2.0
        corner_diff = corners_mean_y - mouth_center_y
        corner_diff_norm = corner_diff / face_h

        # update buffers and compute averages
        self.mouth_buf.append(mouth_w_norm)
        self.corner_buf.append(corner_diff_norm)
        avg_w = sum(self.mouth_buf) / len(self.mouth_buf)
        avg_corner = sum(self.corner_buf) / len(self.corner_buf)

        # heuristics
        if avg_w >= self.smile_thresh and avg_corner < -self.corner_margin:
            label = 'smile'
        elif avg_w <= self.frown_thresh and avg_corner > self.corner_margin:
            label = 'frown'
        else:
            label = 'neutral'

        return label, mouth_w_norm, mouth_w, mouth_h


# ---------------------------------------------------------------------------
# Visualization helper
# ---------------------------------------------------------------------------
def draw_label(frame, label: str, mouth_w_norm: float) -> None:
    txt = f"{label} ({mouth_w_norm:.2f})"
    cv2.putText(frame, txt, (30, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run(port: Optional[str], baud: int, smooth: int, noserial: bool, camera: int, verbose: bool):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format='[%(levelname)s] %(message)s')

    serial_client = None
    if not noserial:
        if serial is None:
            logging.warning('pyserial not available; running in noserial mode')
            noserial = True
        else:
            serial_client = SerialClient(port, baud)

    cap = cv2.VideoCapture(camera)
    if not cap.isOpened():
        logging.error('Could not open camera index %s', camera)
        return

    detector = SmileDetector(buf_size=smooth)

    mp_face_mesh = mp.solutions.face_mesh
    with mp_face_mesh.FaceMesh(min_detection_confidence=0.7, min_tracking_confidence=0.7) as face_mesh:
        prev_label = None
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    logging.warning('Frame not read; exiting')
                    break
                frame = cv2.flip(frame, 1)
                h, w = frame.shape[:2]

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(rgb)

                label_text = ''
                faces = getattr(results, 'multi_face_landmarks', None)
                if faces:
                    # process first face only
                    face_landmarks = faces[0]

                    # draw mouth corner markers
                    left_m = face_landmarks.landmark[L_IDX]
                    right_m = face_landmarks.landmark[R_IDX]
                    cv2.circle(frame, (int(left_m.x * w), int(left_m.y * h)), 5, (255, 0, 0), -1)
                    cv2.circle(frame, (int(right_m.x * w), int(right_m.y * h)), 5, (255, 0, 0), -1)

                    label, mw_norm, mw, mh = detector.compute(face_landmarks, w, h)
                    label_text = f"{label} ({mw_norm:.2f})"

                    # send over serial if available and changed
                    if serial_client and label != prev_label:
                        sent = serial_client.send_signal(label)
                        if sent:
                            prev_label = label

                # overlay and show
                if label_text:
                    draw_label(frame, label, mw_norm)
                cv2.imshow('Webcam Feed', frame)

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
        finally:
            try:
                cap.release()
            except Exception:
                pass
            cv2.destroyAllWindows()
            if serial_client:
                serial_client.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description='Face expression -> Arduino (smile/neutral/frown)')
    p.add_argument('--port', type=str, default=DEFAULT_PORT, help='Serial port (e.g. /dev/ttyACM0)')
    p.add_argument('--baud', type=int, default=DEFAULT_BAUD, help='Serial baud rate')
    p.add_argument('--smooth', type=int, default=DEFAULT_SMOOTH, help='Number of frames to smooth over')
    p.add_argument('--noserial', action='store_true', help='Do not open serial port (visual only)')
    p.add_argument('--camera', type=int, default=DEFAULT_CAMERA, help='Camera device index')
    p.add_argument('--verbose', action='store_true', help='Enable debug logging')
    return p.parse_args()


if __name__ == '__main__':
    args = parse_args()
    run(args.port, args.baud, args.smooth, args.noserial, args.camera, args.verbose)
