#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
incident_map.py — a map (.svg) of incidents by settlement.

Every record in the database carries the same coordinates (the centre of Pleven), so an
incident is placed at the settlement named in its `location`, with the coordinates from
`_shared/raioni/koordinati_pleven.csv` (the settlements of РДПБЗН – Плевен). The picture is
schematic: one circle per settlement with the number of incidents there, the towns as
reference points, no street map. Pure standard library, no network.

Usage:
    python3 _shared/scripts/fetch_incidents.py --from 2026-09-01 --to 2026-09-30 -o sep.json
    python3 scripts/incident_map.py sep.json -o "/mnt/user-data/outputs/Karta_....svg"
    python3 scripts/incident_map.py r2025.json r2026.json --title "Пожари в МПС, 2025–2026" -o map.svg

Arguments:
    records          one or more JSON files from `fetch_incidents.py -o` (merged, duplicate ids dropped)
    --title TEXT     the caption above the map (default: „Произшествия по населени места“)
    -o/--output      the .svg to write (required)

Colours: a settlement with at least one fire with direct material losses; with fires
without losses only; with other incidents only.

Prints on stdout: {"output", "records", "located", "not_located", "settlements",
"top": [{"settlement", "count"}]} — say `not_located` in the answer.
Errors (stderr, exit code ≠ 0):
    BAD_INPUT: ...     — a file is missing or is not an array of records
    NOTHING_TO_DRAW    — no record names a settlement of the directorate
"""
import argparse
import csv
import json
import math
import os
import re
import sys
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from incident_stats import clean, load, strip_code  # noqa: E402

COORDINATES = os.path.join(os.path.dirname(HERE), "_shared", "raioni", "koordinati_pleven.csv")
FIRE_WITH_LOSSES = "пожар с преки материални загуби"
COLOURS = {"losses": "#eb6834", "fire": "#2a78d6", "other": "#1baf7a"}
FONT = "font-family=\"-apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif\""


def settlements():
    """The directorate's settlements, longest names first (so „Долна Митрополия“ wins over a shorter name)."""
    with open(COORDINATES, encoding="utf-8") as fh:
        rows = list(csv.DictReader(line for line in fh if not line.startswith("#")))
    for r in rows:
        r["lat"], r["lng"] = float(r["lat"]), float(r["lng"])
        r["pattern"] = re.compile(r"(?<![^\W\d_])" + re.escape(r["naseleno_masto"].lower()) + r"(?![^\W\d_])")
    return sorted(rows, key=lambda r: (-len(r["naseleno_masto"]), r["ekatte"]))


def locate(location, region, places):
    """The settlement named in `location` („гр. Плевен “, „с.Опанец“, „Летница землището“), or None."""
    text = re.sub(r"\s+", " ", location.lower()).strip()
    if not text:
        return None

    found = []
    for place in places:
        if place["pattern"].search(text):
            if found and len(place["naseleno_masto"]) < len(found[0]["naseleno_masto"]):
                break
            found.append(place)
    if len(found) <= 1:
        return found[0] if found else None

    # Equal names (гр. Искър and с. Искър): the kind written, then the municipality, then the town.
    kind = "гр." if re.search(r"(?<![^\W\d_])(гр|град)(?![^\W\d_])", text) else (
        "с." if re.search(r"(?<![^\W\d_])(с|село)(?![^\W\d_])", text) else None)
    region = re.sub(r"\s+", " ", region.lower()).strip()
    for rule in (lambda p: kind and p["vid"] == kind,
                 lambda p: region and p["obshtina"].lower() == region,
                 lambda p: p["vid"] == "гр."):
        matching = [p for p in found if rule(p)]
        if len(matching) == 1:
            return matching[0]
    return found[0]


def kind_of(record):
    kind = (strip_code(record.get("casulaty")) or clean(record.get("type"))).lower()
    return "losses" if kind == FIRE_WITH_LOSSES else ("fire" if kind.startswith("пожар") else "other")


def group(rows, places):
    """→ ({ekatte: {"place", "count", "kind"}}, located, not_located)"""
    points, located = {}, 0
    rank = {"other": 0, "fire": 1, "losses": 2}
    for record in rows:
        place = locate(clean(record.get("location")), clean(record.get("region")), places)
        if place is None:
            continue
        located += 1
        point = points.setdefault(place["ekatte"], {"place": place, "count": 0, "kind": "other"})
        point["count"] += 1
        kind = kind_of(record)
        if rank[kind] > rank[point["kind"]]:
            point["kind"] = kind
    return points, located, len(rows) - located


def svg(title, points, places, not_located, total):
    width, pad, top = 860, 24, 56
    lats = [p["lat"] for p in places]
    lngs = [p["lng"] for p in places]
    lat0, lat1, lng0, lng1 = min(lats), max(lats), min(lngs), max(lngs)
    squeeze = math.cos(math.radians((lat0 + lat1) / 2))  # a degree of longitude is shorter than one of latitude
    scale = (width - 2 * pad - 40) / ((lng1 - lng0) * squeeze)
    map_h = (lat1 - lat0) * scale
    height = int(top + map_h + 104)

    def xy(place):
        return pad + 20 + (place["lng"] - lng0) * squeeze * scale, top + 10 + (lat1 - place["lat"]) * scale

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="{pad}" y="30" {FONT} font-size="14" font-weight="600" fill="#27272a">{escape(title)}</text>',
        f'<rect x="{pad}" y="{top - 6}" width="{width - 2 * pad}" height="{map_h + 32:.0f}" rx="8" fill="#f4f4f5"/>',
    ]

    # Reference: every settlement as a faint dot, the towns with their names.
    marked = set(points)
    for place in places:
        x, y = xy(place)
        town = place["vid"] == "гр."
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{2.2 if town else 1.3}" fill="{"#a1a1aa" if town else "#d4d4d8"}"/>')
        if town and place["ekatte"] not in marked:
            out.append(f'<text x="{x + 5:.1f}" y="{y + 3.5:.1f}" {FONT} font-size="10" fill="#a1a1aa">{escape(place["naseleno_masto"])}</text>')

    # Bigger circles first, so a small neighbour stays visible on top.
    ordered = sorted(points.values(), key=lambda p: (-p["count"], p["place"]["ekatte"]))
    labelled = {p["place"]["ekatte"] for p in ordered[:14]} | {p["place"]["ekatte"] for p in ordered if p["place"]["vid"] == "гр."}
    for point in ordered:
        x, y = xy(point["place"])
        r = min(24.0, 7 + 3 * math.sqrt(point["count"] - 1))
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{COLOURS[point["kind"]]}" fill-opacity="0.9" stroke="#ffffff" stroke-width="2"/>')
    for point in ordered:
        x, y = xy(point["place"])
        r = min(24.0, 7 + 3 * math.sqrt(point["count"] - 1))
        if point["place"]["ekatte"] in labelled:
            name = escape(point["place"]["naseleno_masto"])
            ly = y + r + 11
            # A name that would land on a neighbour's circle goes above its own instead.
            for other in ordered:
                ox, oy = xy(other["place"])
                if other is not point and math.hypot(ox - x, oy - (ly - 4)) < min(24.0, 7 + 3 * math.sqrt(other["count"] - 1)) + 4:
                    ly = y - r - 5
                    break
            out.append(f'<text x="{x:.1f}" y="{ly:.1f}" text-anchor="middle" {FONT} font-size="10.5" font-weight="600" fill="#3f3f46" stroke="#f4f4f5" stroke-width="2.5" paint-order="stroke">{name}</text>')

    # The numbers last, so a neighbour's name never covers them.
    for point in ordered:
        if point["count"] > 1:
            x, y = xy(point["place"])
            out.append(f'<text x="{x:.1f}" y="{y + 4:.1f}" text-anchor="middle" {FONT} font-size="11" font-weight="600" fill="#ffffff">{point["count"]}</text>')

    y = top + map_h + 46
    x = pad
    for key, text in (("losses", "има пожар с преки материални загуби"), ("fire", "пожари без преки материални загуби"), ("other", "други произшествия")):
        out.append(f'<circle cx="{x + 6}" cy="{y - 4:.0f}" r="6" fill="{COLOURS[key]}"/>')
        out.append(f'<text x="{x + 17}" y="{y:.0f}" {FONT} font-size="12" fill="#52525b">{text}</text>')
        x += 17 + 6.6 * len(text) + 22
    note = "Кръговете са по населено място, не по точен адрес; числото е броят на произшествията там."
    out.append(f'<text x="{pad}" y="{y + 22:.0f}" {FONT} font-size="11" fill="#71717a">{escape(note)}</text>')
    if not_located:
        missing = f"{not_located} от {total} не са на картата – мястото им не е разпознато или е извън областта."
        out.append(f'<text x="{pad}" y="{y + 38:.0f}" {FONT} font-size="11" fill="#71717a">{escape(missing)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="A map (.svg) of incidents by settlement.")
    ap.add_argument("records", nargs="+", help="JSON file(s) from fetch_incidents.py -o")
    ap.add_argument("--title", help="the caption above the map")
    ap.add_argument("-o", "--output", required=True, help="the .svg file to write")
    a = ap.parse_args(argv)

    rows, _ = load(a.records)
    places = settlements()
    points, located, not_located = group(rows, places)
    if not points:
        sys.exit("NOTHING_TO_DRAW: no record names a settlement of РДПБЗН – Плевен")

    with open(a.output, "w", encoding="utf-8") as fh:
        fh.write(svg((a.title or "").strip() or "Произшествия по населени места", points, places, not_located, len(rows)))

    top = sorted(points.values(), key=lambda p: (-p["count"], p["place"]["ekatte"]))[:10]
    print(json.dumps({
        "output": a.output, "records": len(rows), "located": located, "not_located": not_located,
        "settlements": len(points),
        "top": [{"settlement": f'{p["place"]["vid"]} {p["place"]["naseleno_masto"]}', "count": p["count"]} for p in top],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
