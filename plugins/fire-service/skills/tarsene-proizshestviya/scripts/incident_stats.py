#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
incident_stats.py — counts and groupings over incident records from pleven-fire-incidents.

Input is one or more JSON files written by `_shared/scripts/fetch_incidents.py -o FILE`
(a JSON array of records). Several files are merged and de-duplicated by `id`, so a long
period fetched in yearly pieces is counted once. Pure standard library, no network,
deterministic output.

Usage:
    python3 scripts/incident_stats.py records.json
    python3 scripts/incident_stats.py records.json --group-by cause
    python3 scripts/incident_stats.py records.json --group-by service --group-by cause
    python3 scripts/incident_stats.py jul2025.json jul2026.json --group-by cause --compare-field year
    python3 scripts/incident_stats.py records.json --group-by settlement --top 5
    python3 scripts/incident_stats.py records.json --count-only --compare-field month
    python3 scripts/incident_stats.py records.json --group-by kind -o stats.json

Arguments:
    records            one or more JSON files (fetch_incidents.py output)
    --group-by F       field to group by; give it once or twice (two fields = pairs)
    --compare-field F  field whose values become columns (e.g. year, month)
    --top N            keep the N largest groups; the rest are summed in "other"
    --count-only       totals only, no groups
    -o/--output FILE   also write the JSON result to FILE (stdout is always printed)

Fields: any top-level field of the record (`unit`, `location`, `reason`, …), a `detail.*`
field (`detail.activity_area`), or a virtual field (see VIRTUAL below). Values are compared
case-insensitively with collapsed whitespace; the label shown is the most frequent spelling.
Missing or empty values are grouped as "(няма данни)".

Output (stdout, JSON):
    {"records_read", "files", "duplicates_dropped",
     "period": {"first", "last", "months", "empty_months"},
     "total", "casualties": {"injured", "dead"},
     "group_by", "compare_field", "compare_values", "total_by_compare", "total_change",
     "groups_count", "groups": [{"key": [...], "count", "by_compare", "change", "injured", "dead"}],
     "top", "other": {"groups", "count", "by_compare"}}
Groups are sorted by count (desc), then by key (asc). "change" / "total_change" (second
compare value minus the first) are present only when --compare-field has exactly two values.

Errors (stderr, exit code ≠ 0):
    BAD_INPUT: ...    — a file is missing, is not JSON or is not an array of records
    BAD_REQUEST: ...  — unknown field, more than two --group-by, bad --top
"""
import argparse
import os
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict

NO_DATA = "(няма данни)"
MONTHS = ["януари", "февруари", "март", "април", "май", "юни", "юли", "август", "септември",
          "октомври", "ноември", "декември"]
WEEKDAYS = ["понеделник", "вторник", "сряда", "четвъртък", "петък", "събота", "неделя"]
# Stations that report under another service: their incidents count for РСПБЗН – Плевен.
STATION_TO_SERVICE = {"Сторгозия": "Плевен", "Долна Митрополия": "Плевен"}

VIRTUAL = {
    "year": "година на сигнала (ГГГГ)",
    "month": "месец на сигнала (ГГГГ-ММ)",
    "month_of_year": "месец без година (01 януари … 12 декември) – за сравнение на години",
    "date": "дата на сигнала (ГГГГ-ММ-ДД)",
    "weekday": "ден от седмицата (понеделник … неделя)",
    "hour": "час на сигнала (00–23)",
    "kind": "вид произшествие – casulaty без кода",
    "cause": "причина по телефонограмата – reason без кода",
    "object_class": "вид обект по класификатора – ucasulaty без кода",
    "place_class": "място на възникване – place без кода",
    "branch_class": "отрасъл – branch без кода",
    "station": "звено, подало телефонограмата – РСПБЗН – … / УПБЗН – …",
    "service": "районна служба – УПБЗН – Сторгозия и Долна Митрополия → РСПБЗН – Плевен",
    "settlement": "населено място – location, изчистено (с. / гр.)",
    "municipality": "община (или служба) по region, с малки букви",
    "shift": "дежурна смяна – orderlyturn",
    "state": "състояние на записа – status на български",
}

STATE_LABELS = {"open": "отворен (само сигнал)", "closed": "приключен"}

# Bulgarian column headers for fields (used in the .xlsx export and in answers).
FIELD_LABELS = {
    "year": "Година", "month": "Месец", "month_of_year": "Месец", "date": "Дата", "weekday": "Ден от седмицата",
    "hour": "Час", "kind": "Вид произшествие", "cause": "Причина", "object_class": "Вид обект",
    "place_class": "Място на възникване", "branch_class": "Отрасъл", "station": "Звено",
    "service": "Служба", "settlement": "Населено място", "municipality": "Община",
    "shift": "Дежурна смяна", "state": "Състояние", "object": "Обект", "location": "Населено място",
    "reason": "Причина", "unit": "Звено", "status": "Състояние", "casulaty": "Вид произшествие",
    "ucasulaty": "Вид обект", "region": "Община", "address": "Адрес",
}

CODE_TAIL = re.compile(r"\s*-\s*\d+\s*$")
CODE_HEAD = re.compile(r"^\s*\d+\s*-\s*")
SPACES = re.compile(r"\s+")
UNIT = re.compile(r"^\s*(РС|У)\s*ПБЗН\s*-?\s*(.*?)\s*$", re.I)


def clean(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return ""
    return SPACES.sub(" ", str(v)).strip()


def strip_code(v):
    return CODE_HEAD.sub("", CODE_TAIL.sub("", clean(v))).strip()


def signal_time(rec):
    """Date and time of the signal from `dat` ("YYYY-MM-DD HH:MM:SS"), or None."""
    s = clean(rec.get("dat"))
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return dt.datetime.strptime(s[:n], fmt)
        except ValueError:
            continue
    return None


def station(rec):
    m = UNIT.match(clean(rec.get("unit")) or clean(rec.get("subou")))
    if not m:
        return clean(rec.get("unit"))
    kind, place = m.group(1).upper(), m.group(2).strip(" -–")
    return f"{'РСПБЗН' if kind == 'РС' else 'УПБЗН'} – {place}"


def service(rec):
    m = UNIT.match(clean(rec.get("unit")) or clean(rec.get("subou")))
    if not m:
        return clean(rec.get("unit"))
    kind, place = m.group(1).upper(), m.group(2).strip(" -–")
    if kind == "У":
        place = STATION_TO_SERVICE.get(place, place)
    return f"РСПБЗН – {place}"


def settlement(rec):
    s = clean(rec.get("location"))
    s = re.sub(r"\s*,?\s*землището\s*$", "", s, flags=re.I)
    s = re.sub(r"^село\s+", "с. ", s, flags=re.I)
    s = re.sub(r"^(с|гр)\.\s*", lambda m: m.group(1).lower() + ". ", s, flags=re.I)
    return s.strip()


def settlement_key(label):
    return re.sub(r"^(с|гр)\.\s*", "", label).casefold()


# Official spellings where plain title case is wrong.
MUNICIPALITY_NAMES = {"червен бряг": "Червен бряг"}


def municipality(rec):
    s = clean(rec.get("region"))
    if not s:
        return ""
    return MUNICIPALITY_NAMES.get(s.casefold()) or " ".join(w[:1].upper() + w[1:].lower() for w in s.split(" "))


def virtual(rec, field):
    t = signal_time(rec)
    if field == "year":
        return f"{t:%Y}" if t else ""
    if field == "month":
        return f"{t:%Y-%m}" if t else ""
    if field == "month_of_year":
        return f"{t:%m} {MONTHS[t.month - 1]}" if t else ""
    if field == "date":
        return f"{t:%Y-%m-%d}" if t else ""
    if field == "weekday":
        return WEEKDAYS[t.weekday()] if t else ""
    if field == "hour":
        return f"{t:%H}" if t else ""
    if field == "kind":
        return strip_code(rec.get("casulaty")) or clean(rec.get("type"))
    if field == "cause":
        return strip_code(rec.get("reason"))
    if field == "object_class":
        return strip_code(rec.get("ucasulaty"))
    if field == "place_class":
        return strip_code(rec.get("place"))
    if field == "branch_class":
        return strip_code(rec.get("branch"))
    if field == "station":
        return station(rec)
    if field == "service":
        return service(rec)
    if field == "settlement":
        return settlement(rec)
    if field == "municipality":
        return municipality(rec)
    if field == "shift":
        return clean(rec.get("orderlyturn"))
    if field == "state":
        st = clean(rec.get("status"))
        return STATE_LABELS.get(st.lower(), st)
    raise KeyError(field)


def value(rec, field):
    if field in VIRTUAL:
        return virtual(rec, field)
    if field.startswith("detail."):
        d = rec.get("detail")
        return clean(d.get(field[7:])) if isinstance(d, dict) else ""
    return clean(rec.get(field))


def key_of(field, label):
    if field == "settlement":
        return settlement_key(label)
    return label.casefold()


def casualties(rec):
    d = rec.get("detail")
    text = clean(d.get("casualties")) if isinstance(d, dict) else ""
    return len(re.findall(r"Пострадал", text, re.I)), len(re.findall(r"Загинал", text, re.I))


def load(paths):
    rows, seen, dropped = [], set(), 0
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                payload = json.load(fh)
        except OSError as e:
            sys.exit(f"BAD_INPUT: cannot read {p}: {e.strerror}")
        except ValueError:
            sys.exit(f"BAD_INPUT: {p} is not valid JSON")
        if isinstance(payload, dict) and isinstance(payload.get("incidents"), list):
            payload = payload["incidents"]  # raw n8n response is accepted too
        if not isinstance(payload, list) or any(not isinstance(r, dict) for r in payload):
            sys.exit(f"BAD_INPUT: {p} must be a JSON array of records")
        for r in payload:
            rid = clean(r.get("id"))
            if rid:
                if rid in seen:
                    dropped += 1
                    continue
                seen.add(rid)
            rows.append(r)
    return rows, dropped


def check_field(field, rows):
    if field in VIRTUAL or field.startswith("detail."):
        return
    if not re.fullmatch(r"[A-Za-z0-9_]+", field) or (rows and not any(field in r for r in rows)):
        sys.exit(f"BAD_REQUEST: unknown field {field!r}; virtual fields: {', '.join(VIRTUAL)}")


class Labeler:
    """Groups spellings of one value under one key; the label is the most frequent spelling."""

    def __init__(self, field):
        self.field = field
        self.spellings = defaultdict(Counter)

    def key(self, rec):
        label = value(rec, self.field)
        if not label:
            return NO_DATA
        k = key_of(self.field, label)
        self.spellings[k][label] += 1
        return k

    def label(self, k):
        if k == NO_DATA:
            return NO_DATA
        best = sorted(self.spellings[k].items(), key=lambda x: (-x[1], x[0]))
        return best[0][0]


def empty_months(months):
    """Months between the first and the last record that have no records (data gaps)."""
    if not months:
        return []
    y, m = map(int, min(months).split("-"))
    last, gaps = max(months), []
    while f"{y:04d}-{m:02d}" < last:
        k = f"{y:04d}-{m:02d}"
        if k not in months:
            gaps.append(k)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return gaps


def sort_key(k):
    """Natural ascending order for compare columns (years, months, labels)."""
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in re.split(r"(\d+)", k)]


def stats(rows, group_by, compare_field=None, top=None, count_only=False, dropped=0, files=1):
    times = [t for t in (signal_time(r) for r in rows) if t]
    months = Counter(f"{t:%Y-%m}" for t in times)
    inj = dead = 0
    for r in rows:
        i, d = casualties(r)
        inj, dead = inj + i, dead + d

    cmp_lab = Labeler(compare_field) if compare_field else None
    cmp_keys = [cmp_lab.key(r) for r in rows] if cmp_lab else [None] * len(rows)
    cmp_total = Counter(k for k in cmp_keys if k is not None)
    cmp_order = sorted(cmp_total, key=lambda k: sort_key(cmp_lab.label(k))) if cmp_lab else []

    out = {
        "records_read": len(rows),
        "files": files,
        "duplicates_dropped": dropped,
        "period": {
            "first": f"{min(times):%Y-%m-%d}" if times else None,
            "last": f"{max(times):%Y-%m-%d}" if times else None,
            "months": {m: months[m] for m in sorted(months)},
            "empty_months": empty_months(months),
        },
        "total": len(rows),
        "casualties": {"injured": inj, "dead": dead},
        "group_by": group_by,
        "compare_field": compare_field,
        "compare_values": [cmp_lab.label(k) for k in cmp_order] if cmp_lab else [],
        "total_by_compare": {cmp_lab.label(k): cmp_total[k] for k in cmp_order} if cmp_lab else {},
    }
    if len(cmp_order) == 2:
        out["total_change"] = cmp_total[cmp_order[1]] - cmp_total[cmp_order[0]]
    if count_only or not group_by:
        return out

    labelers = [Labeler(f) for f in group_by]
    count, by_cmp, cas = Counter(), defaultdict(Counter), defaultdict(lambda: [0, 0])
    for r, ck in zip(rows, cmp_keys):
        g = tuple(lab.key(r) for lab in labelers)
        count[g] += 1
        if ck is not None:
            by_cmp[g][ck] += 1
        i, d = casualties(r)
        cas[g][0] += i
        cas[g][1] += d

    def labels(g):
        return [lab.label(k) for lab, k in zip(labelers, g)]

    ordered = sorted(count, key=lambda g: (-count[g], [s.casefold() for s in labels(g)]))
    kept, rest = (ordered[:top], ordered[top:]) if top else (ordered, [])
    groups = []
    for g in kept:
        item = {"key": labels(g), "count": count[g]}
        if cmp_lab:
            item["by_compare"] = {cmp_lab.label(k): by_cmp[g][k] for k in cmp_order}
            if len(cmp_order) == 2:
                item["change"] = by_cmp[g][cmp_order[1]] - by_cmp[g][cmp_order[0]]
        item["injured"], item["dead"] = cas[g]
        groups.append(item)
    out["groups_count"] = len(ordered)
    out["groups"] = groups
    out["top"] = top
    if rest:
        other = {"groups": len(rest), "count": sum(count[g] for g in rest)}
        if cmp_lab:
            other["by_compare"] = {cmp_lab.label(k): sum(by_cmp[g][k] for g in rest) for k in cmp_order}
        out["other"] = other
    return out


def truncated(paths):
    """Files that fetch_incidents.py marked as cut short (`<file>.meta.json` with "truncated": true)."""
    out = []
    for p in paths:
        try:
            with open(p + ".meta.json", encoding="utf-8") as fh:
                m = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(m, dict) and m.get("truncated"):
            out.append({"file": os.path.basename(p), "returned": m.get("returned"), "total": m.get("total")})
    return out


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Counts and groupings over pleven-fire-incidents records.")
    ap.add_argument("records", nargs="+", help="JSON file(s) from fetch_incidents.py -o")
    ap.add_argument("--group-by", action="append", default=[], metavar="FIELD",
                    help="field to group by (once or twice)")
    ap.add_argument("--compare-field", metavar="FIELD", help="field whose values become columns")
    ap.add_argument("--top", type=int, metavar="N", help="keep only the N largest groups")
    ap.add_argument("--count-only", action="store_true", help="totals only, no groups")
    ap.add_argument("-o", "--output", help="also write the JSON result to this file")
    a = ap.parse_args(argv)
    a.group_by = [g.strip() for g in a.group_by if g and g.strip()]
    a.compare_field = (a.compare_field or "").strip() or None
    if len(a.group_by) > 2:
        sys.exit("BAD_REQUEST: --group-by can be given at most twice")
    if a.top is not None and a.top < 1:
        sys.exit("BAD_REQUEST: --top must be 1 or more")
    return a


def main(argv=None):
    a = parse_args(argv)
    rows, dropped = load(a.records)
    for f in a.group_by + ([a.compare_field] if a.compare_field else []):
        check_field(f, rows)
    result = stats(rows, a.group_by, a.compare_field, a.top, a.count_only, dropped, len(a.records))
    cut = truncated(a.records)
    if cut:   # fetch_incidents.py left a note: the file holds fewer records than the period has
        result["truncated"] = cut
        result["warning"] = ("НЕПЪЛНИ ДАННИ: файлът съдържа по-малко записи, отколкото има за периода – "
                             "числата са занижени. Свали периода на части или с по-голям --limit.")
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if a.output:
        with open(a.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
