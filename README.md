# streamplify-linux

A Linux client for the **Streamplify DECK** (15-key LCD macro pad, USB `0100:1000`).
There is no official Linux software, so this project reverse-engineers the
protocol and builds a client from scratch.

**Status:** early but usable. Per-key labels, icons and actions, pages,
~5,300 built-in icons, live keys (clock, CPU/RAM/temperature, mic mute
toggle, now-playing album art, command output), press feedback, config
hot-reload and automatic reconnect work.

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
| `label`, `icon`, `icon_color`, `bg`, `fg`, `font_size` | Appearance |
| `run = "cmd"` | Run a shell command |
| `url = "https://…"` | Open in the default browser |
| `hotkey = "ctrl+shift+m"` | Send a key combo (needs `xdotool` on X11 or `wtype` on Wayland) |
| `page = "name"` / `back = true` | Switch page / go back |
| `brightness = 60` or `"+10"` | Set or change brightness |

### Icons

`icon` takes a built-in [Tabler icon](https://tabler.io/icons) or an image file:

```toml
icon = "tabler:brand-github"          # outline icons (~5,300)
icon = "tabler-filled:player-play"    # filled variants (~1,000)
icon = "~/icons/obs.png"              # any png/jpg
icon_color = "#2ecc71"                # Tabler icons default to the key's `fg`
```

Typos get suggestions, e.g. `tabler:microfone` → *did you mean tabler:microphone?*
Icons are bundled; no extra packages needed.

### Live keys

A key can show live data with `widget`. It can still have an action too.

```toml
[pages.main.6]
widget = "clock"
format = "%H:%M"          # any strftime format, "\n" for a second line

[pages.main.7]
widget = "cpu"            # also "ram" and "temp"
style = "graph"           # "graph", "bar" or "text"

[pages.main.10]
widget = "command"
label = "Weather"
command = "curl -s 'wttr.in/?format=%t'"
interval = 600
```

| Widget | Shows | Default interval |
|---|---|---|
| `clock` | Time/date via `format` | 1 s |
| `cpu` | CPU load (%) | 1 s |
| `ram` | Memory in use (%) | 1 s |
| `temp` | CPU temperature; `sensor` picks a hwmon chip by name or a file path | 2 s |
| `command` | First lines of a shell command's output (runs in the background) | 10 s |
| `mic` | Default microphone, red when muted. **Press toggles mute.** Uses `wpctl` (PipeWire) or `pactl` (PulseAudio) | 1 s |
| `nowplaying` | Album art of the current track via `playerctl` (Spotify, browsers, mpv, VLC, …); dimmed with a pause icon when paused. **Press toggles play/pause.** `player = "spotify"` pins one player | 2 s |

Options: `interval`, `format`, `style`, `color`, `command`, `sensor`, `player`.
If a `mic` or `nowplaying` key has its own action, that action runs instead of the built-in toggle.
Widgets only run while their page is visible, and a key is only re-sent
to the deck when its picture actually changes.

See [`src/streamplify/example.toml`](src/streamplify/example.toml) for a full example.

## Roadmap

- [x] Driver, pages, actions, config hot-reload, reconnect
- [ ] Animated GIF keys
- [ ] Canvas mode: images and widgets spanning several keys
- [x] Live keys: clock, CPU/RAM/temperature, command output
- [x] Built-in icons, mic mute toggle, now-playing album art
- [ ] More live keys (Home Assistant, volume, …)
- [ ] Long-press / double-tap, transitions, idle dimming, mini-games

## Protocol

See [docs/PROTOCOL.md](docs/PROTOCOL.md).

## License

MIT
