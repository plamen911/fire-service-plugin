#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compare_counts.py — puts side by side counts that were taken period by period (or value by value) and
computes the differences. It is for the „connector“ mode, where the numbers come from the tool
`incidents` – one call per period – and there is no file with the records for incident_stats.py.
Nothing is counted in one's head: the tool gives the counts, this script gives the table and the change.

Usage:
    python3 scripts/compare_counts.py counts.json [--top N] [-o stats.json]
    python3 scripts/incident_chart.py stats.json -o "/mnt/user-data/outputs/Grafika_....svg"   # the same chart

counts.json – what the tool returned, copied without change:
    {
      "group_by": "reason",                        # the field of the breakdown; omit it for totals only
      "compare_field": "year",                     # what the periods are: year | month | month_of_year | …
      "periods": [
        {"name": "2025", "total": 41, "groups": {"късо съединение-01": 12, "умисъл-08": 3}},
        {"name": "2026", "total": 37, "groups": {"късо съединение-01": 9,  "умисъл-08": 6}}
      ]
    }
`groups` may also be a list of {"value" | "key" | "name": …, "count": …}. A period without `groups` gives
totals only. The periods stay in the order given. A single period is fine too – then the result is a plain
breakdown (for the chart), without a comparison.

Prints the same shape as incident_stats.py with --compare-field (so answers.md and incident_chart.py apply):
    {"source": "counts", "group_by", "compare_field", "compare_values", "total_by_compare", "total",
     "total_change", "groups": [{"key": [label], "count", "by_compare": {…}, "change"}], "other"}
`change` and `total_change` = the last period minus the first.

Errors (stderr, exit code 1):  BAD_INPUT: …
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from incident_stats import CODE_HEAD, CODE_TAIL, clean  # noqa: E402  (the same labels as in the statistics)


def label(value):
    """„късо съединение-01“ / „01 - късо съединение“ → „късо съединение“; empty → „(няма)“."""
    v = CODE_HEAD.sub("", CODE_TAIL.sub("", clean(value)))
    return v or "(няма)"


def counts_of(period, i):
    g = period.get("groups")
    if g is None:
        return None
    out = {}
    items = g.items() if isinstance(g, dict) else [
        (x.get("value", x.get("key", x.get("name"))), x.get("count")) for x in g if isinstance(x, dict)]
    for k, n in items:
        if isinstance(k, list):
            k = " · ".join(str(x) for x in k)
        try:
            n = int(n)
        except (TypeError, ValueError):
            sys.exit(f"BAD_INPUT: periods[{i}].groups – броят за „{k}“ не е число: {n!r}")
        out[label(k)] = out.get(label(k), 0) + n      # the same label written two ways is one row
    return out


def build(data, top=None):
    periods = data.get("periods")
    if not isinstance(periods, list) or not periods or any(not isinstance(p, dict) for p in periods):
        sys.exit('BAD_INPUT: "periods" трябва да е списък с поне един период')
    names, totals, per = [], {}, []
    for i, p in enumerate(periods):
        name = clean(p.get("name"))
        if not name or name in totals:
            sys.exit(f"BAD_INPUT: periods[{i}] – липсва или се повтаря \"name\"")
        groups = counts_of(p, i)
        total = p.get("total", sum(groups.values()) if groups is not None else None)
        try:
            total = int(total)
        except (TypeError, ValueError):
            sys.exit(f"BAD_INPUT: periods[{i}] („{name}“) – липсва \"total\"")
        names.append(name)
        totals[name] = total
        per.append(groups)
    with_groups = [g for g in per if g is not None]
    if with_groups and len(with_groups) != len(per):
        sys.exit('BAD_INPUT: "groups" има само в част от периодите – дай го за всички или за никой')
    many = len(names) > 1     # one period: a plain breakdown (for the chart), nothing to compare
    result = {"source": "counts", "group_by": [data["group_by"]] if data.get("group_by") and with_groups else [],
              "total": sum(totals.values())}
    if many:
        result.update(compare_field=data.get("compare_field") or "period", compare_values=names,
                      total_by_compare=totals, total_change=totals[names[-1]] - totals[names[0]])
    else:
        result["period"] = names[0]
    if not with_groups:
        result.update(count_only=True, groups_count=0, groups=[])
        return result
    keys = []
    for g in per:
        keys += [k for k in g if k not in keys]
    rows = [{"key": [k], "count": sum(g.get(k, 0) for g in per)} for k in keys]
    if many:
        for r in rows:
            k = r["key"][0]
            r.update(by_compare={n: g.get(k, 0) for n, g in zip(names, per)}, change=per[-1].get(k, 0) - per[0].get(k, 0))
    rows.sort(key=lambda r: (-r["count"], r["key"][0]))
    result["groups_count"] = len(rows)
    if top and len(rows) > top:
        rest = rows[top:]
        rows = rows[:top]
        result["other"] = {"groups": len(rest), "count": sum(r["count"] for r in rest)}
        if many:
            result["other"]["by_compare"] = {n: sum(r["by_compare"][n] for r in rest) for n in names}
    result["groups"] = rows
    missing = {n: totals[n] - sum(g.values()) for n, g in zip(names, per) if totals[n] != sum(g.values())}
    if missing:   # the groups of a period do not add up to its total – say it instead of hiding it
        result["unaccounted"] = missing
        result["warning"] = ("Сборът по групи не е равен на общия брой за: "
                             + ", ".join(f"{n} (разлика {d})" for n, d in missing.items())
                             + " – провери дали групите са подадени изцяло.")
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="Counts per period side by side, with the change.")
    ap.add_argument("counts", help="JSON file with the counts per period (see the top of the script)")
    ap.add_argument("--top", type=int, metavar="N", help="keep only the N largest groups")
    ap.add_argument("-o", "--output", help="also write the JSON result to this file (for incident_chart.py)")
    a = ap.parse_args(argv)
    if a.top is not None and a.top < 1:
        sys.exit("BAD_REQUEST: --top must be 1 or more")
    try:
        with open(a.counts, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as e:
        sys.exit(f"BAD_INPUT: cannot read {a.counts}: {e.strerror}")
    except ValueError:
        sys.exit(f"BAD_INPUT: {a.counts} is not valid JSON")
    if not isinstance(data, dict):
        sys.exit("BAD_INPUT: очаква се обект с \"periods\"")
    text = json.dumps(build(data, a.top), ensure_ascii=False, indent=1)
    if a.output:
        with open(a.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
