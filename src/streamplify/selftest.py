"""Hardware self-test: numbers every key, highlights keys while pressed.

    python -m streamplify.selftest [seconds]
"""
import sys
import time

from PIL import Image, ImageDraw, ImageFont

from .device import Deck, KEY_COUNT, KEY_SIZE

COLORS = ["#c0392b", "#d35400", "#f39c12", "#27ae60", "#16a085", "#2980b9", "#8e44ad", "#2c3e50"]


def label(text: str, bg: str) -> Image.Image:
    im = Image.new("RGB", (KEY_SIZE, KEY_SIZE), bg)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 48)
    except OSError:
        font = ImageFont.load_default()
    ImageDraw.Draw(im).text((KEY_SIZE // 2, KEY_SIZE // 2), text, fill="white", font=font, anchor="mm")
    return im


def main() -> None:
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    with Deck() as deck:
        print("firmware:", deck.firmware())
        deck.wake()
        deck.brightness(100)
        deck.clear()
        for k in range(1, KEY_COUNT + 1):
            deck.set_key_image(k, label(str(k), COLORS[k % len(COLORS)]), refresh=False)
        deck.refresh()
        print(f"press keys for {secs}s (each should turn white while held)")
        end = time.time() + secs
        while time.time() < end:
            ev = deck.read_event(500)
            if ev is None:
                continue
            print(f"key {ev.key} {'down' if ev.pressed else 'up'}", flush=True)
            bg = "#ffffff" if ev.pressed else COLORS[ev.key % len(COLORS)]
            deck.set_key_image(ev.key, label(str(ev.key), bg))


if __name__ == "__main__":
    main()
