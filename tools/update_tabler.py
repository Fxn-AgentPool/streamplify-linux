"""Download a Tabler Icons webfont release and regenerate the bundled icon data.

    python tools/update_tabler.py 3.50.0

Writes src/streamplify/icons/{tabler-icons.ttf, tabler-icons-filled.ttf,
tabler.json, LICENSE-tabler}.
"""
import json
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src" / "streamplify" / "icons"
FILES = {
    "tabler-icons.ttf": "dist/fonts/tabler-icons.ttf",
    "tabler-icons-filled.ttf": "dist/fonts/tabler-icons-filled.ttf",
    "outline.css": "dist/tabler-icons.min.css",
    "filled.css": "dist/tabler-icons-filled.min.css",
    "LICENSE-tabler": "LICENSE",
}
RULE = re.compile(r'([^{}]+)\{content:"\\([0-9a-fA-F]+)"')


def parse_css(css: str) -> dict[str, int]:
    names = {}
    for selectors, cp in RULE.findall(css):
        for sel in selectors.split(","):
            m = re.fullmatch(r"\s*\.ti-([a-z0-9-]+):before\s*", sel)
            if m:
                names[m.group(1)] = int(cp, 16)
    return names


def main(version: str) -> None:
    base = f"https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@{version}/"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for local, remote in FILES.items():
            urllib.request.urlretrieve(base + remote, tmp / local)
        mapping = {
            "version": version,
            "outline": parse_css((tmp / "outline.css").read_text()),
            "filled": parse_css((tmp / "filled.css").read_text()),
        }
        if len(mapping["outline"]) < 1000:
            sys.exit(f"suspiciously few icons parsed ({len(mapping['outline'])}); CSS format changed?")
        OUT.mkdir(parents=True, exist_ok=True)
        for name in ("tabler-icons.ttf", "tabler-icons-filled.ttf", "LICENSE-tabler"):
            (OUT / name).write_bytes((tmp / name).read_bytes())
        (OUT / "tabler.json").write_text(json.dumps(mapping, separators=(",", ":"), sort_keys=True))
    print(f"tabler {version}: {len(mapping['outline'])} outline, {len(mapping['filled'])} filled icons")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "3.50.0")
