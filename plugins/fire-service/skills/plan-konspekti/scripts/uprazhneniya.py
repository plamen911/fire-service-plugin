#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uprazhneniya.py — упражненията по пожаро-строева подготовка от Специализираната методика
(заповед № 8121з-1702/09.12.2022 г.): име, вид, описание, скала секунди → точки (за време) или
карта с точки по действия (за правилно изпълнение), цел и материално осигуряване.

Данните не са в пакета. Стоят в нормативната база (Google Drive, tier-b), файл
`MVR_Methodology_Spetsializirana-Metodika-Pozharo-Stroeva-Podgotovka_2022_Uprazhneniya.json`, и се четат
през n8n с личния ключ. Текстът на методиката е в tier-a (…_2022_ed2022-12-09.md), а приложенията ѝ –
в tier-b (…_Appendices.md); те се четат със скила normativna-uredba.

    python3 scripts/uprazhneniya.py spisak                 # номер, вид и име на всички упражнения
    python3 scripts/uprazhneniya.py get "1.9 Б"            # едно упражнение (JSON)
    python3 scripts/uprazhneniya.py get 1.1 --file f.json   # от записан файл (тестове)

Без ключ (колега с конектора Fire Service) скриптът спира с NO_KEY. Тогава упражнението се взима с
`regs_list` (name: "Spetsializirana-Metodika", файлът …_Appendices.md) и `regs_read` с
match: "Упражнение № 1.9 Б", и се подава на build_konspekt.py като свой текст в "tema2"
("tekst", "tsel_uvod", "tsel", "materialno", "opisanie"), а на build_otchet.py – с "tochki".

Грешки (на stderr, код ≠ 0):
    NO_KEY: ...           — няма личен ключ (виж по-горе)
    NOT_FOUND: ...        — няма такова упражнение или файлът не е в базата
    N8N_UNAVAILABLE: ...  — n8n не отговаря → опитай веднъж отново
"""
import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_shared", "scripts"))
NAME = "Spetsializirana-Metodika-Pozharo-Stroeva-Podgotovka_2022_Uprazhneniya.json"
CACHE = os.path.join(tempfile.gettempdir(), "fire_service_uprazhneniya.json")
CACHE_SECONDS = 600


def _fetch():
    import api_config
    if api_config.has_key():
        try:
            if time.time() - os.path.getmtime(CACHE) < CACHE_SECONDS:
                with open(CACHE, encoding="utf-8") as f:
                    return f.read()
        except OSError:
            pass
    try:
        files = api_config.post("regs_url", {"action": "list"}).get("files") or []
        hit = [f for f in files if (f.get("name") or "").endswith(NAME)]
        if not hit:
            sys.exit(f"NOT_FOUND: в нормативната база няма файла с упражненията ({NAME})")
        text = api_config.post("regs_url", {"action": "download", "id": hit[0]["id"]})["content"]
    except urllib.error.HTTPError as e:
        sys.exit(f"N8N_UNAVAILABLE: HTTP {e.code}")
    except (OSError, KeyError, ValueError) as e:
        sys.exit(f"N8N_UNAVAILABLE: {type(e).__name__}: {e}"[:300])
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass
    return text


def load(path=None):
    """The data file: {"metodika", "po_podrazbirane", "uprazhneniya": {number: {...}}}, references resolved."""
    path = path or os.environ.get("FIRE_SERVICE_UPRAZHNENIYA")
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            sys.exit(f"BAD_INPUT: файлът с упражненията не се чете: {e}")
    else:
        text = _fetch()
    try:
        d = json.loads(text)
    except ValueError:
        sys.exit("N8N_UNAVAILABLE: файлът с упражненията не е валиден JSON")

    def deref(v):
        return d[v[1:]] if isinstance(v, str) and v.startswith("@") else v
    for ex in d["uprazhneniya"].values():
        for key in ("tsel_uvod", "tsel", "materialno"):
            ex[key] = deref(ex.get(key))
    return d


def main():
    ap = argparse.ArgumentParser(description="Упражненията по ПСП от методиката")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("spisak")
    p.add_argument("--file")
    p = sub.add_parser("get")
    p.add_argument("nomer")
    p.add_argument("--file")
    a = ap.parse_args()
    d = load(a.file)
    if a.cmd == "spisak":
        rows = [{"nomer": k, "vid": e["vid"], "ime": e["ime"]} for k, e in d["uprazhneniya"].items()]
        print(json.dumps({"metodika": d["metodika"], "broi": len(rows), "uprazhneniya": rows}, ensure_ascii=False, indent=1))
        return
    ex = d["uprazhneniya"].get(a.nomer.strip())
    if ex is None:
        sys.exit(f"NOT_FOUND: няма упражнение „{a.nomer}“ – виж `uprazhneniya.py spisak`")
    print(json.dumps({"nomer": a.nomer.strip(), "metodika": d["metodika"], **ex}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
