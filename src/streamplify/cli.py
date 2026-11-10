"""`streamplify` command line: run the service, check config, self-test."""
from __future__ import annotations

import argparse
import logging
import shutil
import signal
import sys
import time
from importlib import resources
from pathlib import Path

from . import config as cfgmod
from .controller import Controller

log = logging.getLogger("streamplify")

RECONNECT_S = 2.0
POLL_MS = 200
CONFIG_CHECK_S = 1.0


class _Stop(Exception):
    pass


def _mtime(path: Path | None) -> float | None:
    try:
        return path.stat().st_mtime if path else None
    except OSError:
        return None


def run(config_path: Path) -> int:
    from .device import Deck  # imported late so `check` works without hidapi

    cfg = cfgmod.load(config_path)
    mtime = _mtime(cfg.path)

    def _stop(*_):
        raise _Stop

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    ctl: Controller | None = None
    deck = None
    waiting_logged = False
    try:
        while True:
            if deck is None:
                try:
                    deck = Deck()
                except Exception as e:      # hid raises HIDException / OSError variants
                    if not waiting_logged:
                        log.info("waiting for deck (%s)", e)
                        waiting_logged = True
                    time.sleep(RECONNECT_S)
                    continue
                waiting_logged = False
                log.info("deck connected, firmware %s", deck.firmware())
                if ctl is None:
                    ctl = Controller(deck, cfg)
                else:
                    ctl.deck = deck
                ctl.start()
                last_check = time.monotonic()

            try:
                ev = deck.read_event(POLL_MS)
                if ev is not None:
                    ctl.handle(ev)
            except _Stop:
                raise
            except Exception as e:
                log.warning("deck lost (%s); reconnecting", e)
                try:
                    deck.close()
                except Exception:
                    pass
                deck = None
                continue

            if time.monotonic() - last_check >= CONFIG_CHECK_S:
                last_check = time.monotonic()
                m = _mtime(cfg.path)
                if m != mtime:
                    mtime = m
                    try:
                        cfg = cfgmod.load(config_path)
                        ctl.reload(cfg)
                        log.info("config reloaded")
                    except Exception as e:
                        log.error("config not reloaded: %s", e)
    except _Stop:
        log.info("stopping")
    finally:
        if deck is not None:
            try:
                deck.clear()
                deck.refresh()
                deck.close()
            except Exception:
                pass
    return 0


def check(config_path: Path) -> int:
    try:
        cfg = cfgmod.load(config_path)
    except (OSError, cfgmod.ConfigError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    missing = [str(s.icon) for p in cfg.pages.values() for s in p.keys.values()
               if s.icon and not s.icon.exists()]
    for m in missing:
        print(f"warning: icon not found: {m}", file=sys.stderr)
    n = sum(len(p.keys) for p in cfg.pages.values())
    print(f"ok: {len(cfg.pages)} page(s), {n} key(s), start page '{cfg.start_page}'")
    return 0


def init(config_path: Path) -> int:
    if config_path.exists():
        print(f"{config_path} already exists", file=sys.stderr)
        return 1
    config_path.parent.mkdir(parents=True, exist_ok=True)
    src = resources.files("streamplify").joinpath("example.toml")
    with resources.as_file(src) as p:
        shutil.copy(p, config_path)
    print(f"wrote {config_path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="streamplify", description="Streamplify DECK client")
    ap.add_argument("-c", "--config", type=Path, default=cfgmod.DEFAULT_PATH)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("run", help="run the service (default)")
    sub.add_parser("check", help="validate the config file")
    sub.add_parser("init", help="write an example config")
    st = sub.add_parser("selftest", help="number every key and highlight presses")
    st.add_argument("seconds", nargs="?", default="30")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    cmd = args.cmd or "run"
    if cmd == "check":
        return check(args.config)
    if cmd == "init":
        return init(args.config)
    if cmd == "selftest":
        from . import selftest
        sys.argv = ["selftest", args.seconds]
        selftest.main()
        return 0
    return run(args.config)


if __name__ == "__main__":
    sys.exit(main())
