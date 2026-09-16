#!/usr/bin/env python3
"""Refresh flotte/styles/themes/ from the upstream base16 catalogue.

Schemes are copied in verbatim. The only editorial rule is readability: a scheme
whose own foreground on its own background falls below WCAG AA is skipped,
because base.tcss has no way to rescue it.

    uv run python scripts/sync_themes.py
"""
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flotte.theme import MIN_TEXT_CONTRAST, THEMES_DIR, contrast_ratio, read_scheme  # noqa: E402

LISTING = "https://api.github.com/repos/tinted-theming/schemes/contents/base16?per_page=1000"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def main() -> int:
    entries = json.loads(fetch(LISTING))
    schemes = {e["name"]: e["download_url"] for e in entries if e["name"].endswith(".yaml")}
    print(f"upstream schemes: {len(schemes)}")

    staging = THEMES_DIR.parent / ".themes-sync"
    staging.mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(
            lambda item: (staging / item[0]).write_bytes(fetch(item[1])),
            schemes.items(),
        ))

    kept, skipped = [], []
    for path in sorted(staging.glob("*.yaml")):
        scheme = read_scheme(path)
        ratio = contrast_ratio(_hex(scheme["base05"]), _hex(scheme["base00"]))
        (kept if ratio >= MIN_TEXT_CONTRAST else skipped).append((path, ratio))

    for existing in THEMES_DIR.glob("*.yaml"):
        existing.unlink()
    for path, _ in kept:
        (THEMES_DIR / path.name).write_bytes(path.read_bytes())
    for path in staging.glob("*.yaml"):
        path.unlink()
    staging.rmdir()

    print(f"installed: {len(kept)}")
    print(f"skipped below {MIN_TEXT_CONTRAST}:1 ({len(skipped)}):")
    for path, ratio in sorted(skipped, key=lambda row: row[1]):
        print(f"  {ratio:5.2f}  {path.stem}")
    return 0


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


if __name__ == "__main__":
    raise SystemExit(main())
