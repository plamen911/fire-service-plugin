#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plan_grafik.py — годишният план-график за занятията на инспекторите от група „Оперативен център“:
кой, кога, в кои звена и на каква тема провежда занятие.

План-графикът е справочен файл в нормативната база (Google Drive, папка tier-c):
`RDPBZN-Pleven_Plan_Plan-Grafik-Zanyatiya-Inspektori-OC_<година>.md`. Чете се през n8n с личния ключ
(`regs_url` в `_shared/incident_api.json`). Без ключ (колега с конектора Fire Service) файлът се
взима с инструментите `regs_list` (name: "Plan-Grafik") и `regs_read`, записва се и се подава с --file.

    python3 scripts/plan_grafik.py mesec 2026-10                    # занятията през месеца
    python3 scripts/plan_grafik.py mesec 2026-10 --ime "Иван Петров" # само на този инспектор
    python3 scripts/plan_grafik.py godina 2026                       # всички въведени занятия
    python3 scripts/plan_grafik.py mesec 2026-10 --file grafik.md    # от записан файл (конектор, тестове)

Отпечатва JSON: {"godina", "reg", "plan_grafik", "zanyatiya": [{"mesec", "data", "provezhdasht",
"zvena": ["РСПБЗН – …"], "tema", "praktika"}], "belezhka"}. "plan_grafik" е готовият текст за
полето "plan_grafik" на build_konspekt.py. Празна "data" значи, че месечният лист с датите още не е
въведен – попитай потребителя за датата.

Грешки (на stderr, код ≠ 0):
    NO_KEY: ...           — няма личен ключ → вземи файла с regs_list/regs_read и подай --file
    NOT_FOUND: ...        — за тази година няма въведен план-график → работи със свободна тема
    N8N_UNAVAILABLE: ...  — n8n не отговаря → опитай веднъж отново
    BAD_INPUT: ...        — неправилен месец или година
"""
import argparse
import json
import os
import re
import sys
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_shared", "scripts"))
NAME = "Plan-Grafik-Zanyatiya-Inspektori-OC_{year}.md"
MONTHS = ["януари", "февруари", "март", "април", "май", "юни", "юли", "август", "септември", "октомври",
          "ноември", "декември"]


def n(s):
    return re.sub(r"\s+", " ", (s or "").lower().replace("ѝ", "й")).strip()


def fetch(year):
    import api_config
    name = NAME.format(year=year)
    try:
        files = api_config.post("regs_url", {"action": "list"}).get("files") or []
        hit = [f for f in files if (f.get("name") or "").endswith(name)]
        if not hit:
            sys.exit(f"NOT_FOUND: за {year} г. няма въведен план-график ({name}) – работи със свободна тема")
        return api_config.post("regs_url", {"action": "download", "id": hit[0]["id"]})["content"]
    except urllib.error.HTTPError as e:
        sys.exit(f"N8N_UNAVAILABLE: HTTP {e.code}")
    except (OSError, KeyError, ValueError) as e:
        sys.exit(f"N8N_UNAVAILABLE: {type(e).__name__}: {e}"[:300])


def parse(text):
    meta = dict(re.findall(r"^- ([a-z_]+):\s*(.+?)\s*$", text, re.M))
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 6 or n(cells[0]) not in MONTHS:
            continue
        rows.append({"mesec": n(cells[0]), "data": (cells[1] + " г.") if cells[1] else "",
                     "provezhdasht": cells[2],
                     "zvena": [z.strip() for z in cells[3].split(";") if z.strip()],
                     "tema": cells[4], "praktika": cells[5]})
    return meta, rows


def same_person(short, full):
    """„Ив.Петров“ ~ „Иван Петров“: same surname and the first name starts with the abbreviation."""
    parts = n(full).split()
    if not parts:
        return True
    m = re.match(r"^\s*([^.\s]+)\.?\s*(\S+)\s*$", n(short))
    if not m:
        return parts[-1] in n(short)
    return m.group(2) == parts[-1] and (len(parts) == 1 or parts[0].startswith(m.group(1)))


def main():
    ap = argparse.ArgumentParser(description="План-график за занятията на инспекторите от ОЦ")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd, arg, hlp in (("mesec", "mesec", "ГГГГ-ММ"), ("godina", "godina", "ГГГГ")):
        p = sub.add_parser(cmd)
        p.add_argument(arg, help=hlp)
        p.add_argument("--ime", help="само занятията на този инспектор (име и фамилия)")
        p.add_argument("--file", help="записан файл на план-графика вместо n8n")
    a = ap.parse_args()
    if a.cmd == "mesec":
        m = re.fullmatch(r"(\d{4})-(\d{1,2})", a.mesec.strip())
        if not m or not 1 <= int(m.group(2)) <= 12:
            sys.exit("BAD_INPUT: месецът е във вид ГГГГ-ММ, напр. 2026-10")
        year, month = m.group(1), MONTHS[int(m.group(2)) - 1]
    else:
        if not re.fullmatch(r"\d{4}", a.godina.strip()):
            sys.exit("BAD_INPUT: годината е във вид ГГГГ")
        year, month = a.godina.strip(), None
    if a.file:
        try:
            with open(a.file, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            sys.exit(f"BAD_INPUT: файлът не се чете: {e}")
    else:
        text = fetch(year)
    meta, rows = parse(text)
    if meta.get("godina") and meta["godina"] != year:
        sys.exit(f"NOT_FOUND: файлът е за {meta['godina']} г., а не за {year} г.")
    rows = [r for r in rows if (month is None or r["mesec"] == month) and (not a.ime or same_person(r["provezhdasht"], a.ime))]
    reg = meta.get("reg", "")
    print(json.dumps({"godina": year, "reg": reg, "plan_grafik": reg, "zanyatiya": rows,
                      "belezhka": meta.get("belezhka", "")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
