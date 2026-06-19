#!/usr/bin/env python3
"""Read ReSpeaker USB Mic Array DOA/VAD through the vendor tuning endpoint."""

from __future__ import annotations

import argparse
import json
import struct
from typing import Any


VID = 0x2886
PID = 0x0018
TIMEOUT_MS = 100_000

PARAMS = {
    "VOICEACTIVITY": (19, 32, "int"),
    "DOAANGLE": (21, 0, "int"),
}


def read_param(dev: Any, name: str) -> int | float:
    import usb.util

    param_id, offset, param_type = PARAMS[name]
    command = 0x80 | offset
    if param_type == "int":
        command |= 0x40

    response = dev.ctrl_transfer(
        usb.util.CTRL_IN | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE,
        0,
        command,
        param_id,
        8,
        TIMEOUT_MS,
    )
    value, exponent = struct.unpack("ii", bytes(response))
    if param_type == "int":
        return value
    return value * (2.0**exponent)


def read_status(vid: int, pid: int) -> dict[str, Any]:
    try:
        import usb.core
        import usb.util
    except Exception as err:
        return {
            "device_found": False,
            "direction": None,
            "voice_activity": None,
            "source": "respeaker_usb_tuning",
            "error": f"{type(err).__name__}: {err}",
        }

    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if dev is None:
        return {
            "device_found": False,
            "direction": None,
            "voice_activity": None,
            "source": "respeaker_usb_tuning",
            "error": f"USB device {vid:04x}:{pid:04x} not found",
        }

    try:
        return {
            "device_found": True,
            "direction": int(read_param(dev, "DOAANGLE")),
            "voice_activity": int(read_param(dev, "VOICEACTIVITY")),
            "source": "respeaker_usb_tuning",
            "error": None,
        }
    except Exception as err:
        return {
            "device_found": True,
            "direction": None,
            "voice_activity": None,
            "source": "respeaker_usb_tuning",
            "error": f"{type(err).__name__}: {err}",
        }
    finally:
        usb.util.dispose_resources(dev)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vid", type=lambda value: int(value, 0), default=VID)
    parser.add_argument("--pid", type=lambda value: int(value, 0), default=PID)
    parser.add_argument("--value-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    status = read_status(args.vid, args.pid)
    if args.value_only:
        print(status["direction"] if status["direction"] is not None else "unknown")
    else:
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
