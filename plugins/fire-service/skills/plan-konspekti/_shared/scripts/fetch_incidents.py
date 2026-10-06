#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_incidents.py — произшествия от базата pleven-fire-incidents като JSON масив.

Копие от plugins/fire-service/shared/scripts/ — редактирай източника.

Употреба:
    python3 fetch_incidents.py ГГГГ-ММ-ДД                         # един ден, през n8n
    python3 fetch_incidents.py --from 2026-09-01 --to 2026-09-24  # период (до 366 дни)
    python3 fetch_incidents.py 2026-09-24 --all --filter location=Опанец --filter object=кола
    python3 fetch_incidents.py 2026-09-24 --sort dat:asc --limit 20
    python3 fetch_incidents.py --from 2026-01-01 --to 2026-09-30 --all -o records.json

Параметри (липсващ или празен параметър се пропуска):
    --from/--to     период; без --to = само един ден
    --all           всички видове произшествия, не само пожари с преки материални загуби
    --filter k=v    съдържа v (без значение от главни/малки букви); повторен за същото поле = ИЛИ,
                    за различни полета = И. Филтър и сортиране – по всяко поле на записа.
    --sort f:dir    по подразбиране dat:desc — най-новите първи
    --limit N       по подразбиране 500, най-много 5000
    -o/--output F   записва масива във файла F (вход за други скриптове, напр. incident_stats.py),
                    а на stdout отпечатва само кратко резюме
                    {"output", "from", "to", "returned", "total", "truncated"}

Скриптът пита само n8n endpoint-а от ../incident_api.json — работи отвсякъде, включително
от телефона. Паролата за Firebase стои само в n8n; пряк достъп до базата няма.

Изход: JSON масив на stdout (или във файла от -o). Ако записите са повече от лимита, на stderr излиза
    TRUNCATED: returned N of TOTAL

Грешки (на stderr, код ≠ 0):
    BAD_REQUEST: ...            — невалидна дата, период или поле за филтър
    N8N_UNAVAILABLE: ...        — n8n не отговаря или върна грешка → опитай веднъж отново
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request

FIRE = "пожар с преки материални загуби-01"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api_config  # noqa: E402  (addresses of n8n and the personal key)


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", help="ГГГГ-ММ-ДД (същото като --from)")
    ap.add_argument("--from", dest="date_from", help="начало на периода ГГГГ-ММ-ДД")
    ap.add_argument("--to", dest="date_to", help="край на периода ГГГГ-ММ-ДД (по подразбиране = началото)")
    ap.add_argument("--all", action="store_true", help="всички видове произшествия")
    ap.add_argument("--filter", action="append", default=[], metavar="ПОЛЕ=СТОЙНОСТ")
    ap.add_argument("--sort", default="dat:desc", help="поле:asc|desc (по подразбиране dat:desc)")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("-o", "--output", help="запиши масива в този файл; на stdout – само резюме")
    a = ap.parse_args(argv)

    a.date_from = (a.date_from or a.date or "").strip()
    a.date_to = (a.date_to or "").strip() or a.date_from
    try:
        d1 = dt.date.fromisoformat(a.date_from)
        d2 = dt.date.fromisoformat(a.date_to)
    except ValueError:
        sys.exit("BAD_REQUEST: дата във формат ГГГГ-ММ-ДД е задължителна")
    if d2 < d1:
        sys.exit("BAD_REQUEST: --to е преди --from")
    if (d2 - d1).days > 366:
        sys.exit("BAD_REQUEST: периодът е най-много 366 дни")

    filters = {}
    for f in a.filter:
        k, sep, v = f.partition("=")
        k, v = k.strip(), v.strip()
        if not sep or not k:
            sys.exit(f"BAD_REQUEST: --filter иска ПОЛЕ=СТОЙНОСТ, получи {f!r}")
        if not v:
            continue  # празен филтър се пропуска
        if not re.fullmatch(r"[A-Za-z0-9_]+", k):
            sys.exit(f"BAD_REQUEST: невалидно поле {k!r}")
        filters.setdefault(k, []).append(v)
    a.filters = filters

    field, _, order = (a.sort or "dat:desc").partition(":")
    a.sort_field = field.strip() if re.fullmatch(r"[A-Za-z0-9_]+", field.strip()) else "dat"
    a.sort_order = "asc" if order.strip().lower() == "asc" else "desc"
    a.limit = min(a.limit, 5000) if a.limit and a.limit > 0 else 500
    return a


def via_n8n(a):
    body = {"from": a.date_from, "to": a.date_to, "all": a.all, "filters": a.filters,
            "sort": f"{a.sort_field}:{a.sort_order}", "limit": a.limit}
    try:
        res = api_config.post("url", body)
    except urllib.error.HTTPError as e:
        sys.exit(f"N8N_UNAVAILABLE: HTTP {e.code} {e.read().decode(errors='ignore')[:200]}")
    except (OSError, KeyError, ValueError) as e:
        sys.exit(f"N8N_UNAVAILABLE: {type(e).__name__}: {e}"[:300])
    if isinstance(res, list):  # по-стара версия на workflow-а
        return select(res, a)
    if not isinstance(res, dict) or not isinstance(res.get("incidents"), list):
        sys.exit("N8N_UNAVAILABLE: unexpected response shape")
    return res["incidents"], res.get("total", len(res["incidents"]))


def select(rows, a):
    """Same rules as the n8n "Filter & format" node: filter, sort, limit."""
    if not a.all:
        rows = [r for r in rows if r.get("casulaty") == FIRE]
    for k, vals in a.filters.items():
        vals = [v.lower() for v in vals]
        rows = [r for r in rows
                if str(r.get(k) or "") and any(v in str(r.get(k) or "").lower() for v in vals)]
    rows.sort(key=lambda r: (str(r.get(a.sort_field) or ""), str(r.get("id") or "")),
              reverse=a.sort_order == "desc")
    return rows[:a.limit], len(rows)


def main():
    a = parse_args()
    rows, total = via_n8n(a)
    if total > len(rows):
        print(f"TRUNCATED: returned {len(rows)} of {total}", file=sys.stderr)
    if a.output:
        with open(a.output, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1)
        print(json.dumps({"output": a.output, "from": a.date_from, "to": a.date_to,
                          "returned": len(rows), "total": total, "truncated": total > len(rows)},
                         ensure_ascii=False))
        return
    print(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
