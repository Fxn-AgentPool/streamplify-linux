# streamplify-linux

A Linux client for the **Streamplify DECK** (15-key LCD macro pad, USB `0100:1000`).
There is no official Linux software, so this project reverse-engineers the
protocol and builds a client from scratch.

**Status:** early. The low-level driver works (images, brightness, button
events). The background service and config are in progress.

## Setup

```sh
sudo cp udev/70-streamplify-deck.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
python -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m streamplify.selftest      # numbers every key, highlights presses
```

Needs `libhidapi-hidraw0` (Debian/Ubuntu: `sudo apt install libhidapi-hidraw0`).

## Roadmap

1. Background service + TOML config: per-key icons, labels, actions, pages
2. Animated GIF keys
3. Canvas mode: images and widgets spanning several keys
4. Live keys (system stats, mic mute, Home Assistant, …)
5. Extras: long-press/double-tap, transitions, mini-games, idle dimming

## Protocol

See [docs/PROTOCOL.md](docs/PROTOCOL.md).

## License

MIT
