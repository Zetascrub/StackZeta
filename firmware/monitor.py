#!/usr/bin/env python3
"""Read the Linux USB serial console without explicitly toggling DTR or RTS."""

import argparse
import math
import os
import select
import sys
import termios
import time


def capture(port, seconds):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        settings = termios.tcgetattr(fd)
        settings[0] = 0
        settings[1] = 0
        settings[2] &= ~(termios.PARENB | termios.CSTOPB | termios.CSIZE | termios.HUPCL)
        settings[2] |= termios.CS8 | termios.CLOCAL | termios.CREAD
        settings[3] = 0
        settings[4] = settings[5] = termios.B115200
        settings[6][termios.VMIN] = 0
        settings[6][termios.VTIME] = 0
        # Keep pending boot output. Leave HUPCL disabled on close so the driver
        # does not hang up the port; do not issue modem-control ioctls.
        termios.tcsetattr(fd, termios.TCSANOW, settings)
        deadline = time.monotonic() + seconds
        while (remaining := deadline - time.monotonic()) > 0:
            if not select.select([fd], [], [], min(remaining, 0.5))[0]:
                continue
            data = os.read(fd, 65536)
            if not data:
                raise OSError("USB serial device disconnected")
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--seconds", type=float, default=30, help="capture duration (default: 30)")
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error("--seconds must be a finite positive number")
    print(f"Reading {args.port} for {args.seconds:g} seconds; Ctrl-C to stop.", file=sys.stderr)
    try:
        capture(args.port, args.seconds)
    except KeyboardInterrupt:
        return 130
    except (OSError, termios.error) as error:
        print(f"Serial capture failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
