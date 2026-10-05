#!/usr/bin/env python3
"""Тестове за koya_sluzhba.py и sluzhiteli.py върху измислени данни (tests/fixtures в корена на
хранилището). Истинската таблица и списъкът на служителите са зад n8n и не се пипат тук."""
import json
import os
import subprocess
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.abspath(os.path.join(SKILL, "..", "..", "..", ".."))
KS = os.path.join(SKILL, "_shared", "scripts", "koya_sluzhba.py")
ST = os.path.join(SKILL, "_shared", "scripts", "sluzhiteli.py")
BASE = {k: v for k, v in os.environ.items() if not k.startswith("FIRE_SERVICE_")}
ENV = dict(BASE, FIRE_SERVICE_NO_KEY="1",
           FIRE_SERVICE_RAIONI_CSV=os.path.join(ROOT, "tests", "fixtures", "naseleni_mesta.csv"),
           FIRE_SERVICE_STAFF_CSV=os.path.join(ROOT, "tests", "fixtures", "staff.csv"))
NO_DATA = dict(BASE, FIRE_SERVICE_NO_KEY="1")
checks = 0


def run(script, *args, env=ENV):
    return subprocess.run([sys.executable, script, *args], capture_output=True, text=True, env=env)


def out(script, *args, env=ENV):
    return json.loads(run(script, *args, env=env).stdout)


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


def main():
    # населено място → служба и участък
    rows = out(KS, "Крушовене", "--json")
    ok(len(rows) == 1 and rows[0]["sluzhba"] == "РСПБЗН – Плевен" and rows[0]["uchastak"] == "УПБЗН – Долна Митрополия", rows)
    ok(rows[0]["sektor_sod"].endswith("Велико Търново"), rows)
    ok(len(out(KS, "с. Ново село", "--json")) == 2, "две места с това име")
    ok(out(KS, "Ново село", "--oblast", "обл. Русе", "--json")[0]["rdpbzn"] == "РДПБЗН – Русе", "областта стеснява")
    ok(out(KS, "Асеново", "--obshtina", "Левски", "--json")[0]["sluzhba"] == "РСПБЗН – Никопол", "по заповедта, не по общината")
    ok(len(out(KS, "--sod", "Монтана", "--json")) == 3, "по сектор СОД")
    ok([r["naseleno_masto"] for r in out(KS, "--sluzhba", "Кнежа", "--json")] == ["Искър"], "по служба")
    r = run(KS, "Крушовeне")  # латинско „e“ – няма точно съвпадение, дава най-близкото
    ok("Няма точно съвпадение" in r.stdout and "Крушовене" in r.stdout, r.stdout)
    r = run(KS, "Несъществуващо")
    ok(r.returncode == 2 and "NOT_FOUND" in r.stdout, r.stdout)
    # --spravka: районната служба за документ на РДПБЗН – Плевен; неопределимото → ПЛЕВЕН
    for place, kw, want in [("Одърне", [], "ЛЕВСКИ"), ("Долна Митрополия", [], "ПЛЕВЕН"), ("Гиген", [], "ГУЛЯНЦИ"),
                            ("Червен бряг", [], "ЧЕРВЕН БРЯГ"), ("Бургас", [], "ПЛЕВЕН"), ("Несъществуващо", [], "ПЛЕВЕН"),
                            ("Искър", ["--obshtina", "Искър"], "КНЕЖА"), ("Асеново", ["--obshtina", "Левски"], "НИКОПОЛ")]:
        got = out(KS, place, *kw, "--spravka")["unit"]
        ok(got == want, (place, got, want))
    # файлът може да дойде и с --csv (редове от инструмента raioni на конектора)
    ok(len(out(KS, "Гиген", "--json", "--csv", ENV["FIRE_SERVICE_RAIONI_CSV"], env=NO_DATA)) == 1, "--csv")
    # без ключ и без файл скриптът го казва и не измисля
    r = run(KS, "Гиген", env=NO_DATA)
    ok(r.returncode != 0 and "NO_KEY" in r.stderr, r.stderr)

    # служителите
    d = out(ST, "--zveno", "Кнежа", "--dl", "началник", "--json")
    ok(len(d["rows"]) == 1 and d["rows"][0]["zveno"] == "РСПБЗН – Кнежа", d)
    d = out(ST, "Бранко", "--spravka")
    ok(d["match"] == "галено име" and len(d["rows"]) == 1, d)
    b = d["rows"][0]
    ok(b["ime"] == "Бранимир Елхов", b)
    ok(b["uvod"] == "началник на дежурна смяна в група „ПГ и СД” при РСПБЗН – Плевен", b)
    ok(b["signer_title"] == "НАЧАЛНИК НА ДЕЖУРНА СМЯНА" and b["unit"] == "ПЛЕВЕН", b)
    ok(b["izgotvil"] == "мл. експерт" and "email" in b, b)
    ok(len(out(ST, "Бранимир", "--spravka")["rows"]) == 1, "„Бранимир“ не трябва да хваща бащиното „Бранимиров“")
    ok(len(out(ST, "Краси", "--spravka")["rows"]) == 2, "галено име с двама души")
    me = [x for x in out(ST, "Дъбов", "--spravka")["rows"] if x["ime"] == "Иван Дъбов"][0]
    ok(me["signer_title"] == "ИНСПЕКТОР В ГРУПА „ОЦ”" and me["unit"] is None and me["izgotvil"] == "инспектор IV ст.", me)
    ok(out(ST, "--direktor")["direktor"] == {"label": "ДИРЕКТОР:", "rank": "КОМИСАР", "name": "Стоян Кестенов"}, "директор")
    ok(out(ST, "--nachalnik", "Левски")["nachalnik"]["ime"] == "Петър Бадемов", "началник")
    n = out(ST, "--nachalnik", "Кнежа")["nachalnik"]  # ВПД: званието е собственото, след наклонената черта
    ok(n["vpd"] is True and n["zvanie"] == "Инспектор" and n["ime"] == "Тодор Глогов", n)
    ok(len(out(ST, "--nezaeti", "--json")["rows"]) == 1, "незаети длъжности")

    # --profil --zapis: данните на потребителя от реда на whoami (конектор)
    row = {"zveno": "РСПБЗН – Плевен", "podrazdelenie": "ГРУПА „ПОЖАРОГАСИТЕЛНА И СПАСИТЕЛНА ДЕЙНОСТ“",
           "dlazhnost": "КОМАНДИР НА ЕКИП", "zvanie": "Младши експерт", "ime": "Георги Малинов",
           "ime_palno": "Георги Петров Малинов"}
    p = out(ST, "--profil", "--zapis", json.dumps({"client": "Георги Малинов", "admin": False, "staff": row}, ensure_ascii=False),
            env=NO_DATA)["profil"]
    ok(p["ime"] == "Георги Малинов" and p["spravka_izgotvil"] == "мл. експерт" and p["izgotvil_short"] == "Г. Малинов", p)
    ok(p["spravka_uvod"] == "командир на екип в група „ПГ и СД” при РСПБЗН – Плевен", p)
    ok(p["expert_title"] == "мл. експерт" and p["obrazovanie"] == "Висше" and p["specialnost"] == "Пожарна и аварийна безопасност", p)
    ok(p["expert_position"] == "командир на екип в група ПГ и СД на РСПБЗН – Плевен към РДПБЗН – Плевен при ГДПБЗН – МВР", p)
    ok(out(ST, "--spravka", "--zapis", json.dumps(row, ensure_ascii=False), env=NO_DATA)["rows"][0]["izgotvil"] == "мл. експерт", "--spravka --zapis")
    r = run(ST, "--profil", env=NO_DATA)
    ok(r.returncode != 0 and "NO_KEY" in r.stderr and "whoami" in r.stderr, r.stderr)
    r = run(ST, "Дъбов", env=NO_DATA)
    ok(r.returncode != 0 and "NO_KEY" in r.stderr, r.stderr)

    # каталогът за падащите менюта – без имена
    k = out(ST, "--katalog")
    for lst in ("zvaniya", "dlazhnosti", "unit"):
        keys = [e["key"] for e in k[lst]]
        ok(keys and len(keys) == len(set(keys)), (lst, "празен списък или повтарящ се key"))
    ok([e["name"] for e in k["zvaniya"]][:2] == ["комисар", "главен инспектор"], k["zvaniya"])
    names = [e["name"] for e in k["dlazhnosti"]]
    ok("инспектор IV степен" in names and "младши инспектор III степен" in names and "началник на РСПБЗН" in names, names)
    ok(not any("І" in x or "(" in x for x in names), "кирилско І или скоби в длъжност")
    u = {e["name"]: e for e in k["unit"]}
    ok(u["УПБЗН – Сторгозия"]["letterhead"] == "ПЛЕВЕН" and u["РСПБЗН – Червен бряг"]["key"] == "rspbzn_cherven_bryag", u)
    ok("Дъбов" not in json.dumps(k, ensure_ascii=False), "в каталога няма имена")
    print(f"OK – {checks} проверки")


if __name__ == "__main__":
    main()
