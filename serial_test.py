import argparse
import sys
import time
import serial
import serial.tools.list_ports
from serial.serialutil import SerialException


def list_ports():
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return
    for p in ports:
        print(f"{p.device}\t{p.description}")


def open_port(port, baud=9600, retries=3, delay=1.0, timeout=1.0):
    """Attempt to open `port` with retries. Returns a serial.Serial or None."""
    for attempt in range(1, retries + 1):
        try:
            ser = serial.Serial(port, baud, timeout=timeout)
            # small delay to let some devices (Arduino) reset
            time.sleep(0.2)
            print(f"Opened {port} at {baud} baud")
            return ser
        except SerialException as e:
            print(f"Attempt {attempt}/{retries} — could not open {port}: {e}")
            time.sleep(delay)
    print(f"Failed to open port {port} after {retries} attempts.")
    return None


def send_and_read_once(ser, msg, read_timeout=1.0):
    try:
        ser.reset_input_buffer()
    except Exception:
        pass
    try:
        ser.write(msg.encode())
        ser.flush()
        print(f"Sent: {msg!r}")
    except Exception as e:
        print(f"Write failed: {e}")
        return

    # try reading any immediate response
    t0 = time.time()
    buf = b""
    while time.time() - t0 < read_timeout:
        try:
            chunk = ser.read(ser.in_waiting or 1)
        except Exception as e:
            print(f"Read error: {e}")
            break
        if chunk:
            buf += chunk
        else:
            time.sleep(0.01)
    if buf:
        try:
            print("Received:", buf.decode(errors='replace'))
        except Exception:
            print("Received (raw):", buf)
    else:
        print("No response received (within timeout).")


def echo_mode(ser, duration=5):
    print(f"Reading for {duration} seconds (hit Ctrl-C to stop)...")
    t0 = time.time()
    try:
        while time.time() - t0 < duration:
            try:
                chunk = ser.read(ser.in_waiting or 1)
            except Exception as e:
                print(f"Read error: {e}")
                break
            if chunk:
                sys.stdout.write(chunk.decode(errors='replace'))
                sys.stdout.flush()
            else:
                time.sleep(0.01)
    except KeyboardInterrupt:
        print('\nStopped by user')


def interactive_mode(ser):
    print("Interactive mode. Type a line and press Enter to send. Ctrl-D or Ctrl-C to exit.")
    try:
        while True:
            try:
                line = input('> ')
            except EOFError:
                break
            if not line:
                continue
            send_and_read_once(ser, line + '\n', read_timeout=1.0)
    except KeyboardInterrupt:
        print('\nExiting interactive mode')


def main():
    p = argparse.ArgumentParser(description='Serial port test utility')
    p.add_argument('--list', action='store_true', help='List available serial ports')
    p.add_argument('--port', type=str, help='Serial device path to open (e.g., /dev/ttyACM0)')
    p.add_argument('--baud', type=int, default=9600, help='Baud rate')
    p.add_argument('--send', type=str, help='Send this message and exit')
    p.add_argument('--echo', type=float, help='Read/echo for N seconds and exit')
    p.add_argument('--interactive', action='store_true', help='Open port and interactively send lines')
    p.add_argument('--retries', type=int, default=3, help='Open retries')
    p.add_argument('--delay', type=float, default=1.0, help='Delay between open retries')
    args = p.parse_args()

    if args.list:
        list_ports()
        return

    if not args.port:
        print("No port specified. Use --list to see available ports or pass --port /dev/ttyXXX")
        return

    ser = open_port(args.port, baud=args.baud, retries=args.retries, delay=args.delay)
    if not ser:
        print("Port open failed. Use 'lsof' or 'fuser' on the device to see what's holding it, or unplug/replug the device.")
        return

    try:
        if args.send:
            send_and_read_once(ser, args.send, read_timeout=1.0)
            return
        if args.echo:
            echo_mode(ser, duration=args.echo)
            return
        if args.interactive:
            interactive_mode(ser)
            return

        # default behaviour: send a simple probe and read
        send_and_read_once(ser, 'PING\n', read_timeout=1.0)
    finally:
        try:
            ser.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()

