#!/usr/bin/env python3
"""
koya_sluzhba.py — коя служба на ГДПБЗН обслужва дадено населено място.

Източник: Заповед № 8121з-208/16.02.2026 г. на министъра на вътрешните работи за районите
на действие на териториалните звена на ГДПБЗН, вързана към ЕКАТТЕ 2025 (НСИ). Таблицата
(`naseleni_mesta.csv`) и текстът на заповедта (`zapoved_8121z-208_2026.md`) не са в пакета –
пазят се в Google Drive и се четат през n8n с личния ключ (кешират се за едно денонощие).
Без ключ (колега с конектора Fire Service) скриптът спира с `NO_KEY`: тогава редовете идват от
инструмента `raioni` – запиши `header` и `rows` във файл и го подай с `--csv ФАЙЛ`.

    python3 _shared/scripts/koya_sluzhba.py --tekst "Тракия"                # редове от текста на заповедта

    python3 _shared/scripts/koya_sluzhba.py Крушовене
    python3 _shared/scripts/koya_sluzhba.py "с. Ново село" --oblast Русе
    python3 _shared/scripts/koya_sluzhba.py Изгрев --obshtina Венец
    python3 _shared/scripts/koya_sluzhba.py --sluzhba "РСПБЗН – Кнежа"      # всички места на службата
    python3 _shared/scripts/koya_sluzhba.py --obshtina "Долна Митрополия"   # цялата община
    python3 _shared/scripts/koya_sluzhba.py --sod Монтана                   # района на сектор СОД
    python3 _shared/scripts/koya_sluzhba.py Крушовене --json

Търсенето не прави разлика между главни и малки букви, „ѝ/й“, „гр./с.“ пред името и
тирета. Ако името не се намери точно, показва най-близките съвпадения.
"""
import argparse
import csv
import difflib
import io
import json
import os
import re
import sys
import tempfile
import time
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import api_config  # noqa: E402  (addresses of n8n and the personal key)

TABLE, ORDER = "naseleni_mesta.csv", "zapoved_8121z-208_2026.md"
CACHE_SECONDS = 24 * 3600
# A CSV to read instead of asking n8n: tests, and rows saved from the connector tool `raioni`.
CSV_FILE = os.environ.get("FIRE_SERVICE_RAIONI_CSV") or None


def remote(name):
    """A file of the kind "raioni" from n8n, cached for a day."""
    cache = os.path.join(tempfile.gettempdir(), "fire_service_" + name)
    if not api_config.has_key():  # the cached copy is for the key's owner only
        sys.exit(api_config.NO_KEY + " – инструментът raioni")
    try:
        if time.time() - os.path.getmtime(cache) < CACHE_SECONDS:
            with open(cache, encoding="utf-8") as f:
                return f.read()
    except OSError:
        pass
    try:
        text = api_config.post("samples_url", {"action": "get", "kind": "raioni", "name": name}, timeout=120)["text"]
    except urllib.error.HTTPError as e:
        sys.exit(f"N8N_UNAVAILABLE: HTTP {e.code} {e.read().decode(errors='ignore')[:200]}")
    except (OSError, KeyError, ValueError) as e:
        sys.exit(f"N8N_UNAVAILABLE: {type(e).__name__}: {e}"[:300])
    try:
        api_config.write_private(cache, text)
    except OSError:
        pass
    return text


def norm(s):
    s = (s or "").strip().lower().replace("ѝ", "й").replace("–", "-").replace("—", "-")
    s = re.sub(r"^(гр|с|град|село|ман)\.?\s+", "", s)
    s = re.sub(r"^(общ|община|обл|област)\.?\s+", "", s)
    return re.sub(r"[\s\-]+", " ", s).strip()


def load():
    if CSV_FILE:
        with open(CSV_FILE, encoding="utf-8") as f:
            return list(csv.DictReader(f))
    return list(csv.DictReader(io.StringIO(remote(TABLE))))


def tekst(query, context=2):
    """Lines of the order that contain the text, with a few lines around and the heading above."""
    lines, q, keep = remote(ORDER).split("\n"), query.lower(), set()
    for i, line in enumerate(lines):
        if q in line.lower():
            keep.update(range(max(0, i - context), min(len(lines), i + context + 1)))
    out, prev = [], -2
    for i in sorted(keep):
        if i != prev + 1:
            if out:
                out.append("…")
            head = next((lines[j] for j in range(i, -1, -1) if re.match(r"^#{1,4}\s", lines[j])), "")
            if head and head != lines[i]:
                out.append(head)
        out.append(lines[i])
        prev = i
    return "\n".join(out)


def fmt(r):
    lines = [f'{r["vid"]} {r["naseleno_masto"]}, общ. {r["obshtina"]}, обл. {r["oblast"]} (ЕКАТТЕ {r["ekatte"]})',
             f'  → {r["sluzhba"]}' + (f' / {r["uchastak"]}' if r["uchastak"] else "") + f' ({r["rdpbzn"]})',
             f'  основание: {r["osnovanie"]}']
    if r["belezhka"]:
        lines.append(f'  бележка: {r["belezhka"]}')
    if r.get("sektor_sod"):
        lines.append(f'  сектор СОД: {r["sektor_sod"]}')
    return "\n".join(lines)


PLEVEN = "РДПБЗН – Плевен"


def spravka(a, rows):
    """Коя РСПБЗН на РДПБЗН – Плевен е по мястото на пожара. Каквото не се определя
    еднозначно (няма такова място, няколко с това име, извън РДПБЗН – Плевен) → ПЛЕВЕН."""
    rows = [r for r in rows if r["rdpbzn"] == PLEVEN]
    hit = []
    if a.ime:
        q = norm(a.ime)
        hit = [r for r in rows if norm(r["naseleno_masto"]) == q]
        if not hit:
            names = sorted({r["naseleno_masto"] for r in rows})
            close = difflib.get_close_matches(a.ime.strip(), names, n=3, cutoff=0.85)
            hit = [r for r in rows if r["naseleno_masto"] in close]
    # --obshtina само стеснява намереното: в базата `region` е обикновено общината, но
    # понякога службата („с. Одърне“ → ЛЕВСКИ, а селото е в общ. Пордим)
    if a.obshtina and len({r["sluzhba"] for r in hit}) > 1:
        o = norm(a.obshtina)
        hit = ([r for r in hit if norm(r["obshtina"]) == o]
               or [r for r in hit if norm(r["sluzhba"]).endswith(o)] or hit)
    sl = {r["sluzhba"] for r in hit}
    if len(sl) == 1:
        r = hit[0]
        out = {"unit": r["sluzhba"].split("– ", 1)[1].upper(), "sluzhba": r["sluzhba"],
               "uchastak": r["uchastak"] if len(hit) == 1 else "",
               "naseleno_masto": f'{r["vid"]} {r["naseleno_masto"]}' if len(hit) == 1 else "",
               "obshtina": r["obshtina"] if len(hit) == 1 else "",
               "belezhka": r["belezhka"] if len(hit) == 1 else "", "osnova": "по мястото"}
    else:
        why = "няма такова място в РДПБЗН – Плевен" if not hit else "няколко служби за това име"
        out = {"unit": "ПЛЕВЕН", "sluzhba": "РСПБЗН – Плевен", "uchastak": "", "naseleno_masto": "",
               "obshtina": "", "belezhka": "", "osnova": f"по подразбиране ({why})"}
    print(json.dumps(out, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ime", nargs="?", help="населено място")
    ap.add_argument("--obshtina")
    ap.add_argument("--oblast")
    ap.add_argument("--sluzhba", help="списък на населените места на служба/участък")
    ap.add_argument("--sod", help="списък на населените места на сектор СОД (напр. Монтана)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--spravka", action="store_true",
                    help="районната служба за справка/документ на РДПБЗН – Плевен; иначе ПЛЕВЕН")
    ap.add_argument("--tekst", metavar="ТЕКСТ", help="редовете от текста на заповедта, които съдържат този текст")
    ap.add_argument("--context", type=int, default=2, help="редове около всяко съвпадение при --tekst")
    ap.add_argument("--csv", metavar="ФАЙЛ", help="таблица вместо n8n (header и rows от инструмента raioni)")
    a = ap.parse_args()
    global CSV_FILE
    if a.csv:
        CSV_FILE = a.csv
    if a.tekst:
        found = tekst(a.tekst, max(0, min(a.context, 10)))
        print(found or f"NOT_FOUND: „{a.tekst}“ не се среща в текста на заповедта")
        return
    rows = load()
    if a.spravka:
        return spravka(a, rows)

    if a.oblast:
        rows = [r for r in rows if norm(r["oblast"]) == norm(a.oblast)]
    if a.obshtina:
        rows = [r for r in rows if norm(r["obshtina"]) == norm(a.obshtina)]
    if a.sluzhba:
        q = norm(a.sluzhba)
        rows = [r for r in rows if q in norm(r["sluzhba"]) or q in norm(r["uchastak"])]
    if a.sod:
        q = norm(a.sod)
        rows = [r for r in rows if q in norm(r["sektor_sod"])]
    if a.ime:
        q = norm(a.ime)
        hit = [r for r in rows if norm(r["naseleno_masto"]) == q]
        if not hit:
            names = sorted({r["naseleno_masto"] for r in rows})
            close = difflib.get_close_matches(a.ime.strip(), names, n=6, cutoff=0.75)
            hit = [r for r in rows if r["naseleno_masto"] in close]
            if hit and not a.json:
                print(f"Няма точно съвпадение за „{a.ime}“. Най-близки:")
        rows = hit
    elif not (a.sluzhba or a.sod or a.obshtina or a.oblast):
        ap.error("дай населено място или --sluzhba / --sod / --obshtina / --oblast")

    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return
    if not rows:
        print("NOT_FOUND: няма такова населено място в ЕКАТТЕ (провери името, общината или областта)")
        sys.exit(2)
    if a.ime:
        print("\n\n".join(fmt(r) for r in rows))
        if len(rows) > 1:
            print(f"\n{len(rows)} населени места с това име — уточни общината/областта.")
    elif a.sod:
        by = {}
        for r in rows:
            by.setdefault((r["oblast"], r["obshtina"]), 0)
            by[(r["oblast"], r["obshtina"])] += 1
        for (obl, ob), n in sorted(by.items()):
            print(f"обл. {obl}, общ. {ob} – {n} нас. места")
        print(f"\n{len(rows)} населени места в {len(by)} общини (частични общини – виж текста на заповедта)")
    else:
        for r in rows:
            print(f'{r["vid"]} {r["naseleno_masto"]} (общ. {r["obshtina"]}) → {r["sluzhba"]}'
                  + (f' / {r["uchastak"]}' if r["uchastak"] else "") + f' | {r["sektor_sod"]}')
        print(f"\n{len(rows)} населени места")


if __name__ == "__main__":
    main()
