#!/usr/bin/env python3
"""Tests for compare_counts.py (the counts of the connector, period by period). Run: python3 tests/test_compare.py"""
import json
import os
import subprocess
import sys
import tempfile

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CMP = os.path.join(SKILL, "scripts", "compare_counts.py")
CHART = os.path.join(SKILL, "scripts", "incident_chart.py")
failures = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def run(data, *args):
    tmp = tempfile.mkdtemp()
    f, out = os.path.join(tmp, "c.json"), os.path.join(tmp, "s.json")
    json.dump(data, open(f, "w", encoding="utf-8"), ensure_ascii=False)
    r = subprocess.run([sys.executable, CMP, f, "-o", out, *args], capture_output=True, text=True)
    return r, (json.loads(r.stdout) if r.returncode == 0 else None), out


two = {"group_by": "reason", "compare_field": "year", "periods": [
    {"name": "2025", "total": 41, "groups": {"късо съединение-01": 12, "умисъл-08": 3, "в процес на установяване-09": 26}},
    {"name": "2026", "total": 37, "groups": [{"value": "късо съединение-01", "count": 9}, {"value": "умисъл-08", "count": 6},
                                              {"value": "01 - късо съединение", "count": 1}, {"value": "други-10", "count": 21}]}]}
r, res, out = run(two)
g = {x["key"][0]: x for x in res["groups"]}
check(res["total_by_compare"] == {"2025": 41, "2026": 37} and res["total_change"] == -4, "totals per period and their change")
check(g["късо съединение"]["by_compare"] == {"2025": 12, "2026": 10} and g["късо съединение"]["change"] == -2,
      "the code is dropped from the label; the same cause written two ways is one row")
check(g["умисъл"]["change"] == 3 and g["в процес на установяване"]["by_compare"]["2026"] == 0, "a value missing in a period counts as 0")
check("warning" not in res, "groups that add up to the total → no warning")
c = subprocess.run([sys.executable, CHART, out, "-o", out + ".svg"], capture_output=True, text=True)
check(c.returncode == 0 and json.loads(c.stdout)["series"] == ["2025", "2026"], "incident_chart.py draws the result")

r, res, _ = run(two, "--top", "2")
check(len(res["groups"]) == 2 and res["other"]["groups"] == 2 and res["other"]["count"] == res["total"] - sum(x["count"] for x in res["groups"]),
      "--top keeps the largest and sums the rest")

bad = json.loads(json.dumps(two)); bad["periods"][1]["total"] = 50
r, res, _ = run(bad)
check(res["unaccounted"] == {"2026": 13} and "Сборът по групи" in res["warning"], "groups that do not add up to the total → said, not hidden")

r, res, out = run({"compare_field": "month", "periods": [{"name": "2026-07", "total": 30}, {"name": "2026-08", "total": 44}, {"name": "2026-09", "total": 21}]})
check(res["count_only"] and res["total_change"] == -9 and res["compare_values"] == ["2026-07", "2026-08", "2026-09"], "totals only, month by month")

r, res, out = run({"group_by": "unit", "periods": [{"name": "август 2026", "groups": {"РС ПБЗН - Левски": 7, "РС ПБЗН - Кнежа": 4}}]})
check(res["total"] == 11 and "total_change" not in res and "change" not in res["groups"][0], "one period → a plain breakdown, no comparison")
c = subprocess.run([sys.executable, CHART, out, "-o", out + ".svg"], capture_output=True, text=True)
check(c.returncode == 0, "…and a chart of it")

for data, why in (({}, "no periods"), ({"periods": [{"name": "a", "total": 1}, {"name": "a", "total": 2}]}, "a repeated name"),
                  ({"periods": [{"name": "a", "total": 1, "groups": {"x": 1}}, {"name": "b", "total": 2}]}, "groups in one period only"),
                  ({"periods": [{"name": "a"}, {"name": "b", "total": 2}]}, "no total")):
    r, res, _ = run(data)
    check(r.returncode != 0 and r.stderr.startswith("BAD_INPUT"), f"{why} → BAD_INPUT")

print("\nALL PASS" if not failures else f"\n{len(failures)} FAILED")
sys.exit(1 if failures else 0)
