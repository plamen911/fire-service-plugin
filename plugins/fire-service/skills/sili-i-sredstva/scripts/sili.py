#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sili.py — изчисляване на необходимите сили и средства за гасене на пожар.

Смята САМО по „Методика за определяне на необходимите средства и сили за гасене на пожар“ –
Приложение № 5 към чл. 7, ал. 6 от Указанията за разработване на планове за пожарогасене,
рег. № Iз-2749/18.11.2010 г. на МВР. Всяка стъпка в отговора носи номера на формулата от
методиката; табличните стойности са от таблиците към нея (`references/tablitsi.json`).
Каквото методиката не дава (загуби на напор в шлангови линии, време за работа с ВДА), скриптът
не смята.

    python3 scripts/sili.py tvardi --forma krag --vl 1.0 --i 0.20 --t-dv 6 --struinik В
    python3 scripts/sili.py tvardi --forma pravoagalnik --a 12 --n 2 --vl-red 6.1 --i-red 10 \\
        --t-dv 8 --t-r 5 --ataka front2 --struinik С --n-zashtita 2 --q-pa 40
    python3 scripts/sili.py tvardi --fp 300 --forma pravoagalnik --a 15 --b 20 --i 0.15 --struinik В
    python3 scripts/sili.py rezervoar --d 22.8 --sasedni 2 --struinik В --t-kipene 35 --pgv ПГВ-120
    python3 scripts/sili.py obem --a 6 --l 10 --h-pn 1.2 --pgv ПГВ-120
    python3 scripts/sili.py prah --fp 40 --i-red 3.2 --struinik rachen --w-pa 1000
    python3 scripts/sili.py prah --gaz 3.5
    python3 scripts/sili.py tablitsi --tarsi склад          # редове от таблици 1, 2 и 7 по текст
    python3 scripts/sili.py tablitsi 10                     # цяла таблица

Отговорът е JSON: `vhodni` (с какво е смятано, вкл. приетите по подразбиране стойности),
`stapki` (формула, израз, стойност, мерна единица) и `rezultat`. Бройките (струйници, екипи,
автомобили) се закръглят нагоре. Грешка: {"ok": false, "error": …}, код 2.
"""
import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TABLES = os.path.join(os.path.dirname(HERE), "references", "tablitsi.json")
Q_EKIP = 14.0          # l/s – най-големият разход, който подава един екип в пълен състав (т. I.7)
STR_NA_EKIP = {"С": 4, "В": 2}   # струйници, които подава един екип (формула 21)
T_PENA = 10            # min – нормативно време за гасене, една пенна атака (формули 32 и 33)
K_ZAPAS = 3            # коефициент на запаса на пенообразувател (формула 32)
K_RAZRUSHAVANE = 3     # коефициент на разрушаване на пяната (формула 33)
Z_PENA = 0.3           # m – най-малкият слой пяна над пожарното натоварване (формула 34)
T_PRAH = 30            # s – нормативно време за гасене с прах (формула 39)
I_PRAH = 0.3           # kg/s.m2 – прахове с общо предназначение (формула 36)
Q_OTN_PRAH = 1.0       # kg/m3 – относителен разход на прах при факелно горене (формула 40)


class Problem(Exception):
    pass


def tables():
    with open(TABLES, encoding="utf-8") as f:
        return json.load(f)


def num(x, digits=2):
    x = round(float(x), digits)
    return int(x) if x == int(x) else x


def up(x):
    """Whole pieces: 2.01 → 3; float noise (3.0000000001) does not add one."""
    return max(1, math.ceil(round(x, 6)))


class Calc:
    def __init__(self, kind):
        self.kind, self.steps, self.used, self.notes = kind, [], {}, []

    def step(self, formula, name, expr, value, unit, digits=2):
        self.steps.append({"formula": formula, "ime": name, "izraz": expr, "stoinost": num(value, digits), "merna": unit})
        return value

    def answer(self, result):
        return {"ok": True, "vid": self.kind, "vhodni": self.used, "stapki": self.steps, "rezultat": result,
                "belezhki": self.notes, "iztochnik": tables()["iztochnik"]}


def row(table, number):
    for r in tables()[table]["redove"]:
        if r.get("no") == str(number):
            return r
    raise Problem(f"В {table.replace('tablitsa_', 'таблица ')} няма ред „{number}“ – виж: sili.py tablitsi {table[-1]}")


def from_range(calc, what, r, key, low):
    lo, hi = r[key]
    value = lo if low else hi
    if lo != hi:
        calc.notes.append(f"{what}: по таблицата е от {num(lo, 3)} до {num(hi, 3)} – взета е "
                          f"{'долната' if low else 'горната'} граница ({num(value, 3)}).")
    if r.get("proveri"):
        calc.notes.append(f"{what}: ред {r['no']} е отпечатан в източника с изместени стойности – провери в оригинала.")
    return value


def nozzle(a, calc):
    """--struinik: С, В, a type from table 11, or a flow in l/s → (label, l/s, nozzles per crew or None)."""
    text = str(a.struinik or "").strip()
    text = {"c": "С", "b": "В"}.get(text.lower(), text)   # Latin C and B typed for the Cyrillic С and В
    if not text:
        raise Problem("Дай --struinik: С, В, тип от таблица 11 (напр. Р-12) или разход в l/s")
    for r in tables()["tablitsa_11"]["redove"]:
        if r["tip"].lower() == text.lower():
            calc.used["struinik"] = f"{r['ime']} – {num(r['voda_l_s'])} l/s (таблица 11)"
            return r["tip"], float(r["voda_l_s"]), STR_NA_EKIP.get(r["tip"])
    try:
        q = float(text.replace(",", "."))
    except ValueError:
        raise Problem(f"Непознат струйник „{text}“ – С, В, тип от таблица 11 или разход в l/s") from None
    if q <= 0:
        raise Problem("Разходът на струйника трябва да е над 0")
    calc.used["struinik"] = f"{num(q)} l/s (зададен)"
    return f"{num(q)} l/s", q, None


def positive(value, name, zero=False):
    if value is None:
        raise Problem(f"Липсва {name}")
    if value < 0 or (value == 0 and not zero):
        raise Problem(f"{name} трябва да е {'≥ 0' if zero else 'над 0'}")
    return value


# ── I. Твърди горими вещества ────────────────────────────────────────────────

SHAPES = {"krag": ("кръг", 1.0), "polukrag": ("полукръг", 0.5), "sektor": ("сектор 90°", 0.25),
          "pravoagalnik": ("правоъгълник", None)}


def cmd_tvardi(a):
    c = Calc("твърди горими вещества (раздел I)")
    if a.forma not in SHAPES:
        raise Problem("--forma е krag, polukrag, sektor или pravoagalnik")
    shape, share = SHAPES[a.forma]
    c.used["forma"] = shape
    rect = share is None
    hg = positive(a.hg, "--hg")
    c.used["hg"] = f"{num(hg)} m" + (" (ръчни струйници)" if hg == 5 else " (лафетни струйници)" if hg == 10 else "")

    # необходима интензивност
    if a.i is not None:
        inten = positive(a.i, "--i")
        c.used["i"] = f"{num(inten, 3)} l/s.m2 (зададена)"
    elif a.i_red:
        r = row("tablitsa_2", a.i_red)
        inten = from_range(c, "Интензивност", r, "i", a.dolna)
        c.used["i"] = f"{num(inten, 3)} l/s.m2 – таблица 2, ред {r['no']}: {r['obekt']}"
    else:
        raise Problem("Дай интензивността: --i (l/s.m2) или --i-red (ред от таблица 2; sili.py tablitsi --tarsi …)")

    radius = side_b = None
    if a.fp is not None:                      # площта е известна – не се извежда от времето
        fp = positive(a.fp, "--fp")
        c.used["fp"] = f"{num(fp)} m2 (зададена)"
        if rect:
            width = positive(a.a, "--a (ширина на фронта, m)")
            side_b = a.b if a.b is not None else fp / width
            c.used["a"], c.used["b"] = f"{num(width)} m", f"{num(side_b)} m"
        else:
            radius = math.sqrt(fp / (math.pi * share))
            c.used["R"] = f"{num(radius)} m (от площта)"
    else:
        if a.vl is not None:
            vl = positive(a.vl, "--vl")
            c.used["vl"] = f"{num(vl, 3)} m/min (зададена)"
        elif a.vl_red:
            r = row("tablitsa_1", a.vl_red)
            vl = from_range(c, "Линейна скорост", r, "vl", a.dolna)
            c.used["vl"] = f"{num(vl, 3)} m/min – таблица 1, ред {r['no']}: {r['obekt']}"
        else:
            raise Problem("Дай площта на пожара (--fp) или линейната скорост: --vl (m/min) или --vl-red (ред от таблица 1)")
        t_ds = 2 if a.pii else a.t_ds
        t_dv, t_r = positive(a.t_dv, "--t-dv (време за движение, min)", zero=True), a.t_r
        if not 3 <= t_r <= 5:
            c.notes.append(f"Времето за разгръщане по методиката е от 3 до 5 min; зададено е {num(t_r)} min.")
        c.used.update({"t_ds": f"{num(t_ds)} min" + (" (има ПИИ/ПГИ)" if a.pii else " (до съобщението)"),
                       "t_dv": f"{num(t_dv)} min", "t_r": f"{num(t_r)} min"})
        t_sv = c.step("(1)", "Време за свободно развитие на пожара", "tсв = tд.с. + tдв. + tр.", t_ds + t_dv + t_r, "min")
        t3 = positive(a.t3, "--t3", zero=True) if a.t3 is not None else None
        if t_sv <= 10:
            path, expr, f_round, f_rect = 0.5 * vl * t_sv, "0,5.vл.tсв", "(2)", "(5)"
            if t3 is not None:
                c.notes.append("--t3 не е приложено: формулите с t3 (4 и 7) са за tсв над 10 min.")
                t3 = None
        else:
            t2 = t_sv - 10
            path, expr, f_round, f_rect = 5 * vl + vl * t2, "5.vл + vл.t2", "(3)", "(6)"
            if t3 is not None:
                path += 0.5 * vl * t3
                expr, f_round, f_rect = "5.vл + vл.t2 + 0,5.vл.t3", "(4)", "(7)"
                c.used["t3"] = f"{num(t3)} min (от въвеждането на първите струи до локализирането)"
        if rect:
            width, n = positive(a.a, "--a (ширина на фронта, m)"), a.n
            if n not in (1, 2):
                raise Problem("--n (посоки на разпространение) е 1 или 2")
            c.used["a"], c.used["n"] = f"{num(width)} m", n
            fp = c.step(f_rect, "Площ на пожара", f"Fп = n.a.({expr})", n * width * path, "m2")
            side_b = a.b if a.b is not None else n * path
            c.used["b"] = f"{num(side_b)} m" + ("" if a.b is not None else " (изминатият от горенето път)")
        else:
            radius = path
            c.step(f_round, "Радиус на пожара", f"R = {expr}", radius, "m")
            name = "Площ на пожара" + ("" if share == 1 else f" ({shape}: по {num(share)} от кръга)")
            fp = c.step(f_round, name, "Fп = π.R²" if share == 1 else f"Fп = {str(share).replace('.', ',')}.π.R²",
                        share * math.pi * radius ** 2, "m2")

    # площ на гасене
    if rect:
        ataka = a.ataka or "perimetar"
        if ataka == "perimetar":
            whole = 2 * hg >= min(width, side_b)
            fg = None if whole else c.step("(8)", "Площ на гасене (по периметъра)", "Fг = 2.hг.(a + b − 2.hг)",
                                           2 * hg * (width + side_b - 2 * hg), "m2")
        elif ataka in ("front1", "front2"):
            sides = int(ataka[-1])
            whole = sides * hg >= side_b
            fg = None if whole else c.step("(12)" if sides == 2 else "(13)", f"Площ на гасене (по фронта, от {sides} стран{'и' if sides == 2 else 'а'})",
                                           "Fг = 2.a.hг" if sides == 2 else "Fг = a.hг", sides * width * hg, "m2")
        else:
            raise Problem("--ataka е perimetar, front1 или front2")
        c.used["ataka"] = {"perimetar": "по периметъра", "front1": "по фронта от едната страна", "front2": "по фронта от двете страни"}[ataka]
    else:
        whole = hg >= radius
        formula = {1.0: "(9)", 0.5: "(10)", 0.25: "(11)"}[share]
        fg = None if whole else c.step(formula, "Площ на гасене (по периметъра)",
                                       ("Fг = π.hг.(2R − hг)" if share == 1 else f"Fг = {str(share).replace('.', ',')}.π.hг.(2R − hг)"),
                                       share * math.pi * hg * (2 * radius - hg), "m2")
    if fg is not None and fg >= fp:
        whole = True
    if whole:
        c.notes.append("Дълбочината на гасене покрива цялата площ на пожара – разходът е по площта на пожара (формула 14).")
        q_g = c.step("(14)", "Необходим разход на вода за гасене", "Qг = Fп.Iг", fp * inten, "l/s")
        area = fp
    else:
        q_g = c.step("(15)", "Необходим разход на вода за гасене", "Qг = Fг.Iг", fg * inten, "l/s")
        area = fg

    label, q_str, per_crew = nozzle(a, c)
    n_g = up(c.step("(17)", "Струйници за гасене", "Nг = Qг / qстр", q_g / q_str, "бр."))
    q_z, n_z = 0.0, 0
    if a.n_zashtita:
        n_z = a.n_zashtita
        q_z = n_z * q_str
        c.used["zashtita"] = f"{n_z} струйника по {num(q_str)} l/s"
    elif a.q_zashtita:
        q_z = positive(a.q_zashtita, "--q-zashtita")
        n_z = up(q_z / q_str)
        c.used["zashtita"] = f"{num(q_z)} l/s"
    q_all = c.step("(16)", "Общ необходим разход на вода", "Qоб = Qг + Qз", q_g + q_z, "l/s") if q_z else q_g
    if n_z:
        c.step("(18)", "Струйници общо", "Nстр = Nг + Nз", n_g + n_z, "бр.")
    spacing = c.step("(19)", "Разстояние между струйниците", "lстр = qстр / (Iг.hг)", q_str / (inten * hg), "m")
    if per_crew:
        crews_g = up(c.step("(21)", "Екипи за гасене", f"Nекипи = Nг / nстр.екип ({per_crew} бр. „{label}“ на екип)", n_g / per_crew, "бр."))
        crews_z = up(n_z / per_crew) if n_z else 0
    else:
        crews_g = up(c.step("(20)", "Екипи за гасене", f"Nекипи = Qг / qекипи ({num(Q_EKIP)} l/s на екип)", q_g / Q_EKIP, "бр."))
        crews_z = up(q_z / Q_EKIP) if q_z else 0
    if crews_z:
        c.step("(22)", "Екипи общо", "Nекипи = Nг.екипи + Nз.екипи", crews_g + crews_z, "бр.")
    result = {"plosht_na_pozhara_m2": num(fp), "plosht_na_gasene_m2": num(area), "razhod_za_gasene_l_s": num(q_g),
              "razhod_obshto_l_s": num(q_all), "struinitsi_za_gasene": n_g, "struinitsi_za_zashtita": n_z,
              "struinitsi_obshto": n_g + n_z, "struinik": label, "razstoyanie_mezhdu_struinitsite_m": num(spacing),
              "ekipi_obshto": crews_g + crews_z}
    if a.q_pa:
        q_pa = positive(a.q_pa, "--q-pa")
        c.used["q_pa"] = f"{num(q_pa)} l/s (разход на помпата)"
        result["pozharni_avtomobili"] = up(c.step("(23)", "Пожарни автомобили", "Nпа = Qоб / (0,8.Qпа)" if q_z else "Nпа = Qг / (0,8.Qпа)",
                                                  q_all / (0.8 * q_pa), "бр."))
        if q_z:
            c.notes.append("Формула 23 в методиката е за разхода за гасене; тук е приложена към общия разход (гасене и защита).")
    else:
        c.notes.append("Броят пожарни автомобили (формула 23) не е смятан – дай разхода на помпата с --q-pa (l/s).")
    return c.answer(result)


# ── II. Резервоари с ЛЗТ и ГТ ────────────────────────────────────────────────

def foam_device(name):
    for r in tables()["tablitsa_14"]["redove"]:
        if r["ured"].lower().replace(" ", "") == str(name).lower().replace(" ", ""):
            return r
    raise Problem(f"Няма уред „{name}“ в таблица 14 – виж: sili.py tablitsi 14")


def cmd_rezervoar(a):
    c = Calc("резервоар с ЛЗТ или ГТ, въздушно-механична пяна (раздел II)")
    d = positive(a.d, "--d (диаметър на горящия резервоар, m)")
    i_g = 1.0 if a.razliv else 0.5
    c.used.update({"d": f"{num(d)} m", "i_ohl_g": f"{num(i_g)} l/s.m" + (" (разлив в обваловката)" if a.razliv else "")})
    label, q_str, per_crew = nozzle(a, c)
    q_og = c.step("(24)", "Вода за охлаждане на горящия резервоар", "Qохл.г = π.Dг.Iохл.г", math.pi * d * i_g, "l/s")
    n_og = up(c.step("(25)", "Струйници за охлаждане на горящия резервоар", "N = Qохл.г / qстр", q_og / q_str, "бр."))
    result = {"voda_ohlazhdane_goryasht_l_s": num(q_og), "struinitsi_ohlazhdane_goryasht": n_og}
    crews = up(c.step("(26)", "Екипи за охлаждане на горящия резервоар",
                      f"N = Nстр / nстр.екип ({per_crew} на екип)" if per_crew else f"N = Qохл.г / qекипи ({num(Q_EKIP)} l/s)",
                      n_og / per_crew if per_crew else q_og / Q_EKIP, "бр."))
    q_os = n_os = 0
    if a.sasedni:
        d_s = positive(a.d_sased if a.d_sased is not None else d, "--d-sased")
        c.used.update({"sasedni": a.sasedni, "d_sased": f"{num(d_s)} m", "i_ohl_s": "0,2 l/s.m"})
        q_os = c.step("(27)", "Вода за охлаждане на съседните резервоари", "Qохл.с = 0,5.n.π.Dс.Iохл.с",
                      0.5 * a.sasedni * math.pi * d_s * 0.2, "l/s")
        n_os = up(c.step("(28)", "Струйници за охлаждане на съседните резервоари", "N = Qохл.с / qстр", q_os / q_str, "бр."))
        crews += up(c.step("(29)", "Екипи за охлаждане на съседните резервоари",
                           f"N = Nстр / nстр.екип ({per_crew} на екип)" if per_crew else f"N = Qохл.с / qекипи ({num(Q_EKIP)} l/s)",
                           n_os / per_crew if per_crew else q_os / Q_EKIP, "бр."))
        result.update({"voda_ohlazhdane_sasedni_l_s": num(q_os), "struinitsi_ohlazhdane_sasedni": n_os})
    result.update({"voda_ohlazhdane_obshto_l_s": num(q_og + q_os), "ekipi_ohlazhdane": crews})

    if a.pgv:
        dev = foam_device(a.pgv)
        q_sol = dev["voda_l_s"] + dev["penoobrazuvatel_l_s"]
        if a.i_g is not None:
            i_foam = positive(a.i_g, "--i-g")
            c.used["i_g"] = f"{num(i_foam, 3)} l/s.m2 (зададена)"
        elif a.t_kipene is not None:
            i_foam = 0.08 if a.t_kipene <= 28 else 0.05
            c.used["i_g"] = f"{num(i_foam, 3)} l/s.m2 (пяна със средна кратност, температура на кипене {num(a.t_kipene)} °C)"
        else:
            raise Problem("За пенната атака дай --t-kipene (°C на горящата течност) или --i-g (l/s.m2 по разтвор; таблица 4)")
        c.used["pgv"] = f"{dev['ured']} – {num(q_sol)} l/s разтвор, {num(dev['penoobrazuvatel_l_s'])} l/s пенообразувател (таблица 14)"
        area = math.pi * d ** 2 / 4
        n_pgv = up(c.step("(30)", "Пеногенератори за гасене", "Nпгв = π.D².Iг / (4.qпгв)", area * i_foam / q_sol, "бр."))
        w = c.step("(32)", "Пенообразувател", f"Wпо = Nпгв.qпгв.по.tн.60.Kз (tн = {T_PENA} min, Kз = {K_ZAPAS})",
                   n_pgv * dev["penoobrazuvatel_l_s"] * T_PENA * 60 * K_ZAPAS, "l", 0)
        result.update({"plosht_na_gorene_m2": num(area), "penogeneratori": n_pgv, "penogenerator": dev["ured"],
                       "penoobrazuvatel_l": num(w, 0), "voda_za_pyana_l_s": num(n_pgv * dev["voda_l_s"])})
        if a.pgv_na_ekip:
            result["ekipi_gasene"] = up(c.step("(31)", "Екипи за гасене", f"N = Nпгв / nпгв.екип ({a.pgv_na_ekip} на екип)",
                                               n_pgv / a.pgv_na_ekip, "бр."))
        else:
            c.notes.append("Екипите за пенната атака (формула 31) не са смятани – дай --pgv-na-ekip (пеногенератори на екип).")
    else:
        c.notes.append("Пенната атака не е смятана – дай --pgv (уред от таблица 14) и --t-kipene или --i-g.")
    return c.answer(result)


# ── III. Гасене с пяна по обем ───────────────────────────────────────────────

def cmd_obem(a):
    c = Calc("гасене с въздушно-механична пяна по обем (раздел III)")
    if a.v is not None:
        v = positive(a.v, "--v")
        c.used["v"] = f"{num(v)} m3 (зададен)"
    else:
        for value, name in ((a.a, "--a"), (a.l, "--l"), (a.h_pn, "--h-pn")):
            positive(value, f"{name} (или целият обем с --v)")
        if a.z < Z_PENA:
            raise Problem(f"Слоят пяна над пожарното натоварване (--z) е най-малко {str(Z_PENA).replace('.', ',')} m")
        h = a.h_pn + a.z
        c.used.update({"a": f"{num(a.a)} m", "l": f"{num(a.l)} m", "h_pn": f"{num(a.h_pn)} m", "z": f"{num(a.z)} m"})
        v = c.step("(34)", "Обем за запълване", "Vп = a.l.hо, hо = hп.н. + z", a.a * a.l * h, "m3")
    q = c.step("(33)", "Необходим разход на пяна", f"Qг = Vп.Kр / tн (Kр = {K_RAZRUSHAVANE}, tн = {T_PENA} min)",
               v * K_RAZRUSHAVANE / T_PENA, "m3/min")
    result = {"obem_m3": num(v), "razhod_na_pyana_m3_min": num(q)}
    if a.pgv:
        dev = foam_device(a.pgv)
        c.used["pgv"] = f"{dev['ured']} – {num(dev['pyana_m3_min'])} m3/min пяна (таблица 14)"
        n = up(c.step("(35)", "Пеногенератори", "Nпгв = Qг / Qпгв", q / dev["pyana_m3_min"], "бр."))
        w = c.step("(32)", "Пенообразувател", f"Wпо = Nпгв.qпгв.по.tн.60.Kз (tн = {T_PENA} min, Kз = {K_ZAPAS})",
                   n * dev["penoobrazuvatel_l_s"] * T_PENA * 60 * K_ZAPAS, "l", 0)
        result.update({"penogeneratori": n, "penogenerator": dev["ured"], "penoobrazuvatel_l": num(w, 0),
                       "voda_za_pyana_l_s": num(n * dev["voda_l_s"])})
        c.notes.append("Пенообразувателят е по формула 32 – методиката определя останалите сили и средства "
                       "„по аналогичен начин, както при гасенето на вертикални резервоари“.")
    else:
        c.notes.append("Броят пеногенератори (формула 35) не е смятан – дай --pgv (уред от таблица 14).")
    return c.answer(result)


# ── IV. Гасене с прах ────────────────────────────────────────────────────────

def cmd_prah(a):
    c = Calc("гасене с огнегасителни прахови състави (раздел IV)")
    if a.gaz is not None:
        q = c.step("(40)", "Необходим разход на прах (факелно горене)", f"Qг = Qг.г..qотн (qотн = {num(Q_OTN_PRAH)} kg/m3)",
                   positive(a.gaz, "--gaz") * Q_OTN_PRAH, "kg/s")
        c.used["gaz"] = f"{num(a.gaz)} m3/s (разход на изтичащия газ)"
        result = {"razhod_na_prah_kg_s": num(q)}
        w = None
    else:
        fp = positive(a.fp, "--fp (площ на пожара, m2) или --gaz")
        if a.i is not None:
            inten = positive(a.i, "--i")
            c.used["i"] = f"{num(inten, 3)} kg/s.m2 (зададена)"
        elif a.i_red:
            r = row("tablitsa_7", a.i_red)
            inten = r["i"]
            c.used["i"] = f"{num(inten, 3)} kg/s.m2 – таблица 7, ред {r['no']}: {r['obekt']}"
        else:
            inten = I_PRAH
            c.used["i"] = f"{num(inten, 3)} kg/s.m2 (прах с общо предназначение)"
        c.used["fp"] = f"{num(fp)} m2"
        q = c.step("(36)", "Необходим разход на прах", "Qг = Fп.Iг", fp * inten, "kg/s")
        w = c.step("(39)", "Количество огнегасителен прах", f"Wп = Fп.Iг.tн (tн = {T_PRAH} s)", fp * inten * T_PRAH, "kg", 0)
        result = {"razhod_na_prah_kg_s": num(q), "prah_kg": num(w, 0)}
    flows = tables()["tablitsa_11"]["prahovi_kg_s"]
    kind = a.struinik or "rachen"
    if kind not in flows:
        raise Problem("--struinik при прах е rachen (5 kg/s) или lafeten (40 kg/s)")
    q_str = flows[kind]
    c.used["struinik"] = f"{'ръчен' if kind == 'rachen' else 'лафетен'} прахов – {q_str} kg/s"
    n = up(c.step("(37)", "Прахови струйници", "Nстр = Qг / qстр", q / q_str, "бр."))
    result["struinitsi"] = n
    if a.str_na_ekip:
        result["ekipi"] = up(c.step("(38)", "Екипи", f"N = Nстр / nстр.екип ({a.str_na_ekip} на екип)", n / a.str_na_ekip, "бр."))
    if a.w_pa and w is not None:
        c.used["w_pa"] = f"{num(a.w_pa)} kg прах в един автомобил"
        result["avtomobili_za_prahovo_gasene"] = up(c.step("(41)", "Автомобили за прахово гасене", "Nпа = Wп / Wпрах", w / a.w_pa, "бр."))
    return c.answer(result)


# ── таблиците ────────────────────────────────────────────────────────────────

def cmd_tablitsi(a):
    data = tables()
    if a.tarsi:
        words = a.tarsi.lower().split()
        found = []
        for key in ("tablitsa_1", "tablitsa_2", "tablitsa_7"):
            for r in data[key]["redove"]:
                if all(w in r["obekt"].lower() for w in words):
                    found.append({"tablitsa": int(key.split("_")[1]), **r})
        return {"ok": True, "tarsi": a.tarsi, "namereni": found, "iztochnik": data["iztochnik"],
                "belezhka": "Таблица 1 – --vl-red; таблица 2 – --i-red (tvardi); таблица 7 – --i-red (prah)."}
    if a.nomer:
        key = f"tablitsa_{a.nomer}"
        if key not in data:
            raise Problem("В скрипта са таблици " + ", ".join(k.split("_")[1] for k in data if k.startswith("tablitsa_")))
        return {"ok": True, **data[key], "iztochnik": data["iztochnik"]}
    return {"ok": True, "tablitsi": {k.split("_")[1]: v["ime"] for k, v in data.items() if k.startswith("tablitsa_")},
            "iztochnik": data["iztochnik"]}


def main():
    ap = argparse.ArgumentParser(description="Сили и средства за гасене – по методиката към Указания № Iз-2749/2010 г.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = lambda s: float(str(s).replace(",", "."))   # noqa: E731  (12,5 and 12.5 both work)

    p = sub.add_parser("tvardi", help="I. Твърди горими вещества – вода")
    p.add_argument("--forma", required=True, help="krag, polukrag, sektor (90°) или pravoagalnik")
    p.add_argument("--fp", type=f, help="площ на пожара, m2 (вместо извеждане от времето)")
    p.add_argument("--vl", type=f, help="линейна скорост на разпространение, m/min")
    p.add_argument("--vl-red", help="ред от таблица 1")
    p.add_argument("--i", type=f, help="необходима интензивност, l/s.m2")
    p.add_argument("--i-red", help="ред от таблица 2")
    p.add_argument("--dolna", action="store_true", help="при диапазон в таблицата – долната граница (по подразбиране горната)")
    p.add_argument("--t-ds", type=f, default=10, help="време до съобщението, min (по методиката 10)")
    p.add_argument("--pii", action="store_true", help="има ПИИ и/или ПГИ – времето до съобщението е 2 min")
    p.add_argument("--t-dv", type=f, help="време за движение до пожара, min")
    p.add_argument("--t-r", type=f, default=5, help="време за разгръщане, min (3 – 5; по подразбиране 5)")
    p.add_argument("--t3", type=f, help="min от въвеждането на първите струи до локализирането")
    p.add_argument("--a", type=f, help="ширина на фронта, m (правоъгълник)")
    p.add_argument("--b", type=f, help="другата страна на пожара, m (правоъгълник; иначе изминатият път)")
    p.add_argument("--n", type=int, default=1, help="посоки на разпространение (1 или 2)")
    p.add_argument("--ataka", help="perimetar (по подразбиране), front1 или front2 – при правоъгълник")
    p.add_argument("--hg", type=f, default=5, help="дълбочина на гасене, m: 5 ръчни, 10 лафетни")
    p.add_argument("--struinik", help="С, В, тип от таблица 11 или разход в l/s")
    p.add_argument("--n-zashtita", type=int, help="струйници за защита (със същия разход)")
    p.add_argument("--q-zashtita", type=f, help="разход за защита, l/s")
    p.add_argument("--q-pa", type=f, help="разход на помпата на пожарния автомобил, l/s")
    p.set_defaults(fn=cmd_tvardi)

    p = sub.add_parser("rezervoar", help="II. Резервоар с ЛЗТ/ГТ – охлаждане и пенна атака")
    p.add_argument("--d", type=f, help="диаметър на горящия резервоар, m")
    p.add_argument("--razliv", action="store_true", help="разлив в обваловката – интензивност за охлаждане 1,0 l/s.m")
    p.add_argument("--sasedni", type=int, help="брой съседни резервоари за охлаждане")
    p.add_argument("--d-sased", type=f, help="диаметър на съседните, m (по подразбиране като горящия)")
    p.add_argument("--struinik", help="струйник за охлаждане: С, В, тип от таблица 11 или l/s")
    p.add_argument("--pgv", help="пенообразуващ уред от таблица 14, напр. ПГВ-120")
    p.add_argument("--t-kipene", type=f, help="температура на кипене на течността, °C (≤ 28 → 0,08; над 28 → 0,05 l/s.m2)")
    p.add_argument("--i-g", type=f, help="интензивност по разтвор, l/s.m2 (напр. от таблица 4)")
    p.add_argument("--pgv-na-ekip", type=int, help="пеногенератори, които подава един екип")
    p.set_defaults(fn=cmd_rezervoar)

    p = sub.add_parser("obem", help="III. Пяна по обем")
    p.add_argument("--v", type=f, help="обем за гасене, m3")
    p.add_argument("--a", type=f, help="ширина, m")
    p.add_argument("--l", type=f, help="дължина, m")
    p.add_argument("--h-pn", type=f, help="височина на пожарното натоварване, m")
    p.add_argument("--z", type=f, default=Z_PENA, help="слой пяна над натоварването, m (най-малко 0,3)")
    p.add_argument("--pgv", help="пенообразуващ уред от таблица 14")
    p.set_defaults(fn=cmd_obem)

    p = sub.add_parser("prah", help="IV. Огнегасителен прах")
    p.add_argument("--fp", type=f, help="площ на пожара, m2")
    p.add_argument("--i", type=f, help="интензивност, kg/s.m2 (по подразбиране 0,3 – прах с общо предназначение)")
    p.add_argument("--i-red", help="ред от таблица 7")
    p.add_argument("--gaz", type=f, help="разход на аварийно изтичащия газ, m3/s (факелно горене – формула 40)")
    p.add_argument("--struinik", help="rachen (5 kg/s, по подразбиране) или lafeten (40 kg/s)")
    p.add_argument("--str-na-ekip", type=int, help="прахови струйници, които подава един екип")
    p.add_argument("--w-pa", type=f, help="прах в един автомобил за прахово гасене, kg")
    p.set_defaults(fn=cmd_prah)

    p = sub.add_parser("tablitsi", help="таблиците към методиката")
    p.add_argument("nomer", nargs="?", help="1, 2, 4, 7, 10, 11 или 14")
    p.add_argument("--tarsi", help="търси обект в таблици 1, 2 и 7")
    p.set_defaults(fn=cmd_tablitsi)

    a = ap.parse_args()
    try:
        result, code = a.fn(a), 0
    except Problem as e:
        result, code = {"ok": False, "error": str(e)}, 2
    print(json.dumps(result, ensure_ascii=False, indent=1))
    sys.exit(code)


if __name__ == "__main__":
    main()
