#!/usr/bin/env python3
"""Tests for incident_chart.py and incident_map.py. Run from the skill folder:
    python3 tests/test_visuals.py
The fixtures are fake records (no real people or addresses).
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
STATS = os.path.join(SKILL, "scripts", "incident_stats.py")
CHART = os.path.join(SKILL, "scripts", "incident_chart.py")
MAP = os.path.join(SKILL, "scripts", "incident_map.py")
F25 = os.path.join(HERE, "fixtures", "records_2025.json")
F26 = os.path.join(HERE, "fixtures", "records_2026.json")

failures = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def run(script, *args):
    r = subprocess.run([sys.executable, script, *args], capture_output=True, text=True)
    out = None
    if r.returncode == 0:
        out = json.loads(r.stdout)
    return r.returncode, out, r.stderr


def main():
    with tempfile.TemporaryDirectory() as tmp:
        stats = os.path.join(tmp, "stats.json")
        svg = os.path.join(tmp, "chart.svg")

        # chart of one distribution
        rc, _, _ = run(STATS, F25, F26, "--group-by", "kind", "-o", stats)
        check(rc == 0, "stats saved for the chart")
        rc, res, _ = run(CHART, stats, "--title", "Произшествия по вид", "-o", svg)
        check(rc == 0 and res["output"] == svg, "chart runs and reports the output")
        text = open(svg, encoding="utf-8").read()
        check(text.lstrip().startswith("<svg") or text.lstrip().startswith("<?xml"), "chart is an SVG file")
        check("Произшествия по вид" in text, "chart carries the title")
        check("пожар с преки материални загуби" in text, "chart labels the bars")
        total = json.load(open(stats, encoding="utf-8"))["total"]
        check(res["rows"] >= 2 and res["rows"] <= total, "chart reports its rows")

        # --max-bars keeps the biggest and says what was left out
        rc, _, _ = run(STATS, F25, F26, "--group-by", "settlement", "-o", stats)
        rc, res, _ = run(CHART, stats, "--max-bars", "2", "-o", svg)
        check(rc == 0 and res["rows"] == 2, "max-bars limits the bars")
        check(bool(res["note"]) and "Останалите" in res["note"], "the rest is named in the note")

        # comparison of two years: one series per value
        rc, _, _ = run(STATS, F25, F26, "--group-by", "kind", "--compare-field", "year", "-o", stats)
        rc, res, _ = run(CHART, stats, "-o", svg)
        check(rc == 0 and res["series"] == ["2025", "2026"], "compare values become the series")
        text = open(svg, encoding="utf-8").read()
        check("2025" in text and "2026" in text, "legend names both years")

        # count-only statistics have nothing to draw
        rc, _, _ = run(STATS, F25, F26, "--count-only", "-o", stats)
        rc, _, err = run(CHART, stats, "-o", svg)
        check(rc != 0 and "NOTHING_TO_DRAW" in err, "count-only statistics: NOTHING_TO_DRAW")

        bad = os.path.join(tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("not json")
        rc, _, err = run(CHART, bad, "-o", svg)
        check(rc != 0 and "BAD_INPUT" in err, "broken statistics file: BAD_INPUT")

        # map by settlement
        karta = os.path.join(tmp, "map.svg")
        rc, res, _ = run(MAP, F25, F26, "--title", "Произшествия", "-o", karta)
        check(rc == 0 and res["output"] == karta, "map runs and reports the output")
        check(res["records"] == 10, "map reads both files without the duplicate id")
        check(res["located"] + res["not_located"] == res["records"], "located + not located = records")
        check(res["located"] >= 3 and res["settlements"] >= 3, "the fixture settlements are found")
        names = [t["settlement"] for t in res["top"]]
        check("гр. Левски" in names and "с. Асеновци" in names and "гр. Плевен" in names,
              "settlement found from „гр. Левски “, „с.Асеновци“ and „Плевен“")
        text = open(karta, encoding="utf-8").read()
        check("<circle" in text and "Левски" in text, "map draws circles with names")
        check("43.4" not in text and "ул." not in text and "Х.Х.Х." not in text,
              "no record coordinates, street or person in the map")

        # nothing to place
        nowhere = os.path.join(tmp, "nowhere.json")
        with open(nowhere, "w", encoding="utf-8") as fh:
            json.dump([{"id": "1", "dat": "2026-07-01 10:00:00", "location": "извън областта"}], fh, ensure_ascii=False)
        rc, _, err = run(MAP, nowhere, "-o", karta)
        check(rc != 0 and "NOTHING_TO_DRAW" in err, "no known settlement: NOTHING_TO_DRAW")
        rc, _, err = run(MAP, bad, "-o", karta)
        check(rc != 0 and "BAD_INPUT" in err, "broken records file: BAD_INPUT")

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
