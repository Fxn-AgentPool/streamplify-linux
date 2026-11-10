"""Low-level driver for the Streamplify DECK (USB 0100:1000).

The deck uses a Mirabox/Ajazz "Stream Dock" style chipset: 512-byte HID
reports with no report IDs, commands prefixed with ``CRT\\0\\0``.
See docs/PROTOCOL.md for the protocol notes.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import hid
from PIL import Image

VID, PID = 0x0100, 0x1000
PACKET = 512
ROWS, COLS = 3, 5
KEY_COUNT = ROWS * COLS
KEY_SIZE = 100          # pixels, square
KEY_ROTATION = 180      # images must be rotated before upload


# --- key numbering -----------------------------------------------------------
# Image ("key") indices run bottom-up: 1-5 = bottom row, 11-15 = top row.
# Input event indices run top-down: 1-5 = top row. Both are 1-based.

def key_at(row: int, col: int) -> int:
    """Key index for a physical position (row 0 = top, col 0 = left)."""
    return (ROWS - 1 - row) * COLS + col + 1


def pos_of(key: int) -> tuple[int, int]:
    """Physical (row, col) of a key index, row 0 = top."""
    k = key - 1
    return ROWS - 1 - k // COLS, k % COLS


def input_to_key(i: int) -> int:
    """Translate an input-report key number to the image key index."""
    if not 1 <= i <= KEY_COUNT:
        return i
    row, col = divmod(i - 1, COLS)
    return key_at(row, col)


@dataclass(frozen=True)
class KeyEvent:
    key: int        # image key index (1..15)
    pressed: bool


class Deck:
    def __init__(self, vid: int = VID, pid: int = PID):
        self._dev = hid.Device(vid, pid)

    def close(self) -> None:
        self._dev.close()

    def __enter__(self) -> "Deck":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- transport ---
    def _write(self, data: bytes) -> None:
        # Leading 0 = "no report ID" for hidapi.
        self._dev.write(b"\x00" + bytes(data).ljust(PACKET, b"\x00"))

    def _cmd(self, payload: bytes) -> None:
        self._write(b"CRT\x00\x00" + payload)

    # --- info ---
    def firmware(self) -> str:
        raw = self._dev.get_feature_report(0, PACKET + 1)[1:]
        return raw.split(b"\x00")[0].decode(errors="replace")

    @property
    def serial(self) -> str:
        return self._dev.serial

    # --- display control ---
    def wake(self) -> None:
        self._cmd(b"DIS")

    def brightness(self, percent: int) -> None:
        self._cmd(b"LIG\x00\x00" + bytes([max(0, min(100, int(percent)))]))

    def clear(self, key: int | None = None) -> None:
        """Clear one key, or all keys when ``key`` is None."""
        self._cmd(b"CLE\x00\x00\x00" + bytes([0xFF if key is None else key]))

    def refresh(self) -> None:
        """Commit uploaded images to the screen (~40 ms on the device)."""
        self._cmd(b"STP")

    # --- images ---
    def upload_jpeg(self, key: int, jpeg: bytes) -> None:
        """Upload a pre-encoded, pre-rotated JPEG. Call refresh() afterwards."""
        self._cmd(b"BAT" + len(jpeg).to_bytes(4, "big") + bytes([key]))
        for i in range(0, len(jpeg), PACKET):
            self._write(jpeg[i:i + PACKET])

    def set_key_image(self, key: int, img: Image.Image, *, refresh: bool = True) -> None:
        self.upload_jpeg(key, encode_key_image(img))
        if refresh:
            self.refresh()

    # --- input ---
    def read_event(self, timeout_ms: int = 1000) -> KeyEvent | None:
        r = self._dev.read(PACKET, timeout_ms)
        if r and r[:3] == b"ACK" and len(r) > 10:
            return KeyEvent(input_to_key(r[9]), bool(r[10]))
        return None


def encode_key_image(img: Image.Image, quality: int = 85) -> bytes:
    img = img.convert("RGB")
    if img.size != (KEY_SIZE, KEY_SIZE):
        img = img.resize((KEY_SIZE, KEY_SIZE), Image.LANCZOS)
    img = img.rotate(KEY_ROTATION)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()
