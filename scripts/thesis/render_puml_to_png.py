"""Render a PlantUML .puml file to PNG via the public PlantUML server.

Usage:
    python render_puml_to_png.py <path-to-puml-file>

Writes <basename>.png next to the input file. Requires only stdlib.
"""

from __future__ import annotations

import sys
import zlib
from pathlib import Path
from urllib.request import Request, urlopen


PLANTUML_SERVER = 'https://www.plantuml.com/plantuml/png/'


def _encode_6bit(b: int) -> str:
    if b < 10:
        return chr(48 + b)
    b -= 10
    if b < 26:
        return chr(65 + b)
    b -= 26
    if b < 26:
        return chr(97 + b)
    b -= 26
    if b == 0:
        return '-'
    if b == 1:
        return '_'
    return '?'


def _encode_3bytes(b1: int, b2: int, b3: int) -> str:
    c1 = b1 >> 2
    c2 = ((b1 & 0x3) << 4) | (b2 >> 4)
    c3 = ((b2 & 0xF) << 2) | (b3 >> 6)
    c4 = b3 & 0x3F
    return (_encode_6bit(c1) + _encode_6bit(c2)
            + _encode_6bit(c3) + _encode_6bit(c4))


def encode_plantuml(text: str) -> str:
    zlibbed = zlib.compress(text.encode('utf-8'))
    raw = zlibbed[2:-4]
    out = []
    for i in range(0, len(raw), 3):
        b1 = raw[i]
        b2 = raw[i + 1] if i + 1 < len(raw) else 0
        b3 = raw[i + 2] if i + 2 < len(raw) else 0
        out.append(_encode_3bytes(b1, b2, b3))
    return ''.join(out)


def render(puml_path: Path) -> Path:
    puml_text = puml_path.read_text(encoding='utf-8')
    encoded = encode_plantuml(puml_text)
    url = PLANTUML_SERVER + encoded
    req = Request(url, headers={
        'User-Agent': ('Mozilla/5.0 (compatible; CJPCA-PUML-Render/1.0)'),
        'Accept': 'image/png,*/*',
    })
    with urlopen(req, timeout=30) as resp:
        png_bytes = resp.read()
    out_path = puml_path.with_suffix('.png')
    out_path.write_bytes(png_bytes)
    return out_path


def main():
    if len(sys.argv) < 2:
        print('Usage: render_puml_to_png.py <path-to-puml>',
              file=sys.stderr)
        sys.exit(1)
    src = Path(sys.argv[1]).resolve()
    if not src.exists():
        print(f'File not found: {src}', file=sys.stderr)
        sys.exit(2)
    out = render(src)
    print(f'Wrote {out}')


if __name__ == '__main__':
    main()
