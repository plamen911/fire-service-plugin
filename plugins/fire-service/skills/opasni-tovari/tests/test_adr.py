#!/usr/bin/env python3
"""Tests for adr.py and karta_docx.py – the bundled dangerous-goods data and the answers built from it.
Everything is offline; the data files are checked for integrity as well as the logic."""
import csv
import json
import os
import subprocess
import sys
import tempfile
import zipfile

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADR = os.path.join(SKILL, "scripts", "adr.py")
DOCX = os.path.join(SKILL, "scripts", "karta_docx.py")
DATA = os.path.join(SKILL, "data")
checks = 0


def run(*args, script=ADR):
    return subprocess.run([sys.executable, script, *args], capture_output=True, text=True)


def out(*args):
    return run(*args).stdout


def js(*args):
    return json.loads(run(*args, "--json").stdout)


def ok(cond, what=""):
    global checks
    checks += 1
    assert cond, what


def rows(name):
    with open(os.path.join(DATA, name), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_data():
    v = rows("veshtestva.csv")
    ok(len(v) > 2500 and len({r["un"] for r in v}) == 2347, "all UN numbers of ADR 2025 Table A")
    ok(len({r["id"] for r in v}) == len(v), "ids are unique")
    eri = json.load(open(os.path.join(DATA, "eri_karti.json"), encoding="utf-8"))
    erg = json.load(open(os.path.join(DATA, "erg_ukazaniya.json"), encoding="utf-8"))
    hin = {r["hin"] for r in rows("hin.csv")}
    klas = {r["klas"] for r in rows("klasove.csv")}
    for r in v:
        ok(r["ime"] and r["ime_en"] and r["klas"] in klas, r)
        ok(r["eri"] == "" or r["eri"] in eri["karti"], f"card of {r['un']}")
        ok(r["erg"] and all(g in erg["ukazaniya"] for g in r["erg"].split("/")), f"guide of {r['un']}")
        ok(all(h.strip() in hin for h in r["hin"].split(",") if h.strip()), f"HIN of {r['un']}: {r['hin']}")
        ok(all(p in ("I", "II", "III") for p in r["og"].split(", ") if p), f"packing group of {r['un']}: {r['og']}")
        ok("N.O.S" not in r["ime"] and "О.У.О" not in r["ime"], r["ime"])
    # no index points outside the phrase tables, every card has its seven sections
    for c in eri["karti"].values():
        ok(all(0 <= i < len(eri["frazi"]) for i in c["tekst"]))
        heads = [eri["frazi"][i][1].split(" ")[0] for i in c["tekst"] if eri["frazi"][i][0] != "li"]
        ok(heads == ["1.", "2.", "3.", "4.", "4.1", "4.2", "4.3", "5.", "6.", "7.", "7.1", "7.2"], heads)
    for g in erg["ukazaniya"].values():
        ok(all(0 <= i < len(erg["frazi"]) for i in g["tekst"]) and g["izolirane_m"])
    # the mistranslations of the source must not come back
    text = json.dumps(eri, ensure_ascii=False)
    for bad in ("подветрената", "Възможно наличие на разливи", "пукнатини", "Съхранявайте от"):
        ok(bad not in text, bad)
    ok("наветрената страна" in text)
    # Bulgarian only in the guides (a missing translation would leave an English sentence)
    for kind, bg, *_ in erg["frazi"]:
        ok(sum(ch.isascii() and ch.isalpha() for ch in bg) < 0.5 * max(1, sum(ch.isalpha() for ch in bg)), bg)
    t1 = rows("erg_tablica1.csv")
    ok(len({r["un"] for r in t1}) == 264 and all(r["malak_izol_m"] for r in t1))   # 271 in ERG less 7 NA numbers
    ok({r["un"] for r in rows("erg_tablica3.csv")} == {"1005", "1017", "1040", "1050", "1052", "1079", "2186"})


def test_known_values():
    # a handful of values checked by hand against ADR 2025 Table A, ERICards and ERG 2024
    r = js("tarsi", "--tabela", "33/1203")["rows"][0]
    ok((r["klas"], r["kod"], r["og"], r["eri"], r["erg"]) == ("3", "F1", "II", "3-11", "128"), r)
    r = js("tarsi", "--un", "1824")["rows"][0]
    ok(r["ime"].startswith("НАТРИЕВ ХИДРОКСИД") and r["hin"] == "80", r)             # was „натриев хлорид“
    r = js("tarsi", "--un", "3423")["rows"][0]
    ok((r["klas"], r["hin"], r["eri"]) == ("6.1", "668", ""), r)                       # ADR 2025 + Corr.2
    r = js("tarsi", "--un", "3480")["rows"][0]
    ok((r["klas"], r["etiketi"], r["erg"]) == ("9", "9A", "147"), r)
    ok({x["hin"] for x in js("tarsi", "--un", "2031")["rows"]} == {"80", "85", "885"})
    ok("по-малко от 65 %" in [x for x in js("tarsi", "--un", "2031")["rows"] if x["hin"] == "80"][0]["ime"])
    r = {x["hin"]: x for x in js("tarsi", "--un", "1133")["rows"]}
    ok(r["33"]["og"] == "I, II" and r["30"]["og"] == "III" and r[""]["og"] == "III", r)      # PG III is 30, not 33
    r = {x["hin"]: x for x in js("tarsi", "--un", "1835")["rows"]}
    ok(r["80"]["og"] == "III" and r["86"]["og"] == "II" and r["86"]["etiketi"] == "8+6.1", r)
    ok(js("tarsi", "--un", "0303")["rows"][0]["etiketi"] == "1.4, 1.4+8, 1.4+6.1")
    ok(js("karta", "--un", "3539")["tablica1"][0]["golyam_izol_m"] == "300")
    t = out("proizshestvie", "--un", "1942", "--vid", "pozhar", "--kolichestvo", "golyamo", "--vreme", "den")
    ok("1600 m" in t and "амониев нитрат" in t, "the ammonium nitrate fire distance of guide 140")
    k = js("karta", "--un", "1005")
    ok(k["veshtestvo"]["hin"] == "268" and k["tablica1"][0]["malak_izol_m"] == "30" and k["tablica1"][0]["tablica3"] == "1", k["tablica1"])
    g = {x["nomer"]: x for x in js("karta", "--un", "1203")["erg"]}["128"]
    ok((g["izolirane_m"], g["golyam_razliv_m"], g["golyam_razliv_posoka"], g["pozhar_m"]) == (50, 300, "vyatar", 800), g)
    g = js("ukazanie", "--nomer", "115")
    ok((g["izolirane_m"], g["golyam_razliv_m"], g["pozhar_m"]) == (100, 800, 1600), g)
    g = js("ukazanie", "--nomer", "147")
    ok((g["izolirane_m"], g["pozhar_m"]) == (25, 500), g)


def test_search():
    ok(js("tarsi", "--ime", "хлор")["rows"][0]["un"] == "1017", "exact name first")
    ok(js("tarsi", "--ime", "chlorine")["rows"][0]["un"] == "1017", "English name")
    ok(js("tarsi", "--tabela", "1203 33")["rows"][0]["un"] == "1203", "plate read bottom-up")
    ok(js("tarsi", "--tabela", "Х423/1428")["rows"][0]["un"] == "1428", "Cyrillic Х")
    d = js("tarsi", "--tabela", "30/1203")
    ok(d["rows"][0]["hin"] == "33" and "проверете прочитането" in d["note"], d["note"])
    ok(run("tarsi", "--un", "9999").returncode == 2)
    ok(all(r["klas"].startswith("2") for r in js("tarsi", "--klas", "2", "--limit", "0")["rows"]))
    ok(len(js("tarsi", "--hin", "X423", "--limit", "0")["rows"]) >= 10)
    p = run("karta", "--un", "1950")
    ok(p.returncode == 0 and "има 12 записа" in p.stdout, p.stdout[:200])
    ok(js("tarsi", "--ime", "нафта")["rows"][0]["un"] == "1202" and js("tarsi", "--ime", "пропан-бутан")["rows"][0]["un"] in ("1965", "1075"))
    p = run("karta", "--un", "1139")
    ok(p.returncode in (0, 3), p.stdout[:200])
    ok("реагира опасно с вода" in out("hin", "--kod", "X423"))
    ok("Няма го в списъка" in out("hin", "--kod", "299"))


def test_incident():
    t = out("proizshestvie", "--tabela", "265/1017", "--vid", "tech", "--kolichestvo", "golyamo", "--vreme", "nosht",
            "--vyatar", "slab", "--sad", "avtocisterna")
    ok("изолирайте 600 m" in t and "6,4 km" in t, "chlorine, Table 3")                # ERG 2024 Table 3
    ok("важи по-голямото" in t)
    ok(t.index("### 1. Зони") < t.index("Лична защита") < t.index("При разлив"), "zones first")
    ok("При пожар\n" not in t, "no fire section in a spill")
    t = out("proizshestvie", "--un", "1017", "--vid", "tech", "--kolichestvo", "malko", "--vreme", "den")
    ok("изолирайте 60 m" in t and "0,3 km" in t, "chlorine, small spill, day")        # ERG 2024 Table 1
    t = out("proizshestvie", "--un", "1203", "--vid", "tech-pozhar", "--kolichestvo", "golyamo", "--vreme", "den")
    ok("най-малко 50 m" in t and "по посока на вятъра на най-малко 300 m" in t and "ИЗОЛИРАЙТЕ (ОТЦЕПЕТЕ) на 800 m" in t, "petrol")
    ok("4. При разлив\n" in t and "5. При пожар\n" in t and "Гасете с пяна" in t)
    t = out("proizshestvie", "--un", "1689", "--vid", "tech", "--kolichestvo", "golyamo", "--vreme", "den")
    ok("само при контакт с вода" in t and "циановодород" in t, "water-reactive hint")
    t = out("proizshestvie", "--un", "1689", "--vid", "tech", "--kolichestvo", "golyamo", "--vreme", "den", "--voda")
    ok("при разлив във вода" in t and "изолирайте 60 m" in t)
    t = out("proizshestvie", "--un", "3480", "--vid", "pozhar", "--kolichestvo", "golyamo", "--vreme", "den")
    ok("Указание 147" in t and "ИЗОЛИРАЙТЕ (ОТЦЕПЕТЕ) на 500 m" in t and "високо напрежение" in t, "lithium batteries → ERG")
    t = out("proizshestvie", "--un", "3171", "--vid", "pozhar", "--kolichestvo", "malko", "--vreme", "den")
    ok("Указанията са няколко" in t and "--erg" in t)
    t = out("proizshestvie", "--un", "3171", "--erg", "147", "--vid", "pozhar", "--kolichestvo", "malko", "--vreme", "den")
    ok("Указание 147" in t and "Указание 138" not in t)
    d = js("proizshestvie", "--un", "1005", "--vid", "tech", "--kolichestvo", "golyamo", "--vreme", "den")
    ok(len(d["zoni"]["tablica3"]) == 4 and d["zoni"]["izolirane_m"] == 100, d["zoni"])
    for bad in ("подветрен", "None", "nan"):
        ok(bad not in t)
    # the first answer, before anything is known about a leak: immediate isolation, the fire radius and the worst case
    t = out("proizshestvie", "--tabela", "268/1005", "--vid", "zaplaha", "--kolichestvo", "golyamo", "--vreme", "nosht",
            "--sad", "avtocisterna")
    ok("най-малко 100 m" in t and "Ако се запали" in t and "1600 m" in t and "Ако има теч" in t and "1,8 km" in t, t[:900])
    t = out("proizshestvie", "--un", "1203", "--vid", "tech-pozhar", "--kolichestvo", "golyamo", "--vreme", "den")
    ok(t.index("При пожар: ") < t.index("Голям разлив: "), "the fire radius comes before the spill evacuation")
    ok("ОБАДЕТЕ СЕ НА 112" not in out("ukazanie", "--nomer", "128"))
    ok("етикети 2.3+8" in out("tarsi", "--tabela", "268/1005"), "labels in the search line, to check a photo")


def test_docx():
    try:
        import docx  # noqa: F401
    except ImportError:
        print("  (python-docx not installed – karta_docx.py not tested)")
        return
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "k.docx")
        p = run("--tabela", "265/1017", "--vid", "tech", "--kolichestvo", "golyamo", "--vreme", "nosht",
                "--vyatar", "slab", "--sad", "avtocisterna", "-o", f, script=DOCX)
        ok(p.returncode == 0 and os.path.getsize(f) > 10000, p.stderr)
        with zipfile.ZipFile(f) as z:
            xml = z.read("word/document.xml").decode("utf-8")
            ok("1017" in xml and "ХЛОР" in xml and "600 m" in xml and "6,4 km" in xml)
            ok(sum(n.startswith("word/media/") for n in z.namelist()) == 3, "three hazard labels: 2.3 + 5.1 + 8")
        sys.path.insert(0, os.path.join(SKILL, "_shared", "scripts"))
        from docx_common import check_document
        bad = check_document(f, letterhead=False)   # the card has no letterhead, but no bold and the common typography
        ok(not bad, "the card keeps the common rules: " + "; ".join(bad)[:200])
        f2 = os.path.join(d, "s.docx")
        ok(run("--un", "3480", "-o", f2, script=DOCX).returncode == 0 and os.path.getsize(f2) > 8000)
        ok(run("--un", "9999", "-o", f2, script=DOCX).returncode == 2)


def main():
    for t in (test_data, test_known_values, test_search, test_incident, test_docx):
        t()
        print(f"✓ {t.__name__}")
    print(f"OK – {checks} checks")


if __name__ == "__main__":
    main()
