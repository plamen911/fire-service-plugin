#!/usr/bin/env python3
"""Tests for _shared/scripts/grafik.py (idempotent import, roster matching, duty and holiday queries)
and scripts/izrezki.py. Everything runs on a local store (--store) with invented people; n8n is not called."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.abspath(os.path.join(SKILL, "..", "..", "..", ".."))
SCRIPT = os.path.join(SKILL, "_shared", "scripts", "grafik.py")
FIX = os.path.join(SKILL, "tests", "fixtures")
OC = os.path.join(FIX, "2026-10_oc.json")
RS = os.path.join(FIX, "2026-10_rspbzn-pleven.json")
STAFF = os.path.join(ROOT, "tests", "fixtures", "staff.csv")
BASE = {k: v for k, v in os.environ.items() if not k.startswith("FIRE_SERVICE_")}
ENV = dict(BASE, FIRE_SERVICE_NO_KEY="1", FIRE_SERVICE_AZ="Иван Дъбов", FIRE_SERVICE_STAFF_CSV=STAFF)
NO_ROSTER = dict(BASE, FIRE_SERVICE_NO_KEY="1")


def run(store, *args, env=ENV, before=()):
    cmd = [sys.executable, SCRIPT] + (["--store", store] if store else []) + list(before) + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return r.returncode, r.stdout


def js(store, *args, **kw):
    code, text = run(store, *args, **kw)
    return code, json.loads(text)


def reading(tmp, name, doc):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return path


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_import(tmp, store):
    month = os.path.join(store, "oc", "2026-10.json")

    # dry run writes nothing
    code, r = js(store, "import", OC, "--dry-run")
    assert code == 0 and r["ok"] and r["changed"] and not r["written"], r
    assert not os.path.exists(month)

    # first import: everyone added and matched to the roster
    code, r = js(store, "import", OC)
    assert code == 0 and r["written"] and len(r["added"]) == 6 and not r["unmatched"] and not r["approx"], r
    first = sha(month)
    assert first == r["sha256"]

    # idempotent: the same reading again changes nothing, byte for byte
    code, r = js(store, "import", OC)
    assert code == 0 and not r["changed"] and not r["written"] and r["unchanged"] == 6, r
    assert not r["added"] and not r["updated"] and not r["removed"]
    assert sha(month) == first

    # the second schedule: all in the roster
    doc = json.load(open(RS, encoding="utf-8"))
    code, r = js(store, "import", RS)
    assert code == 0 and len(r["added"]) == 8 and not r["unmatched"] and not r["approx"], r
    rs_month = os.path.join(store, "rspbzn-pleven", "2026-10.json")
    rs_sha = sha(rs_month)
    # the order of rows and of keys in the reading does not matter
    shuffled = dict(doc, redove=[dict(reversed(list(row.items()))) for row in reversed(doc["redove"])])
    code, r = js(store, "import", reading(tmp, "shuffled.json", shuffled))
    assert code == 0 and not r["changed"], r
    assert sha(rs_month) == rs_sha

    # the codes of this schedule are kept as they are: the typeface is part of the code
    stored = {row["nomer"]: row for row in json.load(open(rs_month, encoding="utf-8"))["sluzhiteli"]}
    assert stored[2]["dni"] == {"Д": [3, 7, 11, 19, 23, 27, 31], "К": [14, 15, 16]}, stored[2]
    assert stored[3]["dni"] == {"Д": [4, 28], "Д-ДМ": [8, 12, 16, 24]}, stored[3]
    assert stored[6]["dni"] == {"Д-С": [4, 8, 12, 16, 20, 24, 28], "8о": [1]}, stored[6]
    assert stored[7]["dni"] == {"Д12": [1, 2, 5, 6, 9, 10, 13, 14, 21, 22, 25, 26, 29, 30]}, stored[7]
    assert stored[5]["dni"]["Бд"] == [1, 5] and stored[5]["dni"]["Б"] == [2, 6, 7, 8], stored[5]

    # a partial page updates only its own people
    page = {"grafik": "rspbzn-pleven", "mesec": "2026-10", "redove": [
        {"nomer": 1, "ime": "Бранимир Христов Елхов", "dni": {"Д": [7, 11, 15, 19, 23, 27], "Б": [31]}}]}
    code, r = js(store, "import", reading(tmp, "page.json", page))
    assert code == 0 and r["updated"] == ["Бранимир Христов Елхов"] and r["redove_v_mesetsa"] == 8, r
    code, r = js(store, "import", RS)  # … and the original page restores the original file
    assert code == 0 and r["updated"] == ["Бранимир Христов Елхов"] and sha(rs_month) == rs_sha, r

    # same row number, another name = correction of a misread name: the old row is replaced
    wrong = {"grafik": "rspbzn-pleven", "mesec": "2026-10", "redove": [
        {"nomer": 1, "ime": "Бранимир Петров Непознат", "dni": {"Д": [7]}}]}
    code, r = js(store, "import", reading(tmp, "wrong.json", wrong))
    assert code == 0 and r["removed"] == ["Бранимир Христов Елхов"], r
    assert r["unmatched"] and r["unmatched"][0]["ime"] == "Бранимир Петров Непознат", r
    code, r = js(store, "import", RS)
    assert code == 0 and r["removed"] == ["Бранимир Петров Непознат"] and sha(rs_month) == rs_sha, r

    # --replace drops the people that are not in the reading
    code, r = js(store, "import", reading(tmp, "page2.json", page), "--replace")
    assert code == 0 and len(r["removed"]) == 7 and r["redove_v_mesetsa"] == 1, r
    js(store, "import", RS)
    assert sha(rs_month) == rs_sha

    # approximate name: one wrong letter still finds the person and stores the roster name;
    # the Excel schedule accepts its codes in either letter case
    approx = {"grafik": "oc", "mesec": "2026-11", "redove": [
        {"ime": "Мариан Петров Липов", "dni": {"д": "4, 8"}}, {"ime": "Иван Дъбов", "dni": {}}]}
    code, r = js(store, "import", reading(tmp, "approx.json", approx))
    assert code == 0 and r["approx"] == [{"v_grafika": "Мариан Петров Липов", "v_razpisanieto": "Мариян Петров Липов"}], r
    nov = json.load(open(os.path.join(store, "oc", "2026-11.json"), encoding="utf-8"))["sluzhiteli"]
    assert nov[0]["ime"] == "Мариян Петров Липов" and nov[0]["kakto_e_v_grafika"] == "Мариан Петров Липов"
    assert nov[0]["dni"] == {"Д": [4, 8]} and nov[1]["ime"] == "Иван Георгиев Дъбов" and nov[1]["dni"] == {}, nov

    # bad readings are refused and nothing is written
    row = lambda dni: [{"ime": "Х", "dni": dni}]  # noqa: E731
    bad = [
        ({"grafik": "oc", "mesec": "2026-11", "redove": row({"Д": [31]})}, "извън месеца"),
        ({"grafik": "oc", "mesec": "2026-10", "redove": row({"Дк": [30]})}, "последния ден"),
        ({"grafik": "oc", "mesec": "2026-10", "redove": row({"Я": [3]})}, "непознат код"),
        ({"grafik": "oc", "mesec": "2026-10", "redove": row({"Д-С": [3]})}, "непознат код"),  # a code of the other schedule
        ({"grafik": "rspbzn-pleven", "mesec": "2026-10", "redove": row({"км": [3]})}, "непознат код"),
        ({"grafik": "oc", "mesec": "2026-10", "redove": row({"Д": [3], "о": "2-4"})}, "ден 3"),
        ({"grafik": "oc", "mesec": "2026-10", "redove": [{"ime": "Иван Георгиев Дъбов", "dni": {}},
                                                          {"ime": "Иван Дъбов", "dni": {}}]}, "същият служител"),
        ({"grafik": "drug", "mesec": "2026-10", "redove": row({})}, "Непознат график"),
        ({"grafik": "oc", "mesec": "10.2026", "redove": row({})}, "ГГГГ-ММ"),
    ]
    for i, (doc_bad, expect) in enumerate(bad):
        code, r = js(store, "import", reading(tmp, f"bad{i}.json", doc_bad))
        assert code == 2 and not r["ok"] and expect in r["error"], (expect, r)
    assert sha(month) == first

    # what to look at again: shift days off the person's usual 4-day cycle; people of another unit
    code, r = js(store, "import", OC, "--dry-run")
    check = {c["ime"]: c["dni_izvan_tsikala"] for c in r["za_proverka"]}
    assert check == {"Мариян Петров Липов": [21]}, check
    assert [p["ime"] for p in r["vremenno_premesteni"]] == ["Стоян Петров Дренов"], r["vremenno_premesteni"]
    two = {"grafik": "oc", "mesec": "2027-03", "redove": [{"ime": "Иван Георгиев Дъбов", "dni": {"Д": [3, 4, 8]}}]}
    code, r = js(store, "import", reading(tmp, "two.json", two), "--dry-run")
    assert any("два поредни дни (3 и 4)" in w for w in r["warnings"]), r
    # … but 12-hour duties on consecutive days are normal
    code, r = js(store, "import", RS, "--dry-run")
    assert not r["warnings"], r["warnings"]


def test_queries(tmp, store):
    # who is on duty on a date = who takes over at 08:00
    code, r = js(store, "na-data", "2026-10-04")
    assert r["kam"] == "2026-10-04 08:00" and r["den"] == "неделя", r
    by = {g["grafik"]: g for g in r["grafici"]}
    assert [p["ime_kratko"] for p in by["oc"]["dezhurni"]] == ["Мариян Липов"], by["oc"]
    assert by["oc"]["dezhurni"][0]["smyana"] == "III" and by["oc"]["dezhurni"][0]["do"] == "2026-10-05 08:00"
    places = {}
    for p in by["rspbzn-pleven"]["dezhurni"]:
        places.setdefault(p["myasto"], []).append(p["ime_kratko"])
    assert places == {"РСПБЗН – Плевен": ["Петър Къпинов"], "УПБЗН – Сторгозия": ["Красимир Орехов"],
                      "УПБЗН – Долна Митрополия": ["Васил Ружев"]}, places
    # the schedule wins over the roster: the unit is where the schedule puts the person
    moved = [p for p in by["rspbzn-pleven"]["dezhurni"] if p["ime_kratko"] == "Васил Ружев"][0]
    assert moved["zveno"] == "УПБЗН – Долна Митрополия" and moved["vremenno_premesten"] is True, moved
    assert moved["po_razpisanie_e_v"] == "РСПБЗН – Белене", moved
    assert all("po_razpisanie_e_v" not in p for p in by["oc"]["dezhurni"]), by["oc"]["dezhurni"]

    # before 08:00 the shift of the previous day is still on duty
    code, r = js(store, "na-data", "2026-10-04", "--chas", "03:30", "--grafik", "oc")
    assert [p["ime_kratko"] for p in r["grafici"][0]["dezhurni"]] == ["Иван Дъбов", "Стоян Дренов"], r
    assert r["grafici"][0]["dezhurni"][0]["ot"] == "2026-10-03 08:00"
    # a 12-hour duty (08:00 – 20:00) is over in the evening; an 8-hour day is work, not a duty
    code, r = js(store, "na-data", "2026-10-01", "--chas", "21:00", "--grafik", "rspbzn-pleven")
    assert "Николай Лешников" not in [p["ime_kratko"] for p in r["grafici"][0]["dezhurni"]], r
    code, r = js(store, "na-data", "2026-10-01", "--grafik", "rspbzn-pleven")
    g = r["grafici"][0]
    assert "Николай Лешников" in [p["ime_kratko"] for p in g["dezhurni"]]
    assert [p["ime_kratko"] for p in g["na_rabota_bez_dezhurstvo"]] == ["Ангел Черешов"], g["na_rabota_bez_dezhurstvo"]
    # the rest of the shift from 30 September (00:00 – 08:00) is on duty at night, not at 08:00
    code, r = js(store, "na-data", "2026-10-01", "--chas", "02:00", "--grafik", "rspbzn-pleven")
    assert [(p["ime_kratko"], p["kod"]) for p in r["grafici"][0]["dezhurni"]] == [("Красимир Орехов", "8о")], r
    code, r = js(store, "na-data", "2026-10-31", "--grafik", "oc")
    assert [p["kod"] for p in r["grafici"][0]["dezhurni"]] == ["Дк", "Дк"], r
    code, r = js(store, "na-data", "2026-10-06", "--grafik", "oc", "--vsichki")
    assert [p["ime_kratko"] for p in r["grafici"][0]["otsastvat"]] == ["Николай Яворов"], r
    code, r = js(store, "na-data", "2027-01-05")
    assert r["nyama_grafik_za_mesetsa"] == ["oc", "rspbzn-pleven"] and not r["grafici"], r

    # "кога съм дежурен": --az is the owner of the key (here FIRE_SERVICE_AZ)
    code, r = js(store, "sluzhitel", "--az", "--mesec", "2026-10")
    g = r["grafici"][0]
    assert r["sluzhitel"] == "Иван Дъбов" and g["grafik"] == "oc" and g["broi_dezhurstva"] == 7, r
    assert r["dlazhnost"] == "ИНСПЕКТОР IV степен" and r["zvanie"] == "Инспектор", r
    assert [d["data"][-2:] for d in g["dezhurstva"]] == ["03", "11", "15", "19", "23", "27", "31"], g
    assert g["dezhurstva"][0] == {"data": "2026-10-03", "den": "събота", "kod": "Д", "ot": "2026-10-03 08:00",
                                  "do": "2026-10-04 08:00", "chasove": 24}, g["dezhurstva"][0]
    code, r = js(store, "sluzhitel", "Георги Малинов", "--mesec", "2026-10")
    g = r["grafici"][0]
    assert g["grafik"] == "rspbzn-pleven" and g["broi_dezhurstva"] == 7 and g["drugi"]["К"]["dni"] == [14, 15, 16], g
    code, r = js(store, "sluzhitel", "Черешов", "--mesec", "2026-10")
    assert code == 2 and "Няколко служители" in r["error"], r
    code, r = js(store, "sluzhitel", "Няма Такъв")
    assert code == 2 and "няма в поименното разписание" in r["error"], r

    code, r = js(store, "spisak")
    assert [(m["grafik"], m["mesec"], m["sluzhiteli"]) for m in r["mesetsi"]] == [
        ("oc", "2026-10", 6), ("oc", "2026-11", 2), ("rspbzn-pleven", "2026-10", 8)], r
    assert r["vidove"]["rspbzn-pleven"]["kodove"]["Д-С"].startswith("дежурство в УПБЗН – Сторгозия"), r["vidove"]
    code, text = run(store, "mesec", "oc", "2026-10")
    assert code == 0 and "| 2 | Иван Георгиев Дъбов | II |  |  | Д |" in text and text.count("\n") >= 9, text


def test_without_roster(tmp, store):
    """A colleague with the connector has no staff list at hand: questions still work, an import asks for it."""
    code, r = js(store, "sluzhitel", "Иван Дъбов", "--mesec", "2026-10", env=NO_ROSTER)
    assert code == 0 and r["sluzhitel"] == "Иван Дъбов" and r["grafici"][0]["broi_dezhurstva"] == 7, r
    # what the schedule itself says: the position and rank kept in the month when it was saved
    assert r["dlazhnost"] == "ИНСПЕКТОР IV степен" and r["zvanie"] == "Инспектор" and "podrazdelenie" not in r, r
    code, r = js(store, "na-data", "2026-10-04", "--grafik", "oc", env=NO_ROSTER)
    assert [p["ime_kratko"] for p in r["grafici"][0]["dezhurni"]] == ["Мариян Липов"], r
    code, r = js(store, "sluzhitel", "--az", env=NO_ROSTER)
    assert code == 2 and "Не знам кой си" in r["error"], r
    code, r = js(store, "import", OC, "--dry-run", env=NO_ROSTER)
    assert code == 2 and "NO_KEY" in r["error"] and "--roster" in r["error"], r
    # … and gets it from a file (the rows of the connector tool staff with csv: true)
    code, r = js(store, "import", OC, "--dry-run", env=NO_ROSTER, before=["--roster", STAFF])
    assert code == 0 and not r["changed"] and not r["unmatched"], r


def test_holidays(tmp, store):
    # the holiday days are the official holidays only; the moved days off are listed on request
    code, r = js(None, "praznitsi", "2026")
    assert len(r["praznitsi"]) == 14 and "2026-12-28" not in [p["data"] for p in r["praznitsi"]], r
    code, r = js(None, "praznitsi", "2026", "--s-premesteni")
    days = {p["data"]: p["ime"] for p in r["praznitsi"]}
    assert [d for d in days if d.startswith("2026-04")] == ["2026-04-10", "2026-04-11", "2026-04-12", "2026-04-13"], days
    # 24 May and 6 September are Sundays, 26 December is a Saturday → the Mondays after them are days off
    assert days["2026-05-25"].startswith("почивен ден за 24.05.") and days["2026-09-07"].startswith("почивен ден за 06.09.")
    assert days["2026-12-28"].startswith("почивен ден за 26.12.") and len(days) == 17, days
    code, r = js(None, "praznitsi", "2027", "--s-premesteni")  # Easter 2 May 2027; 1 May is a Saturday → Tuesday 4 May (3 May is Easter Monday)
    days = [p["data"] for p in r["praznitsi"]]
    assert "2027-04-30" in days and "2027-05-03" in days and "2027-05-04" in days, days

    # December 2026: the shift before a holiday has 8 hours of it (00:00 – 08:00), the next one 16 (08:00 – 24:00)
    dec = {"grafik": "oc", "mesec": "2026-12", "redove": [
        {"ime": "Иван Георгиев Дъбов", "smyana": "II", "dni": {"Д": [3, 23, 27], "Дк": [31]}},
        {"ime": "Мариян Петров Липов", "smyana": "III", "dni": {"Д": [24]}},
        {"ime": "Николай Иванов Яворов", "smyana": "IV", "dni": {"Д": [25], "о": [24]}}]}
    code, r = js(store, "import", reading(tmp, "dec.json", dec))
    assert code == 0 and r["written"], r
    code, r = js(store, "praznichni", "--az", "--mesec", "2026-12")
    assert r["praznichni_dni_s_dezhurstvo"] == 1 and r["praznichni_chasove"] == 8, r
    assert [(d["data"], d["chasove"], d["chasti"][0]["ot"], d["chasti"][0]["do"]) for d in r["dni"]] == [
        ("2026-12-24", 8, "00:00", "08:00")], r["dni"]
    assert [p["data"][-2:] for p in r["praznitsi_v_mesetsa"]] == ["24", "25", "26"], r
    code, r = js(store, "praznichni", "--az", "--mesec", "2026-12", "--s-premesteni")  # 28 Dec is a moved day off
    assert r["praznichni_dni_s_dezhurstvo"] == 2 and r["praznichni_chasove"] == 16, r
    code, r = js(store, "praznichni", "Мариян Липов", "--mesec", "2026-12")  # on 24 Dec: 16 h, then 8 h of 25 Dec
    assert [(d["data"], d["chasove"]) for d in r["dni"]] == [("2026-12-24", 16), ("2026-12-25", 8)], r
    assert r["praznichni_dni_s_dezhurstvo"] == 2 and r["praznichni_chasove"] == 24, r
    code, r = js(store, "praznichni", "Николай Яворов", "--mesec", "2026-12")  # 25 Dec 16 h + 26 Dec 8 h; leave is not work
    assert [(d["data"], d["chasove"]) for d in r["dni"]] == [("2026-12-25", 16), ("2026-12-26", 8)], r

    # the month gets only its own dates: the shift of 31 December gives its last 8 hours to 1 January
    code, r = js(store, "praznichni", "--az", "--mesec", "2027-01")
    assert r["praznichni_chasove"] == 8 and r["dni"][0]["data"] == "2027-01-01", r
    assert r["dni"][0]["chasti"][0]["smyana_ot"] == "2026-12-31" and r["belezhki"] == ["Няма го в записан график за 2027-01"], r
    # no holidays in October; a missing previous month is said only when the 1st is a holiday
    code, r = js(store, "praznichni", "--az", "--mesec", "2026-10")
    assert r["praznichni_dni_s_dezhurstvo"] == 0 and r["praznichni_chasove"] == 0 and not r["belezhki"], r
    code, r = js(store, "na-data", "2026-12-25", "--grafik", "oc")
    assert r["praznik"] == "Рождество Христово" and [p["ime_kratko"] for p in r["grafici"][0]["dezhurni"]] == ["Николай Яворов"], r


def test_store(tmp, store):
    month = os.path.join(store, "oc", "2026-10.json")
    code, r = js(store, "proverka")
    assert code == 0 and r["ok"] and r["provereni"] == 4, r
    with open(month, encoding="utf-8") as f:
        text = f.read()
    edited = text.replace("[2, 6, 10, 14, 18, 22, 26, 30]", "[2,6,10,14,18,22,26,30]")
    assert edited != text
    with open(month, "w", encoding="utf-8") as f:
        f.write(edited)
    code, r = js(store, "proverka")
    assert code == 1 and not r["ok"] and "каноничния вид" in r["problemi"][0], r

    # what n8n returns is re-serialised JSON (compact, number-like keys first); it is read back as the same file
    sys.path.insert(0, os.path.dirname(SCRIPT))
    import grafik
    rs_month = os.path.join(store, "rspbzn-pleven", "2026-10.json")
    canonical = open(rs_month, encoding="utf-8").read()
    doc = json.loads(canonical)
    for person in doc["sluzhiteli"]:
        person["dni"] = dict(sorted(person["dni"].items(), key=lambda kv: (not kv[0].isdigit(), 0)))
    assert list(doc["sluzhiteli"][3]["dni"]) == ["8", "О"] and list(doc["sluzhiteli"][5]["dni"]) == ["Д-С", "8о"]
    mangled = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    assert mangled != canonical and grafik.canonical_text(mangled) == canonical

    # without --store the months come from n8n; without a personal key that is said plainly, nothing is invented
    code, r = js(None, "spisak")
    assert code == 2 and not r["ok"] and r["error"].startswith("NO_KEY"), r


def test_tiles(tmp):
    """izrezki.py: every tile carries the header row and the name column."""
    try:
        from PIL import Image
    except ImportError:
        print("skip izrezki.py (Pillow is not installed)")
        return
    src = os.path.join(tmp, "photo.png")
    Image.new("RGB", (1000, 800), "white").save(src)
    out_dir = os.path.join(tmp, "tiles")
    r = subprocess.run([sys.executable, os.path.join(SKILL, "scripts", "izrezki.py"), src, "--box", "0.1,0.2,0.9,0.8",
                        "--header", "0.15,0.2", "--names", "0.1,0.3", "--bands", "3", "--cols", "2", "-o", out_dir],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    made = json.loads(r.stdout)["tiles"]
    assert len(made) == 6 and all(os.path.isfile(p) for p in made), made
    w, h = Image.open(made[0]).size
    assert w > h and max(w, h) <= 1500, (w, h)


def test_concurrent_save(tmp):
    """Two people save halves of the same month at the same time: the second one read the month before the
    first one wrote. The save reads the month again just before writing and merges over the fresh copy."""
    import argparse
    import contextlib
    import io
    os.environ.update(FIRE_SERVICE_NO_KEY="1", FIRE_SERVICE_STAFF_CSV=STAFF)
    sys.path.insert(0, os.path.dirname(SCRIPT))
    import grafik
    grafik.sluzhiteli.STAFF_FILE = STAFF               # the invented staff list of the tests

    doc = json.load(open(OC, encoding="utf-8"))
    rows = [dict(r, nomer=i) for i, r in enumerate(doc["redove"], 1)]   # the row numbers of the printed schedule
    half_a = reading(tmp, "a.json", dict(doc, redove=rows[:3]))
    half_b = reading(tmp, "b.json", dict(doc, redove=rows[3:]))
    store_dir = os.path.join(tmp, "race")
    code, r = js(store_dir, "import", half_a)          # the colleague's half is already saved …
    assert code == 0 and len(r["added"]) == 3, r

    class Stale(grafik.LocalStore):                    # … but our first read happened before that
        calls = 0

        def get(self, g, m):
            Stale.calls += 1
            return None if Stale.calls == 1 else super().get(g, m)

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        grafik.cmd_import(argparse.Namespace(reading=half_b, replace=False, dry_run=False), Stale(store_dir))
    saved = json.load(open(os.path.join(store_dir, "oc", "2026-10.json"), encoding="utf-8"))
    assert len(saved["sluzhiteli"]) == 6, [x["ime"] for x in saved["sluzhiteli"]]   # nobody's rows are lost
    assert Stale.calls >= 3, Stale.calls                # read, read again before writing, read after the change
    print("  ok  concurrent save: the colleague's rows survive")


def test_former_employee(tmp):
    """Someone who has left is no longer in the staff list, but the months he worked still give his name,
    position and rank – like everyone else's – because they were kept in the month when it was saved."""
    store = os.path.join(tmp, "former")
    for f in (OC, RS):
        code, r = js(store, "import", f)
        assert code == 0, r
    saved = json.load(open(os.path.join(store, "rspbzn-pleven", "2026-10.json"), encoding="utf-8"))
    row = saved["sluzhiteli"][0]
    assert list(row)[:4] == ["ime", "ime_kratko", "dlazhnost", "zvanie"], list(row)
    assert (row["ime_kratko"], row["dlazhnost"], row["zvanie"]) == \
        ("Бранимир Елхов", "НАЧАЛНИК НА ДЕЖУРНА СМЯНА", "Младши експерт"), row

    lines = open(STAFF, encoding="utf-8").read().splitlines(True)
    gone = [l for l in lines if "Бранимир Христов Елхов" not in l and "Иван Георгиев Дъбов" not in l]
    assert len(gone) == len(lines) - 2
    later = os.path.join(tmp, "staff_later.csv")          # the staff list a year later: two people have left
    open(later, "w", encoding="utf-8").writelines(gone)
    env = dict(ENV, FIRE_SERVICE_STAFF_CSV=later)

    code, r = js(store, "na-data", "2026-10-03", "--grafik", "rspbzn-pleven", env=env)
    people = {p["ime_kratko"]: p for p in r["grafici"][0]["dezhurni"]}
    left, stays = people["Бранимир Елхов"], people["Георги Малинов"]
    assert left["dlazhnost"] == "НАЧАЛНИК НА ДЕЖУРНА СМЯНА" and left["zvanie"] == "Младши експерт", left
    assert left["zveno"] == "РСПБЗН – Плевен" and left["ne_e_v_razpisanieto"] is True, left
    assert "ne_e_v_razpisanieto" not in stays and stays["dlazhnost"] == "КОМАНДИР НА ЕКИП", stays

    code, r = js(store, "sluzhitel", "Бранимир Елхов", "--mesec", "2026-10", env=env)   # asked about by name
    assert code == 0 and r["sluzhitel"] == "Бранимир Елхов" and r["zvanie"] == "Младши експерт", r
    assert r["ne_e_v_razpisanieto"] is True and r["grafici"][0]["broi_dezhurstva"] == 8, r
    code, r = js(store, "praznichni", "Иван Дъбов", "--mesec", "2026-10", env=env)
    assert code == 0 and r["sluzhitel"] == "Иван Дъбов", r
    code, r = js(store, "sluzhitel", "Никой Никоев", "--mesec", "2026-10", env=env)
    assert code == 2, r

    # a later page of the same month, saved after he left, does not wipe what was kept about him
    doc = json.load(open(RS, encoding="utf-8"))
    code, r = js(store, "import", reading(tmp, "page2.json", dict(doc, redove=doc["redove"][1:3])), env=env)
    assert code == 0 and not r["changed"], r
    code, r = js(store, "import", RS, "--replace", env=env)      # … nor does his own page, read again
    assert code == 0 and [u["ime"] for u in r["unmatched"]] == ["Бранимир Христов Елхов"], r
    again = json.load(open(os.path.join(store, "rspbzn-pleven", "2026-10.json"), encoding="utf-8"))["sluzhiteli"][0]
    assert again["zvanie"] == "Младши експерт" and again["v_razpisanieto"] is False, again
    code, r = js(store, "import", RS, "--replace")               # back to the state the next checks expect
    assert code == 0, r
    # the position kept in the month wins over today's: a promotion later does not rewrite the past
    promoted = os.path.join(tmp, "staff_promoted.csv")
    open(promoted, "w", encoding="utf-8").write(
        "".join(lines).replace("КОМАНДИР НА ЕКИП,КОМАНДИР НА ЕКИП,Младши експерт,Георги",
                               "НАЧАЛНИК НА ДЕЖУРНА СМЯНА,НАЧАЛНИК НА ДЕЖУРНА СМЯНА,Инспектор,Георги"))
    code, r = js(store, "na-data", "2026-10-03", "--grafik", "rspbzn-pleven", env=dict(ENV, FIRE_SERVICE_STAFF_CSV=promoted))
    stays = [p for p in r["grafici"][0]["dezhurni"] if p["ime_kratko"] == "Георги Малинов"][0]
    assert stays["dlazhnost"] == "КОМАНДИР НА ЕКИП" and stays["zvanie"] == "Младши експерт", stays

    # a month saved before the snapshot existed: "dopalni" adds it while the people are still in the list
    old = os.path.join(tmp, "old")
    path = os.path.join(old, "rspbzn-pleven", "2026-10.json")
    os.makedirs(os.path.dirname(path))
    bare = dict(saved, sluzhiteli=[{k: v for k, v in x.items() if k not in ("ime_kratko", "dlazhnost", "zvanie")}
                                   for x in saved["sluzhiteli"]])
    sys.path.insert(0, os.path.dirname(SCRIPT))
    import grafik
    open(path, "w", encoding="utf-8").write(grafik.dump(bare))
    code, r = js(old, "na-data", "2026-10-03", "--grafik", "rspbzn-pleven", env=env)    # nothing kept: the name stays
    left = [p for p in r["grafici"][0]["dezhurni"] if p["ime"] == "Бранимир Христов Елхов"][0]
    assert left["ime_kratko"] == "Бранимир Елхов" and "dlazhnost" not in left and left["ne_e_v_razpisanieto"], left
    code, r = js(old, "dopalni", "rspbzn-pleven", "2026-10", "--dry-run")
    assert code == 0 and r["dopalneni"] == 8 and not r["written"], r
    code, r = js(old, "dopalni", "rspbzn-pleven", "2026-10")
    assert code == 0 and r["written"] and open(path, encoding="utf-8").read() == grafik.dump(saved), r
    code, r = js(old, "dopalni", "rspbzn-pleven", "2026-10")
    assert code == 0 and r["dopalneni"] == 0 and not r["written"], r
    code, r = js(old, "proverka")
    assert code == 0 and r["ok"], r
    print("  ok  former employee: name, position and rank stay in the months he worked")


def test_incident(tmp):
    """Who was on shift at an incident: the operations centre and the unit(s) of the record, at the hour of
    the signal; a night signal belongs to the shift of the day before; a long one shows the next shift too."""
    store = os.path.join(tmp, "incident")
    for f in (OC, RS):
        code, r = js(store, "import", f)
        assert code == 0, r
    rec = {"id": 77001, "num_event": 12, "dat": "2026-10-09 03:30:00", "casulaty": "пожар с преки материални загуби",
           "unit": "У ПБЗН - Сторгозия", "location": "гр. Плевен", "object": "склад", "orderlyturn": "02 ДС",
           "forces": "служ 8; 3 ПА; 1 - РС ПБЗН - Плевен; 2 - У ПБЗН - Сторгозия;", "closed": "2026-10-09 05:10:00"}
    path = reading(tmp, "rec.json", [rec])
    code, r = js(store, "pri-proizshestvie", "--zapis", path)
    assert code == 0 and r["kam"] == "2026-10-09 03:30" and r["proizshestvie"]["orderlyturn"] == "02 ДС", r
    assert r["sluzhbi"] == ["УПБЗН – Сторгозия", "РСПБЗН – Плевен"] and not r["sluzhbi_bez_grafik"], r
    by = {g["grafik"]: g for g in r["grafici"]}
    assert set(by) == {"oc", "rspbzn-pleven"}, by.keys()
    rs = by["rspbzn-pleven"]                               # 03:30 on the 9th = the shift that began on the 8th
    assert [(p["ime_kratko"], p["myasto"], p["ot"]) for p in rs["dezhurni"]] == \
        [("Красимир Орехов", "УПБЗН – Сторгозия", "2026-10-08 08:00")], rs
    assert [p["myasto"] for p in rs["dezhurni_v_drugi_zvena"]] == ["УПБЗН – Долна Митрополия"], rs
    assert all(p["ot"] == "2026-10-08 08:00" for p in by["oc"]["dezhurni"]) and by["oc"]["dezhurni"], by["oc"]
    assert "sled_smyanata_na_smenite" not in r and "график" in r["belezhka"], r

    # the work went on after 08:00: the shift that took over is listed as well
    code, r = js(store, "pri-proizshestvie", "--zapis", reading(tmp, "long.json", dict(rec, closed="2026-10-09 10:00:00",
                                                                                      dat_o2="2026-10-09 11:15:00")))
    later = r["sled_smyanata_na_smenite"]
    assert later["kam"] == "2026-10-09 11:15" and later["smyana_ot"] == "2026-10-09 08:00", later
    assert all(p["ot"] == "2026-10-09 08:00" for g in later["grafici"] for p in g["dezhurni"]), later

    # a unit with no stored schedule: said, not guessed; the operations centre is still given
    code, r = js(store, "pri-proizshestvie", "--zapis", reading(tmp, "lv.json", dict(rec, unit="РС ПБЗН - Левски",
                                                                                    forces="служ 4; 1 ПА; 1 - РС ПБЗН - Левски;")))
    assert r["sluzhbi_bez_grafik"] == ["РСПБЗН – Левски"] and [g["grafik"] for g in r["grafici"]] == ["oc"], r
    code, r = js(store, "pri-proizshestvie", "--zapis", reading(tmp, "cb.json", dict(rec, unit="РС ПБЗН - Червен бряг", forces="")))
    assert r["sluzhbi"] == ["РСПБЗН – Червен бряг"], r

    # no record: date, hour and unit; several records in the file need --id; a month with no schedule is said
    code, r = js(store, "pri-proizshestvie", "--data", "2026-10-04", "--chas", "14:00", "--sluzhba", "РСПБЗН – Плевен")
    names = [p["ime_kratko"] for g in r["grafici"] if g["grafik"] == "rspbzn-pleven" for p in g["dezhurni"]]
    assert code == 0 and names == ["Петър Къпинов"] and "proizshestvie" not in r, r
    two = reading(tmp, "two.json", [rec, dict(rec, id=77002, dat="2026-10-12 21:00:00")])
    code, r = js(store, "pri-proizshestvie", "--zapis", two)
    assert code == 2 and "--id" in r["error"], r
    code, r = js(store, "pri-proizshestvie", "--zapis", two, "--id", "77002")
    assert code == 0 and r["kam"] == "2026-10-12 21:00", r
    code, r = js(store, "pri-proizshestvie", "--zapis", reading(tmp, "old.json", dict(rec, dat="2025-03-02 10:00:00", closed="")))
    assert code == 0 and set(r["nyama_grafik_za_mesetsa"]) == {"oc", "rspbzn-pleven"} and not r["grafici"], r
    code, r = js(store, "pri-proizshestvie")
    assert code == 2, r
    print("  ok  incident: the shift at the hour of the signal, by unit")


def test_conditional_save(tmp):
    """Through n8n the write is conditional: put sends the md5 that get saw ("new" when there was no file);
    on 409 CONFLICT the month is read again, merged again and saved with the fresh md5."""
    import argparse
    import contextlib
    import hashlib
    import io
    import urllib.error
    os.environ.update(FIRE_SERVICE_NO_KEY="1", FIRE_SERVICE_STAFF_CSV=STAFF)
    sys.path.insert(0, os.path.dirname(SCRIPT))
    import grafik
    grafik.sluzhiteli.STAFF_FILE = STAFF

    doc = json.load(open(OC, encoding="utf-8"))
    rows = [dict(r, nomer=i) for i, r in enumerate(doc["redove"], 1)]
    half_a = reading(tmp, "ca.json", dict(doc, redove=rows[:3]))
    half_b = reading(tmp, "cb.json", dict(doc, redove=rows[3:]))
    other = os.path.join(tmp, "other")                 # the colleague's half, as it will be stored
    code, r = js(other, "import", half_a)
    assert code == 0, r
    colleague = open(os.path.join(other, "oc", "2026-10.json"), encoding="utf-8").read()

    server = {"text": None}                            # the month file "in Drive"
    puts = []
    md5 = lambda t: hashlib.md5(t.encode()).hexdigest()

    def post(which, body, timeout=30):
        assert which == "duty_url", which
        now = md5(server["text"]) if server["text"] else "new"
        if body["action"] == "get":
            if server["text"] is None:
                raise urllib.error.HTTPError("u", 404, "x", {}, io.BytesIO(b'{"error":"NOT_FOUND: no schedule"}'))
            return {"text": server["text"], "md5": now}
        puts.append(body.get("if_md5"))
        if len(puts) == 1:                             # the colleague saves between our last read and our write
            server["text"] = colleague
            now = md5(colleague)
        if body.get("if_md5") != now:
            raise urllib.error.HTTPError("u", 409, "x", {}, io.BytesIO(b'{"error":"CONFLICT: changed"}'))
        server["text"] = body["text"]
        return {"ok": True, "md5": md5(body["text"]), "link": "drive"}

    store = grafik.RemoteStore.__new__(grafik.RemoteStore)
    store.cfg, store.seen = {"key": "k", "duty_url": "u"}, {}
    real, grafik.api_config.post = grafik.api_config.post, post
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            grafik.cmd_import(argparse.Namespace(reading=half_b, replace=False, dry_run=False), store)
    finally:
        grafik.api_config.post = real
    saved = json.loads(server["text"])
    assert puts == ["new", md5(colleague)], puts       # first "there was no file", then the fresh fingerprint
    assert len(saved["sluzhiteli"]) == 6, [x["ime"] for x in saved["sluzhiteli"]]
    print("  ok  conditional save: if_md5 is sent, a conflict is merged and saved again")


def main():
    tmp = tempfile.mkdtemp()
    try:
        store = os.path.join(tmp, "grafici")
        test_import(tmp, store)
        test_queries(tmp, store)
        test_without_roster(tmp, store)
        test_holidays(tmp, store)
        test_store(tmp, store)
        test_tiles(tmp)
        test_concurrent_save(tmp)
        test_conditional_save(tmp)
        test_former_employee(tmp)
        test_incident(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("OK grafik-dezhurstva")


if __name__ == "__main__":
    main()
