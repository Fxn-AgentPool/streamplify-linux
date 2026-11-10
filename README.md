# streamplify-linux

A Linux client for the **Streamplify DECK** (15-key LCD macro pad, USB `0100:1000`).
There is no official Linux software, so this project reverse-engineers the
protocol and builds a client from scratch.

**Status:** early but usable. Per-key labels, icons and actions, pages,
press feedback, config hot-reload and automatic reconnect work. GIFs and
multi-key canvas are next.

## Install

```sh
sudo apt install libhidapi-hidraw0            # Debian/Ubuntu
sudo cp udev/70-streamplify-deck.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
pipx install git+https://github.com/Fxn-AgentPool/streamplify-linux
```

Replug the deck after installing the udev rule.

## Use

```sh
streamplify init        # writes ~/.config/streamplify/config.toml
streamplify check       # validate the config
streamplify run         # run in the foreground
streamplify selftest    # numbers every key, highlights presses
```

Run at login as a systemd user service:

```sh
mkdir -p ~/.config/systemd/user
cp systemd/streamplify.service ~/.config/systemd/user/
systemctl --user enable --now streamplify
```

## Config

Keys are numbered in reading order, 1 = top-left, 15 = bottom-right.
The file is reloaded automatically when saved.

```toml
brightness = 80

[pages.main.1]
label = "Terminal"
icon = "~/icons/terminal.png"
run = "kitty"

[pages.main.5]
label = "Media"
bg = "#8e44ad"
page = "media"

[pages.media.11]
label = "Back"
back = true
```

| Field | Meaning |
|---|---|
| `label`, `icon`, `bg`, `fg`, `font_size` | Appearance |
| `run = "cmd"` | Run a shell command |
| `url = "https://…"` | Open in the default browser |
| `hotkey = "ctrl+shift+m"` | Send a key combo (needs `xdotool` on X11 or `wtype` on Wayland) |
| `page = "name"` / `back = true` | Switch page / go back |
| `brightness = 60` or `"+10"` | Set or change brightness |

See [`src/streamplify/example.toml`](src/streamplify/example.toml) for a full example.

## Roadmap

- [x] Driver, pages, actions, config hot-reload, reconnect
- [ ] Animated GIF keys
- [ ] Canvas mode: images and widgets spanning several keys
- [ ] Live keys (system stats, mic mute, Home Assistant, …)
- [ ] Long-press / double-tap, transitions, idle dimming, mini-games

## Protocol

See [docs/PROTOCOL.md](docs/PROTOCOL.md).

## License

MIT
