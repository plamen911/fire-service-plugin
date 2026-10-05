#!/usr/bin/env python3
"""Tests for incident_stats.py and export_incidents_xlsx.py. Run from the skill folder:
    python3 tests/test_stats.py
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
XLSX = os.path.join(SKILL, "scripts", "export_incidents_xlsx.py")
F25 = os.path.join(HERE, "fixtures", "records_2025.json")
F26 = os.path.join(HERE, "fixtures", "records_2026.json")

failures = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def run(*args):
    r = subprocess.run([sys.executable, STATS, *args], capture_output=True, text=True)
    return r.returncode, (json.loads(r.stdout) if r.returncode == 0 else None), r.stderr


def groups(res):
    return {" | ".join(g["key"]): g for g in res["groups"]}


def main():
    # totals, de-duplication across files, period and gaps
    rc, res, _ = run(F25, F26, "--count-only")
    check(rc == 0, "count-only runs")
    check(res["records_read"] == 10 and res["duplicates_dropped"] == 1, "two files merged, duplicate id dropped")
    check(res["total"] == 10 and "groups" not in res, "count-only has total and no groups")
    check(res["period"]["first"] == "2025-07-03" and res["period"]["last"] == "2026-09-01", "period first/last")
    check(res["period"]["months"] == {"2025-07": 3, "2026-07": 6, "2026-09": 1}, "records per month")
    check("2026-08" in res["period"]["empty_months"] and "2025-08" in res["period"]["empty_months"]
          and "2026-07" not in res["period"]["empty_months"], "empty months between first and last")
    check(res["casualties"] == {"injured": 2, "dead": 1}, "injured and dead counted from detail.casualties")

    # group by kind
    _, res, _ = run(F25, F26, "--group-by", "kind")
    g = groups(res)
    check(g["пожар с преки материални загуби"]["count"] == 5, "kind without code: 5 fires with losses")
    check(g["пожар без преки материални загуби"]["count"] == 4, "kind: 4 fires without losses")
    check(res["groups"][0]["key"] == ["пожар с преки материални загуби"], "groups sorted by count desc")
    check(sum(x["count"] for x in res["groups"]) == res["total"], "group counts add up to total")

    # service folds УПБЗН into РСПБЗН – Плевен; station keeps it
    _, res, _ = run(F25, F26, "--group-by", "service")
    g = groups(res)
    check(g["РСПБЗН – Плевен"]["count"] == 4, "service: Сторгозия and Долна Митрополия count for РСПБЗН – Плевен")
    check(g["РСПБЗН – Левски"]["count"] == 3, "service: РСПБЗН – Левски")
    _, res, _ = run(F25, F26, "--group-by", "station")
    check("УПБЗН – Сторгозия" in groups(res), "station keeps УПБЗН – Сторгозия with en dash")

    # settlement normalisation: "Плевен", "гр.Плевен", "гр. Плевен" are one place
    _, res, _ = run(F25, F26, "--group-by", "settlement")
    g = groups(res)
    check(g["гр. Плевен"]["count"] == 3, "settlement: three spellings of Плевен merged")
    check("Летница" in g and "с. Асеновци" in g, "settlement: 'землището' dropped, 'с.' spaced")
    # free-text object: case and trailing spaces merged
    _, res, _ = run(F25, F26, "--group-by", "object")
    check(groups(res)["суха трева"]["count"] == 3, "object: 'Суха трева ' and 'суха трева' merged")

    # missing values
    _, res, _ = run(F25, F26, "--group-by", "cause")
    check(groups(res)["(няма данни)"]["count"] == 1, "empty reason → (няма данни)")

    # compare two years, with change
    _, res, _ = run(F25, F26, "--group-by", "cause", "--compare-field", "year")
    check(res["compare_values"] == ["2025", "2026"], "compare values ascending")
    check(res["total_by_compare"] == {"2025": 3, "2026": 7} and res["total_change"] == 4, "totals and change by year")
    ks = groups(res)["късо съединение"]
    check(ks["by_compare"] == {"2025": 2, "2026": 0} and ks["change"] == -2, "per-group compare and change")

    # two group-by fields
    _, res, _ = run(F25, F26, "--group-by", "service", "--group-by", "kind")
    check(groups(res)["РСПБЗН – Левски | пожар с преки материални загуби"]["count"] == 2, "pairs of two fields")

    # top N with the rest summed
    _, res, _ = run(F25, F26, "--group-by", "settlement", "--top", "2")
    check(len(res["groups"]) == 2 and res["groups"][0]["key"] == ["гр. Плевен"], "top 2 kept")
    check(res["other"]["count"] + sum(x["count"] for x in res["groups"]) == res["total"], "top: rest summed in other")
    check(res["groups_count"] == 8, "groups_count counts all groups")

    # virtual time fields
    _, res, _ = run(F26, "--group-by", "weekday")
    check(all(k[0] in ("понеделник", "вторник", "сряда", "четвъртък", "петък", "събота", "неделя")
              for k in (x["key"] for x in res["groups"])), "weekday names in Bulgarian")
    _, res, _ = run(F25, F26, "--group-by", "month_of_year", "--compare-field", "year")
    check(groups(res)["07 юли"]["by_compare"] == {"2025": 3, "2026": 6}, "month_of_year compares July across years")
    _, res, _ = run(F25, F26, "--group-by", "state")
    check(groups(res)["отворен (само сигнал)"]["count"] == 1, "state label for status=open")
    _, res, _ = run(F25, F26, "--group-by", "municipality")
    check("Червен бряг" in groups(res), "municipality keeps the official spelling Червен бряг")

    # deterministic output and the -o file
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "stats.json")
    a = subprocess.run([sys.executable, STATS, F25, F26, "--group-by", "service", "-o", out],
                       capture_output=True, text=True).stdout
    b = subprocess.run([sys.executable, STATS, F25, F26, "--group-by", "service"], capture_output=True, text=True).stdout
    check(a == b, "same input → same output")
    check(json.load(open(out, encoding="utf-8")) == json.loads(a), "-o writes the same JSON")

    # errors
    rc, _, err = run(F25, "--group-by", "no_such_field")
    check(rc != 0 and "BAD_REQUEST" in err, "unknown field → BAD_REQUEST")
    rc, _, err = run(F25, "--group-by", "kind", "--group-by", "cause", "--group-by", "year")
    check(rc != 0 and "BAD_REQUEST" in err, "three --group-by → BAD_REQUEST")
    bad = os.path.join(tmp, "bad.json")
    open(bad, "w").write('{"x": 1}')
    rc, _, err = run(bad)
    check(rc != 0 and "BAD_INPUT" in err, "not an array → BAD_INPUT")
    rc, _, err = run(os.path.join(tmp, "missing.json"))
    check(rc != 0 and "BAD_INPUT" in err, "missing file → BAD_INPUT")
    empty = os.path.join(tmp, "empty.json")
    open(empty, "w").write("[]")
    rc, res, _ = run(empty, "--group-by", "kind")
    check(rc == 0 and res["total"] == 0 and res["groups"] == [] and res["period"]["first"] is None,
          "empty input → zero, no groups")

    # xlsx export
    try:
        from openpyxl import load_workbook
    except ImportError:
        print("  skip xlsx (openpyxl missing)")
    else:
        x = os.path.join(tmp, "out.xlsx")
        r = subprocess.run([sys.executable, XLSX, F25, F26, "--stats", out, "-o", x], capture_output=True, text=True)
        check(r.returncode == 0 and os.path.exists(x), "xlsx export runs")
        wb = load_workbook(x)
        check(wb.sheetnames == ["Произшествия", "Обобщение"], "two sheets with Bulgarian names")
        ws = wb["Произшествия"]
        head = [c.value for c in ws[1]]
        check(head[:3] == ["Дата и час", "№ на телефонограмата", "Служба"] and "Адрес" not in head,
              "Bulgarian headers, no address by default")
        check(ws.max_row == 11 and ws["A2"].value == "03.07.2025 14:10", "one row per record, oldest first")
        text = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
        check("***" not in text and "Х.Х.Х." not in text and "43.4" not in text, "no owner, casualty or coordinates")
        tot = " ".join(str(c.value) for row in wb["Обобщение"].iter_rows() for c in row if c.value is not None)
        check("РСПБЗН – Плевен" in tot and "Общо произшествия" in tot, "totals sheet from stats")
        x2 = os.path.join(tmp, "out2.xlsx")
        subprocess.run([sys.executable, XLSX, F26, "--with-address", "-o", x2], check=True, capture_output=True)
        check("Адрес" in [c.value for c in load_workbook(x2)["Произшествия"][1]], "--with-address adds the column")

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        sys.exit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
