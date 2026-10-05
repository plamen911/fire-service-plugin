#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
incident_chart.py — a bar chart (.svg) of an incident_stats.py result.

The numbers in the picture are the script's own: nothing is recounted here. Pure standard
library, no network; the same input gives the same file.

Usage:
    python3 scripts/incident_stats.py records.json --group-by cause -o stats.json
    python3 scripts/incident_chart.py stats.json -o "/mnt/user-data/outputs/Grafika_....svg"
    python3 scripts/incident_chart.py stats.json --title "Пожари по причини, юли 2025 и 2026" -o chart.svg

Arguments:
    stats            JSON written by `incident_stats.py -o FILE`
    --title TEXT     the caption above the chart (default: „Брой по …“ from the fields)
    --max-bars N     at most N rows (default 15); the rest is summed in the note under the chart
    -o/--output      the .svg to write (required)

What is drawn: one row per group, in the order of the stats (months, days and hours in
calendar order); with --compare-field of 2–8 values — one bar per value with a legend;
with --count-only and a compare field — the totals per value. Every bar carries its number.

Prints on stdout: {"output", "rows", "series", "note"}.
Errors (stderr, exit code ≠ 0):
    BAD_INPUT: ...     — the file is missing or is not an incident_stats.py result
    NOTHING_TO_DRAW    — fewer than two bars (a single number needs no chart)
"""
import argparse
import json
import os
import sys
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from incident_stats import FIELD_LABELS, WEEKDAYS  # noqa: E402

# Categorical colours in a fixed order (the same as in the web app); values are always
# printed next to the bars, so colour never carries the meaning alone.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
CHRONOLOGICAL = {"year", "month", "month_of_year", "date", "hour"}
FONT = "font-family=\"-apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif\""


def label(field):
    return FIELD_LABELS.get(field, field).lower()


def natural(text):
    import re
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in re.split(r"(\d+)", text)]


def rows_of(stats, max_bars):
    """→ (title, series, rows, note); rows = [(label, [values])]."""
    group_by = [g for g in stats.get("group_by") or [] if isinstance(g, str)]
    groups = [g for g in stats.get("groups") or [] if isinstance(g, dict)]
    compare = [str(v) for v in stats.get("compare_values") or []]
    compare_label = label(stats.get("compare_field") or "")

    if not groups:
        totals = stats.get("total_by_compare") or {}
        rows = [(str(k), [int(v)]) for k, v in totals.items()]
        return "Брой по " + compare_label, [], rows[:max_bars], None

    series = compare if 2 <= len(compare) <= len(SERIES) else []
    rows = []
    for g in groups:
        values = [int((g.get("by_compare") or {}).get(v, 0)) for v in series] if series else [int(g.get("count", 0))]
        rows.append((" · ".join(str(k) for k in g.get("key") or []), values))

    if len(group_by) == 1:
        if group_by[0] in CHRONOLOGICAL:
            rows.sort(key=lambda r: natural(r[0]))
        elif group_by[0] == "weekday":
            rows.sort(key=lambda r: WEEKDAYS.index(r[0]) if r[0] in WEEKDAYS else 99)

    hidden = rows[max_bars:]
    rows = rows[:max_bars]
    other = stats.get("other") or {}
    rest_groups = len(hidden) + int(other.get("groups", 0))
    rest_count = sum(sum(v) for _, v in hidden) + int(other.get("count", 0))
    title = "Брой по " + " и ".join(label(f) for f in group_by)
    if series and compare_label:
        title += ", по " + compare_label

    return title, series, rows, (f"Останалите {rest_groups} – {rest_count}." if rest_groups else None)


def wrap(text, width):
    """Breaks a label into at most two lines of about `width` characters."""
    if len(text) <= width:
        return [text]
    cut = text.rfind(" ", 0, width + 1)
    cut = cut if cut > width // 2 else width
    first, rest = text[:cut].rstrip(), text[cut:].lstrip()
    return [first, rest if len(rest) <= width else rest[: width - 1].rstrip() + "…"]


def svg(title, series, rows, note):
    label_w, bar_w, pad, bar_h, gap = 230, 380, 16, 14, 3
    per_row = max(len(rows[0][1]) * (bar_h + gap) - gap, 30) + 12
    top = pad + 22 + (24 if series else 0)
    height = top + per_row * len(rows) + (22 if note else 0) + pad
    width = pad + label_w + 10 + bar_w + 50 + pad
    peak = max(max(v) for _, v in rows) or 1
    x0 = pad + label_w + 10
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="{pad}" y="{pad + 12}" {FONT} font-size="13" font-weight="600" fill="#27272a">{escape(title)}</text>',
    ]

    x = pad
    for i, name in enumerate(series):
        out.append(f'<rect x="{x}" y="{pad + 24}" width="10" height="10" rx="2" fill="{SERIES[i]}"/>')
        out.append(f'<text x="{x + 15}" y="{pad + 33}" {FONT} font-size="12" fill="#52525b">{escape(name)}</text>')
        x += 15 + 7 * len(name) + 18

    out.append(f'<line x1="{x0}" y1="{top}" x2="{x0}" y2="{top + per_row * len(rows) - 12}" stroke="#d4d4d8"/>')

    for r, (text, values) in enumerate(rows):
        y = top + r * per_row
        block = len(values) * (bar_h + gap) - gap
        lines = wrap(text, 34)
        ty = y + block / 2 + 4 - (7 if len(lines) == 2 else 0)
        for n, line in enumerate(lines):
            out.append(f'<text x="{x0 - 10}" y="{ty + n * 14:.0f}" text-anchor="end" {FONT} font-size="12" fill="#3f3f46">{escape(line)}</text>')
        for i, value in enumerate(values):
            w = round(bar_w * value / peak, 1)
            by = y + i * (bar_h + gap)
            out.append(f'<rect x="{x0}" y="{by}" width="{w}" height="{bar_h}" rx="2" fill="{SERIES[i]}"/>')
            out.append(f'<text x="{x0 + w + 6}" y="{by + bar_h - 3}" {FONT} font-size="12" fill="#3f3f46">{value}</text>')

    if note:
        out.append(f'<text x="{pad}" y="{height - pad}" {FONT} font-size="11" fill="#71717a">{escape(note)}</text>')

    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="A bar chart (.svg) of an incident_stats.py result.")
    ap.add_argument("stats", help="JSON file from incident_stats.py -o")
    ap.add_argument("--title", help="the caption above the chart")
    ap.add_argument("--max-bars", type=int, default=15, metavar="N", help="at most N rows (default 15)")
    ap.add_argument("-o", "--output", required=True, help="the .svg file to write")
    a = ap.parse_args(argv)

    try:
        with open(a.stats, encoding="utf-8") as fh:
            stats = json.load(fh)
    except (OSError, ValueError):
        sys.exit(f"BAD_INPUT: {a.stats} is not a stats JSON file")
    if not isinstance(stats, dict) or "total" not in stats:
        sys.exit(f"BAD_INPUT: {a.stats} is not an incident_stats.py result")

    title, series, rows, note = rows_of(stats, max(1, a.max_bars))
    if not rows or max(max(v) for _, v in rows) == 0 or (len(rows) < 2 and len(series) < 2):
        sys.exit("NOTHING_TO_DRAW: fewer than two bars – say the number in a sentence instead")

    with open(a.output, "w", encoding="utf-8") as fh:
        fh.write(svg((a.title or "").strip() or title, series, rows, note))
    print(json.dumps({"output": a.output, "rows": len(rows), "series": series, "note": note}, ensure_ascii=False))


if __name__ == "__main__":
    main()
