#!/usr/bin/env python3
"""
izrezki.py — cuts a photo of a duty schedule into enlarged tiles that are easy to read.

A photo of a whole month (15–50 rows × 31 day columns) is too dense to read reliably in one
look. This script cuts the table into horizontal bands and (optionally) into left/right halves
of the day columns; every tile carries the header row with the day numbers on top and the name
column on the left, so each cell can be read against its day and its employee.

    python3 scripts/izrezki.py SNIMKA.jpg --box 0.03,0.33,0.99,0.57 --header 0.333,0.345 \
        --names 0.04,0.225 --bands 3 --cols 2 -o /tmp/grafik_oc

Coordinates are fractions of the image (0–1) or pixels (values above 1):
  --box     x0,y0,x1,y1  the table body: the employee rows and all day columns
  --header  y0,y1        the row with the day numbers (repeated on top of every tile)
  --names   x0,x1        the name column (repeated on the left of every tile when --cols > 1)
  --bands   N            horizontal bands (about 6–10 rows per band reads best)
  --cols    N            vertical parts of the day columns (1 = keep full width)
  --overlap F            overlap between neighbouring bands/parts, fraction of their size
  --rotate  DEG          rotate the photo first (counter-clockwise), for a tilted sheet

Prints one JSON line: {"tiles": [paths], "bands": N, "cols": N}. Requires Pillow.
"""
import argparse
import json
import os
import sys

from PIL import Image, ImageOps

MAX_SIDE = 1500  # tiles larger than this get downscaled by viewers; keep them below


def nums(text, count, name):
    try:
        vals = [float(v) for v in text.split(",")]
    except ValueError:
        sys.exit(f"BAD_ARGS: --{name} must be {count} numbers separated by commas")
    if len(vals) != count:
        sys.exit(f"BAD_ARGS: --{name} must be {count} numbers separated by commas")
    return vals


def px(value, size):
    """Fraction (≤ 1) or pixels → pixels inside the image."""
    return max(0, min(size, int(round(value * size if value <= 1 else value))))


def spans(start, end, parts, overlap):
    """`parts` consecutive (a, b) spans covering start–end, each widened by `overlap` of its size."""
    step = (end - start) / parts
    pad = step * overlap
    return [(int(max(start, start + i * step - pad)), int(min(end, start + (i + 1) * step + pad)))
            for i in range(parts)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--box", required=True, help="x0,y0,x1,y1 of the table body")
    ap.add_argument("--header", help="y0,y1 of the row with the day numbers")
    ap.add_argument("--names", help="x0,x1 of the name column")
    ap.add_argument("--bands", type=int, default=3)
    ap.add_argument("--cols", type=int, default=1)
    ap.add_argument("--overlap", type=float, default=0.08)
    ap.add_argument("--rotate", type=float, default=0.0)
    ap.add_argument("-o", "--out", required=True, help="output folder")
    a = ap.parse_args()

    im = ImageOps.exif_transpose(Image.open(a.image)).convert("RGB")
    if a.rotate:
        im = im.rotate(a.rotate, expand=True, fillcolor="white", resample=Image.BICUBIC)
    w, h = im.size
    bx0, by0, bx1, by1 = nums(a.box, 4, "box")
    x0, x1, y0, y1 = px(bx0, w), px(bx1, w), px(by0, h), px(by1, h)
    if x1 <= x0 or y1 <= y0:
        sys.exit("BAD_ARGS: --box is empty")
    head = None
    if a.header:
        hy0, hy1 = nums(a.header, 2, "header")
        head = (px(hy0, h), px(hy1, h))
    names = None
    if a.names:
        nx0, nx1 = nums(a.names, 2, "names")
        names = (px(nx0, w), px(nx1, w))
    # the day columns start where the name column ends
    dx0 = names[1] if names and a.cols > 1 else x0

    os.makedirs(a.out, exist_ok=True)
    tiles = []
    for bi, (ty0, ty1) in enumerate(spans(y0, y1, max(1, a.bands), a.overlap), 1):
        for ci, (tx0, tx1) in enumerate(spans(dx0, x1, max(1, a.cols), a.overlap), 1):
            left = [names] if names and a.cols > 1 else []
            cols = left + [(tx0, tx1)]
            rows = ([head] if head else []) + [(ty0, ty1)]
            tw = sum(c[1] - c[0] for c in cols)
            th = sum(r[1] - r[0] for r in rows)
            tile = Image.new("RGB", (tw, th), "white")
            oy = 0
            for ry0, ry1 in rows:
                ox = 0
                for cx0, cx1 in cols:
                    tile.paste(im.crop((cx0, ry0, cx1, ry1)), (ox, oy))
                    ox += cx1 - cx0
                oy += ry1 - ry0
            scale = min(3.0, MAX_SIDE / max(tw, th))
            if abs(scale - 1) > 0.02:
                tile = tile.resize((int(tw * scale), int(th * scale)), Image.LANCZOS)
            path = os.path.join(a.out, f"tile_r{bi:02d}_c{ci:02d}.png")
            tile.save(path)
            tiles.append(path)
    print(json.dumps({"tiles": tiles, "bands": a.bands, "cols": a.cols}, ensure_ascii=False))


if __name__ == "__main__":
    main()
