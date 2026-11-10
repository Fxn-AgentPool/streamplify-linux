# streamplify-linux

Linux client for the Streamplify DECK (15-key LCD macro pad, USB `0100:1000`,
Mirabox/Ajazz "Stream Dock" chipset). Python package `streamplify`, CLI `streamplify`.

## Develop
- Env: `uv venv && uv pip install -e '.[dev]'` (project-local `.venv`)
- Test: `.venv/bin/pytest -q` (no hardware needed; uses a fake deck)
- Lint: `.venv/bin/ruff check .` (rules pinned in pyproject; CI runs both on 3.11–3.13)
- Hardware self-test: `.venv/bin/streamplify selftest`
- Workflow: feature branch → PR → CI green → user checks on the real deck → squash-merge.
- Release: bump `version` in pyproject.toml **and** `__version__` in `src/streamplify/__init__.py`,
  tag `vX.Y.Z`, push the tag → Release workflow builds wheel + sdist into a GitHub release.

## Architecture (src/streamplify)
- `device.py` – HID transport (512-byte reports, `CRT\0\0` commands), key-number translation.
- `config.py` – TOML parsing/validation; keys addressed in reading order (1 = top-left).
- `render.py` / `icons.py` – key images; bundled Tabler icon font (`tools/update_tabler.py` regenerates).
- `controller.py` – pages, actions, press handling, screensaver; uploads only keys whose JPEG changed,
  one `STP` refresh per batch.
- `widgets.py` – live keys; slow sources use `AsyncWidget` (worker thread, one fetch at a time).
- `cli.py` – service loop (reconnect, config hot-reload, graceful stop), `usbreset.py` – USB reset.
- Protocol facts and measurements: `docs/PROTOCOL.md`.

## Gotchas (hard-won)
- **Never interrupt an image upload.** The deck then silently drops all button presses (sometimes the
  kernel floods `input irq status -75`). Stop the service with SIGTERM (it finishes the current
  operation); never SIGKILL it mid-run. Recovery: `streamplify reset` (or `sudo usbreset 0100:1000`).
  The service also resets the deck on start.
- Image key indices count rows bottom-up, input indices top-down (`input_to_key`). Images are
  100×100 JPEG rotated 180°.
- Budget ≈ 45 key uploads/s; one key ≈ 15 fps; a full 15-key redraw ≈ 2 fps.
- Hotkey key names are X keysyms and case-sensitive (`F13`, `XF86AudioMute`); single letters are lowercased.
- `gh pr edit` is broken in gh 2.46 (Projects classic deprecation) → `gh api -X PATCH repos/.../pulls/N -F body=@file`.
- Testing without hardware: PipeWire virtual mic (mute only applies while something records:
  keep `pw-record --target test-mic /dev/null` running), mpv + mpv-mpris for MPRIS, Xvfb + xdotool + xev
  for hotkeys.

## Status
- v0.2.0 released 2026-11-10 (service, icons, live keys, mic, now playing, hotkeys, auto-reset, screensaver).
- User runs Hyprland; README has a Hyprland section.
- Open ideas: multi-key canvas widgets, gestures (long-press/double-tap/shift), GIF keys,
  ydotool fallback for GNOME/KDE Wayland, desktop-idle integration (hypridle).
