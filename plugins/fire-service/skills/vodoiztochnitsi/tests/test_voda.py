#!/usr/bin/env python3
"""Тестове за voda.py върху измислени данни (tests/fixtures в корена на хранилището).
Истинската таблица с водоизточниците е зад n8n и не се пипа тук."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.abspath(os.path.join(SKILL, "..", "..", "..", ".."))
VODA = os.path.join(SKILL, "_shared", "scripts", "voda.py")
FIX = os.path.join(ROOT, "tests", "fixtures")
BASE = {k: v for k, v in os.environ.items() if not k.startswith("FIRE_SERVICE_")}
TMP = tempfile.mkdtemp()
TABLE = os.path.join(TMP, "vodoiztochnitsi.csv")
ENV = dict(BASE, FIRE_SERVICE_NO_KEY="1", FIRE_SERVICE_VODA_CSV=TABLE,
           FIRE_SERVICE_RAIONI_CSV=os.path.join(FIX, "naseleni_mesta.csv"),
           FIRE_SERVICE_CENTRES_CSV=os.path.join(FIX, "koordinati.csv"))
checks = 0


def run(*args, env=ENV):
    return subprocess.run([sys.executable, VODA, *args], capture_output=True, text=True, env=env)


def out(*args):
    r = run(*args, "--json")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


def fresh():
    shutil.copy(os.path.join(FIX, "vodoiztochnitsi.csv"), TABLE)


def main():
    fresh()
    # населено място: точните първи, приблизителните и без координати не получават линк
    d = out("masto", "Крушовене")
    ok((d["obshto"], d["tochni"], d["priblizitelni"], d["bez_koordinati"]) == (4, 2, 1, 1), d)
    ok([v["id"] for v in d["vodoiztochnitsi"]] == ["00001-001", "00001-002", "00001-003", "00001-004"], "ред")
    ok(d["vodoiztochnitsi"][0]["navigatsiya"].endswith("43.6512000,24.4084000"), "линк за точна")
    ok(d["vodoiztochnitsi"][2]["navigatsiya"] is None and d["vodoiztochnitsi"][2]["tochni_koordinati"] is False, "без линк за приблизителна")
    ok(d["uchastak"] == "УПБЗН – Долна Митрополия", d)
    text = run("masto", "с. Крушовене").stdout
    ok("проверена на място" in text and "приблизителна – по улица" in text and "няма координати" in text, text)
    # място без точни координати → най-близките от другаде; място без нищо – също
    d = out("masto", "Гиген")
    ok(d["tochni"] == 0 and d["nay_blizki_drugade"][0]["id"] == "00001-001", d)
    d = out("masto", "Долна Митрополия")
    ok(d["obshto"] == 0 and len(d["nay_blizki_drugade"]) == 2, d)
    ok("Няма въведени" in run("masto", "Долна Митрополия").stdout, "няма въведени")
    # повтарящо се име и непознато място
    r = run("masto", "Асеново")
    ok(r.returncode == 2 and "AMBIGUOUS" in r.stderr, r.stderr)
    ok(run("masto", "Асеново", "--obshtina", "Никопол").returncode == 0, "общината стеснява")
    r = run("masto", "Бургас")
    ok(r.returncode == 2 and "NOT_FOUND" in r.stderr, "извън РДПБЗН – Плевен")
    # най-близките: само точните, освен ако не се поиска
    d = out("blizo", "--lat", "43.6481", "--lon", "24.4061", "--broi", "2")
    ok([v["id"] for v in d["vodoiztochnitsi"]] == ["00001-001", "00001-002"], d)
    ok(300 < d["vodoiztochnitsi"][0]["razstoyanie_m"] < 420, d["vodoiztochnitsi"][0]["razstoyanie_m"])
    d = out("blizo", "--link", "https://www.google.com/maps?q=43.6481,24.4061", "--s-priblizitelni", "--broi", "1")
    ok(d["vodoiztochnitsi"][0]["id"] == "00001-003", "с приблизителните")
    ok(out("blizo", "--link", "https://www.google.com/maps/place/x/@43.6481,24.4061,17z")["vodoiztochnitsi"], "линк с @")
    ok(out("blizo", "--masto", "Гиген", "--radius-m", "500")["vodoiztochnitsi"] == [], "радиус")
    r = run("blizo", "--link", "https://maps.app.goo.gl/abc")
    ok(r.returncode == 2 and "BAD_INPUT" in r.stderr, "съкратен линк")
    r = run("blizo", "--lat", "24.4", "--lon", "43.6")
    ok(r.returncode == 2 and "разменени" in r.stderr, "разменени координати")
    # служба, участък и статистика
    d = out("sluzhba", "Долна Митрополия")
    ok(d["obshto"] == 4 and len(d["naseleni_mesta"]) == 1, d)
    ok(out("sluzhba", "Плевен")["obshto"] == 4 and run("sluzhba", "Плевен", "--samo-uchastak").returncode == 2, "служба срещу участък")
    d = out("statistika")
    ok((d["obshto"], d["tochni"], d["priblizitelni"], d["bez_koordinati"]) == (6, 2, 2, 2), d)
    ok("гр. Долна Митрополия (общ. Долна Митрополия)" in d["bez_vodoiztochnitsi"] and not any("Бургас" in x for x in d["bez_vodoiztochnitsi"]), d)
    # износ: само точните, освен ако не се поиска
    kml = os.path.join(TMP, "x.kml")
    ok(out("eksport", "--masto", "Крушовене", "-o", kml)["broi"] == 2, "kml")
    ok(open(kml, encoding="utf-8").read().count("<Placemark>") == 2 and "24.4084000,43.6512000,0" in open(kml, encoding="utf-8").read(), "kml съдържание")
    ok(run("eksport", "--masto", "Гиген", "-o", kml).returncode == 2, "няма точни за износ")
    # проба: нищо не се записва
    before = open(TABLE, encoding="utf-8").read()
    d = out("dobavi", "--masto", "Гиген", "--tip", "надземен", "--lat", "43.7010", "--lon", "24.4840", "--dry-run")
    ok(d["deystvie"] == "dobaven" and d["dry_run"] and open(TABLE, encoding="utf-8").read() == before, "проба")
    # нов водоизточник: следващ номер, проверена, с дата и кой
    d = out("dobavi", "--masto", "Гиген", "--tip", "надземен", "--lat", "43.7010", "--lon", "24.4840",
            "--orientir", "пред кметството", "--proveril", "Иван Дъбов")
    v = d["vodoiztochnik"]
    ok(v["id"] == "00004-003" and v["tochnost"] == "проверена" and v["proveril"] == "Иван Дъбов" and v["proveren_na"], v)
    ok(v["sluzhba"] == "РСПБЗН – Гулянци" and v["naseleno_masto"] == "с. Гиген", v)
    # същата точка втори път (на няколко метра) обновява записа, не създава втори
    d = out("dobavi", "--masto", "Гиген", "--lat", "43.70103", "--lon", "24.48402", "--diametar", "80")
    ok(d["deystvie"] == "obnoven" and d["vodoiztochnik"]["id"] == "00004-003", d)
    ok(d["vodoiztochnik"]["diametar"] == "80" and d["vodoiztochnik"]["orientir"] == "пред кметството", "допълва, не трие")
    ok(out("masto", "Гиген")["obshto"] == 3, "един запис, не два")
    # далеч от населеното място се отказва; с --vapreki минава
    r = run("dobavi", "--masto", "Гиген", "--lat", "43.5", "--lon", "24.6")
    ok(r.returncode == 2 and "TOO_FAR" in r.stderr, r.stderr)
    ok(out("dobavi", "--masto", "Гиген", "--lat", "43.5", "--lon", "24.6", "--vapreki", "--dry-run")["deystvie"] == "dobaven", "--vapreki")
    ok(run("dobavi", "--masto", "Гиген", "--vid", "кладенец", "--lat", "43.7", "--lon", "24.48").returncode == 2, "непознат вид")
    # потвърждаване на място на хидрант без координати и на приблизителен
    d = out("potvardi", "00001-004", "--lat", "43.6490", "--lon", "24.4070", "--proveril", "Иван Дъбов")
    ok(d["vodoiztochnik"]["tochnost"] == "проверена" and d["premesten_m"] is None, d)
    d = out("potvardi", "00001-003", "--link", "43.6485, 24.4065")
    ok(d["premesten_m"] and d["vodoiztochnik"]["tochni_koordinati"], d)
    ok(out("masto", "Крушовене")["tochni"] == 4, "след потвърждаването")
    ok(run("potvardi", "99999-001", "--lat", "43.6", "--lon", "24.4").returncode == 2, "няма такъв номер")
    # промяна на полета; координатите не се сменят оттук
    d = out("promeni", "00001-001", "sastoyanie=неизправен", "belezhka=без капак")
    ok(d["deystvie"] == "promenen" and set(d["promeni"]) == {"sastoyanie", "belezhka"}, d)
    ok(out("promeni", "00001-001", "sastoyanie=неизправен")["deystvie"] == "bez_promyana", "идемпотентно")
    ok("състояние: неизправен" in run("masto", "Крушовене").stdout, "състоянието се показва")
    ok(run("promeni", "00001-001", "lat=43.1").returncode == 2, "координати само с potvardi")
    # файлът остава каноничен: същите колони, подреден
    lines = open(TABLE, encoding="utf-8").read().splitlines()
    ok(lines[0].startswith("id,ekatte,naseleno_masto") and len(lines) == 8, len(lines))
    ok([x.split(",")[0] for x in lines[1:4]] == ["00004-001", "00004-002", "00004-003"], "подредба")
    # сверка с карта (KML): познатите точки се прескачат, новите се показват и се записват само с --zapishi
    fresh()
    kml = os.path.join(TMP, "karta.kml")
    marks = [("Крушовене", "Подземен хидрант", 43.6512300, 24.4084200),            # на ~4 m от 00001-001
             ("Крушовене", "Подземен хидрант (заринат)", 43.6400000, 24.4000000),
             ("Крушовене", '<img src="https://example.org/a.jpg" /><br>', 43.6410000, 24.4010000),
             ("Гиген", "Червен надземен хидрант", 43.7010000, 24.4840000),
             ("Несъществуващо", "Надземен хидрант", 43.6000000, 24.4000000)]
    with open(kml, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><Folder><name>слой</name>'
                + "".join(f"<Placemark><name>{n}</name><description><![CDATA[{d}]]></description><Point><coordinates>{lo},{la},0"
                          "</coordinates></Point></Placemark>" for n, d, la, lo in marks) + "</Folder></Document></kml>")
    d = out("karta", "--kml", kml)
    ok((d["tochki_v_kartata"], d["veche_v_tablitsata"], len(d["novi"]), len(d["nepoznati"])) == (5, 1, 3, 1), d)
    ok([(m["tip"], m["belezhka"]) for m in d["novi"]] == [("подземен", "заринат"), ("", "типът не е посочен в картата (само снимка)"),
                                                           ("надземен", "червен")], d["novi"])
    ok(d["zapisani"] == [] and len(open(TABLE, encoding="utf-8").read().splitlines()) == 7, "без --zapishi не се записва")
    ok("NOT_FOUND" in d["nepoznati"][0]["prichina"], d["nepoznati"])
    d = out("karta", "--kml", kml, "--zapishi", "--proveril", "Иван Дъбов", "--dry-run")
    ok(len(d["zapisani"]) == 3 and len(open(TABLE, encoding="utf-8").read().splitlines()) == 7, "проба")
    d = out("karta", "--kml", kml, "--zapishi", "--proveril", "Иван Дъбов")
    ok([v["id"] for v in d["zapisani"]] == ["00001-005", "00001-006", "00004-003"], d["zapisani"])
    ok(all(v["proveril"] == "Иван Дъбов" and v["tochnost"] == "проверена" for v in d["zapisani"]), d["zapisani"])
    d = out("karta", "--kml", kml, "--zapishi")
    ok((d["veche_v_tablitsata"], d["novi"], d["zapisani"]) == (4, [], []), "повторната сверка не добавя нищо")
    ok(d["nyama_gi_v_kartata"] == [], d["nyama_gi_v_kartata"])
    r = run("karta", "--kml", os.path.join(FIX, "naseleni_mesta.csv"))
    ok(r.returncode != 0 and "MAP_PRIVATE" in r.stderr, r.stderr)
    r = run("karta")
    ok(r.returncode != 0 and "BAD_INPUT" in r.stderr, r.stderr)
    fresh()
    spisak = os.path.join(TMP, "tochki.txt")
    with open(spisak, "w", encoding="utf-8") as f:
        f.write("".join(f"{n}|{'[снимка]' if '<img' in d else d}|{la}|{lo}\n" for n, d, la, lo in marks))
    d2 = out("karta", "--tochki", spisak)
    ok((d2["tochki_v_kartata"], d2["veche_v_tablitsata"], len(d2["novi"]), len(d2["nepoznati"])) == (5, 1, 3, 1), d2)
    ok([m["tip"] for m in d2["novi"]] == ["подземен", "", "надземен"] and d2["novi"][0]["belezhka"] == "заринат", d2["novi"])
    with open(spisak, "w", encoding="utf-8") as f:
        f.write("Крушовене|без координати\n")
    r = run("karta", "--tochki", spisak)
    ok(r.returncode != 0 and "BAD_INPUT" in r.stderr, r.stderr)
    fresh()
    # без ключ и без файл скриптът го казва и не измисля
    r = run("masto", "Крушовене", env=dict(BASE, FIRE_SERVICE_NO_KEY="1", FIRE_SERVICE_RAIONI_CSV=ENV["FIRE_SERVICE_RAIONI_CSV"]))
    ok(r.returncode != 0 and "NO_KEY" in r.stderr, r.stderr)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"OK – {checks} проверки")


if __name__ == "__main__":
    main()
