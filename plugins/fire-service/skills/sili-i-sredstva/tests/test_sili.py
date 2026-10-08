#!/usr/bin/env python3
"""Tests for scripts/sili.py: every section of the method against values worked out by hand from the
formulas of Appendix 5 (the expected numbers below are computed here, not copied from the script)."""
import json
import math
import os
import subprocess
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(SKILL, "scripts", "sili.py")


def run(*args):
    r = subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout)


def steps(r):
    return {s["formula"] + " " + s["ime"]: s["stoinost"] for s in r["stapki"]}


def near(a, b, tol=0.011):
    return abs(a - b) <= tol


def test_solid():
    # circle, t = 10 + 6 + 5 = 21 min → R = 5·1 + 1·11 = 16 m
    code, r = run("tvardi", "--forma", "krag", "--vl", "1.0", "--i", "0.20", "--t-dv", "6", "--struinik", "В", "--q-pa", "40")
    s, res = steps(r), r["rezultat"]
    assert code == 0 and s["(1) Време за свободно развитие на пожара"] == 21 and s["(3) Радиус на пожара"] == 16, s
    assert near(res["plosht_na_pozhara_m2"], math.pi * 256) and near(res["plosht_na_gasene_m2"], math.pi * 5 * 27), res
    q = math.pi * 5 * 27 * 0.2
    assert near(res["razhod_za_gasene_l_s"], q) and res["struinitsi_za_gasene"] == math.ceil(q / 7) == 13, res
    assert res["ekipi_obshto"] == 7 and res["pozharni_avtomobili"] == math.ceil(q / 32) == 3, res
    assert res["razstoyanie_mezhdu_struinitsite_m"] == 7 and "Iз-2749" in r["iztochnik"], res

    # the first ten minutes at half speed: t = 2 + 3 + 3 = 8 → R = 0,5·2·8 = 8 m; semicircle and sector
    for shape, share, f_area in (("krag", 1, "(9)"), ("polukrag", 0.5, "(10)"), ("sektor", 0.25, "(11)")):
        code, r = run("tvardi", "--forma", shape, "--vl", "2", "--i", "0.1", "--pii", "--t-dv", "3", "--t-r", "3", "--struinik", "С")
        res = r["rezultat"]
        assert near(res["plosht_na_pozhara_m2"], share * math.pi * 64), (shape, res)
        assert near(res["plosht_na_gasene_m2"], share * math.pi * 5 * 11), (shape, res)
        assert [x["formula"] for x in r["stapki"]][:4] == ["(1)", "(2)", "(2)", f_area], r["stapki"]
    # the depth of extinguishing covers the whole fire → the flow is by the fire area (14)
    code, r = run("tvardi", "--forma", "krag", "--vl", "1", "--i", "0.1", "--pii", "--t-dv", "3", "--t-r", "3", "--struinik", "С")
    assert "(14) Необходим разход на вода за гасене" in steps(r) and near(r["rezultat"]["razhod_za_gasene_l_s"], math.pi * 16 * 0.1), r

    # rectangle, two directions, table rows, third stage, attack along the front from both sides, protection
    code, r = run("tvardi", "--forma", "pravoagalnik", "--a", "12", "--n", "2", "--vl-red", "6.1", "--i-red", "10",
                  "--t-dv", "8", "--t3", "10", "--ataka", "front2", "--struinik", "С", "--n-zashtita", "2")
    s, res = steps(r), r["rezultat"]
    path = 5 * 0.4 + 0.4 * 13 + 0.5 * 0.4 * 10                       # the upper bound of 0,3 – 0,4 m/min
    assert near(res["plosht_na_pozhara_m2"], 2 * 12 * path) and "(7) Площ на пожара" in s, res
    assert res["plosht_na_gasene_m2"] == 120 and res["razhod_za_gasene_l_s"] == 24 and res["razhod_obshto_l_s"] == 31, res
    assert (res["struinitsi_za_gasene"], res["struinitsi_obshto"], res["ekipi_obshto"]) == (7, 9, 3), res
    assert any("горната граница" in n for n in r["belezhki"]) and "pozharni_avtomobili" not in res, r["belezhki"]
    code, lower = run("tvardi", "--forma", "pravoagalnik", "--a", "12", "--n", "2", "--vl-red", "6.1", "--i-red", "10",
                      "--t-dv", "8", "--dolna", "--struinik", "С")
    assert near(lower["rezultat"]["plosht_na_pozhara_m2"], 24 * (5 * 0.3 + 0.3 * 13)), lower["rezultat"]

    # a known area, attack along the perimeter: Fг = 2·5·(15 + 20 − 10) = 250
    code, r = run("tvardi", "--forma", "pravoagalnik", "--fp", "300", "--a", "15", "--i", "0,15", "--struinik", "B")
    res = r["rezultat"]
    assert res["plosht_na_gasene_m2"] == 250 and res["razhod_za_gasene_l_s"] == 37.5 and res["struinitsi_za_gasene"] == 6, res
    assert res["struinik"] == "В" and res["ekipi_obshto"] == 3, res                 # Latin B is read as „В“
    # a monitor: 10 m deep, crews by flow (20)
    code, r = run("tvardi", "--forma", "pravoagalnik", "--fp", "2000", "--a", "40", "--i", "0.2", "--hg", "10",
                  "--struinik", "Р-12", "--ataka", "front1")
    res = r["rezultat"]
    assert res["plosht_na_gasene_m2"] == 400 and res["struinitsi_za_gasene"] == 4 and res["ekipi_obshto"] == math.ceil(80 / 14), res

    for bad in (["tvardi", "--forma", "krag", "--i", "0.2", "--struinik", "С"],             # no speed, no area
                ["tvardi", "--forma", "krag", "--vl", "1", "--struinik", "С", "--t-dv", "5"],  # no intensity
                ["tvardi", "--forma", "krag", "--vl", "1", "--i", "0.2", "--t-dv", "5"],       # no nozzle
                ["tvardi", "--forma", "krag", "--vl", "1", "--i", "0.2", "--struinik", "С"],   # no travel time
                ["tvardi", "--forma", "elipsa", "--fp", "10", "--i", "0.2", "--struinik", "С"],
                ["tvardi", "--forma", "krag", "--vl-red", "19", "--i", "0.2", "--t-dv", "5", "--struinik", "С"]):
        code, r = run(*bad)
        assert code == 2 and r["ok"] is False and r["error"], (bad, r)
    print("  ok  solid combustibles: area, extinguishing area, flow, nozzles, crews, vehicles")


def test_tank():
    code, r = run("rezervoar", "--d", "22.8", "--sasedni", "2", "--struinik", "В", "--t-kipene", "35",
                  "--pgv", "ПГВ-120", "--pgv-na-ekip", "2")
    res = r["rezultat"]
    assert near(res["voda_ohlazhdane_goryasht_l_s"], math.pi * 22.8 * 0.5) and res["struinitsi_ohlazhdane_goryasht"] == 6, res
    assert near(res["voda_ohlazhdane_sasedni_l_s"], 0.5 * 2 * math.pi * 22.8 * 0.2) and res["struinitsi_ohlazhdane_sasedni"] == 3, res
    area = math.pi * 22.8 ** 2 / 4
    assert res["penogeneratori"] == math.ceil(area * 0.05 / 6.0) == 4 and res["penoobrazuvatel_l"] == 2592, res
    assert res["ekipi_ohlazhdane"] == 5 and res["ekipi_gasene"] == 2, res
    code, r = run("rezervoar", "--d", "10", "--razliv", "--struinik", "В", "--t-kipene", "20", "--pgv", "ПГВ-40")
    res = r["rezultat"]
    assert near(res["voda_ohlazhdane_goryasht_l_s"], math.pi * 10) and res["penogeneratori"] == math.ceil(math.pi * 25 * 0.08 / 2.0), res
    code, r = run("rezervoar", "--d", "10", "--struinik", "В", "--pgv", "ПГВ-999", "--t-kipene", "20")
    assert code == 2 and "таблица 14" in r["error"], r
    code, r = run("rezervoar", "--d", "10", "--struinik", "В")                      # cooling only
    assert code == 0 and "penogeneratori" not in r["rezultat"] and any("Пенната атака" in n for n in r["belezhki"]), r
    print("  ok  tank: cooling, foam generators, foam concentrate")


def test_volume_and_powder():
    code, r = run("obem", "--a", "6", "--l", "10", "--h-pn", "1.2", "--pgv", "ПГВ-120")
    res = r["rezultat"]
    assert res["obem_m3"] == 90 and res["razhod_na_pyana_m3_min"] == 27 and res["penogeneratori"] == 1, res
    code, r = run("obem", "--v", "500", "--pgv", "ПГВ-40")
    assert r["rezultat"]["razhod_na_pyana_m3_min"] == 150 and r["rezultat"]["penogeneratori"] == math.ceil(150 / 12), r
    code, r = run("obem", "--a", "6", "--l", "10", "--h-pn", "1.2", "--z", "0.1")
    assert code == 2, r
    code, r = run("prah", "--fp", "40", "--i-red", "3.2", "--w-pa", "1000")
    res = r["rezultat"]
    assert res["razhod_na_prah_kg_s"] == 14 and res["prah_kg"] == 420 and res["struinitsi"] == 3 and res["avtomobili_za_prahovo_gasene"] == 1, res
    code, r = run("prah", "--fp", "100", "--struinik", "lafeten")
    assert r["rezultat"]["razhod_na_prah_kg_s"] == 30 and r["rezultat"]["struinitsi"] == 1 and r["rezultat"]["prah_kg"] == 900, r
    code, r = run("prah", "--gaz", "3.5")
    assert r["rezultat"] == {"razhod_na_prah_kg_s": 3.5, "struinitsi": 1}, r
    code, r = run("prah")
    assert code == 2, r
    print("  ok  foam by volume and powder")


def test_tables():
    code, r = run("tablitsi")
    assert set(r["tablitsi"]) == {"1", "2", "4", "7", "10", "11", "14"}, r
    code, r = run("tablitsi", "--tarsi", "жилищни")
    assert {(x["tablitsa"], x["no"]) for x in r["namereni"]} >= {(1, "3"), (2, "4.1"), (2, "4.3")}, r
    code, r = run("tablitsi", "10")
    assert r["napor_m"]["40"][1] == 7.4 and r["nakrainik_mm"][1] == 19, r
    code, r = run("tablitsi", "3")
    assert code == 2, r
    data = json.load(open(os.path.join(SKILL, "references", "tablitsi.json"), encoding="utf-8"))
    for key in ("tablitsa_1", "tablitsa_2"):
        numbers = [x["no"] for x in data[key]["redove"]]
        assert len(numbers) == len(set(numbers)), key
        for x in data[key]["redove"]:
            lo, hi = x.get("vl") or x.get("i")
            assert 0 < lo <= hi, x
    for x in data["tablitsa_14"]["redove"]:      # 6 % solution: concentrate is 6 % of the solution flow
        assert near(x["penoobrazuvatel_l_s"] / (x["voda_l_s"] + x["penoobrazuvatel_l_s"]), 0.06, 0.0005), x
    print("  ok  tables")


def main():
    test_solid()
    test_tank()
    test_volume_and_powder()
    test_tables()
    print("OK sili-i-sredstva")


if __name__ == "__main__":
    main()
