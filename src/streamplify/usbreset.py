"""USB-level reset of the deck (the software equivalent of replugging it).

Needed because an interrupted image upload leaves the deck's firmware out of
sync: the screen keeps working but button presses never arrive (the kernel
logs "input irq status -75"). See docs/PROTOCOL.md.

Requires write access to the deck's /dev/bus/usb node; the bundled udev rule
grants that to the logged-in user.
"""
from __future__ import annotations

import fcntl
import logging
import os
import time
from pathlib import Path

from .device import PID, VID

log = logging.getLogger(__name__)

USBDEVFS_RESET = (ord("U") << 8) | 20     # _IO('U', 20)
SYSFS = Path("/sys/bus/usb/devices")


class ResetError(OSError):
    pass


def find_device_nodes(vid: int = VID, pid: int = PID, sysfs: Path = SYSFS) -> list[Path]:
    """/dev/bus/usb/BBB/DDD for every attached deck."""
    nodes = []
    for dev in sorted(sysfs.iterdir()) if sysfs.exists() else []:
        try:
            if (int((dev / "idVendor").read_text(), 16) == vid
                    and int((dev / "idProduct").read_text(), 16) == pid):
                bus = int((dev / "busnum").read_text())
                num = int((dev / "devnum").read_text())
                nodes.append(Path(f"/dev/bus/usb/{bus:03d}/{num:03d}"))
        except (OSError, ValueError):
            continue
    return nodes


def reset(node: Path) -> None:
    try:
        fd = os.open(node, os.O_WRONLY)
    except PermissionError as e:
        raise ResetError(
            f"no permission to reset {node}; install udev/70-streamplify-deck.rules and replug the deck"
        ) from e
    try:
        fcntl.ioctl(fd, USBDEVFS_RESET, 0)
    finally:
        os.close(fd)


def reset_all(settle_s: float = 1.0) -> int:
    """Reset every attached deck; returns how many were reset."""
    n = 0
    for node in find_device_nodes():
        try:
            reset(node)
            n += 1
            log.info("reset deck at %s", node)
        except ResetError as e:
            log.warning("%s", e)
        except OSError as e:
            log.warning("could not reset %s: %s", node, e)
    if n:
        time.sleep(settle_s)      # let the kernel re-create the hidraw node
    return n
