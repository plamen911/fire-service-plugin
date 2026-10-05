#!/usr/bin/env python3
"""
adr.py — dangerous goods lookup for first responders (ADR 2025 + CEFIC ERICards + ERG 2024).

Read-only. All data is bundled in ../data (no network, no key). One call per step:

    adr.py tarsi --un 1203                       # search: by UN number,
    adr.py tarsi --tabela "33/1203"              #   by the orange plate (HIN / UN),
    adr.py tarsi --ime хлор                      #   by name (Bulgarian or English),
    adr.py tarsi --hin X423                      #   by hazard identification number,
    adr.py tarsi --klas 2                        #   by class
    adr.py karta --un 1203                       # the full reference card
    adr.py karta --id 549
    adr.py proizshestvie --un 1017 --vid tech --kolichestvo golyamo --vreme nosht \
                         --vyatar slab --sad avtocisterna        # incident mode
    adr.py hin --kod X423                        # what a hazard identification number means
    adr.py ukazanie --nomer 147                  # an ERG 2024 guide in Bulgarian

Every command prints Bulgarian text for the chat; --json prints the same facts as JSON.
Exit codes: 0 ok, 2 nothing found, 3 ambiguous (several entries – the candidates are listed).
"""
import argparse
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("ADR_DATA_DIR") or os.path.join(os.path.dirname(HERE), "data")

SOURCES = ("Източници: ADR 2025 (ООН/ИКЕ, Таблица А, с поправка Corr.2); ERI карти на CEFIC (ERICards, "
           "превод от английския оригинал); ERG 2024 (PHMSA/Transport Canada – разстояния и указания).")
DISCLAIMER = ("Справочна информация за първите действия. Тя не заменя информационния лист за безопасност, "
              "товарните документи, указанията на ръководителя на място и на специалистите (сектор СОД).")

VID = {"tech": "теч/разлив без пожар", "pozhar": "пожар", "tech-pozhar": "теч/разлив и пожар",
       "zaplaha": "няма теч и пожар (застрашен товар)"}
VYATAR = {"slab": "слаб вятър (< 10 km/h)", "umeren": "умерен вятър (10–20 km/h)", "silen": "силен вятър (> 20 km/h)"}
SAD = {"zhp-cisterna": "жп цистерна", "avtocisterna": "автоцистерна или полуремарке-цистерна",
       "selskostopanska-cisterna": "селскостопанска цистерна (за амоняк)",
       "ednotonni-sadove": "няколко еднотонни съда",
       "malki-butilki": "няколко малки бутилки"}
GAS_BG = {"HCl": "хлороводород (HCl)", "H2S": "сероводород (H2S)", "SO2": "серен диоксид (SO2)",
          "HF": "флуороводород (HF)", "PH3": "фосфин (PH3)", "HBr": "бромоводород (HBr)",
          "NO2": "азотен диоксид (NO2)", "NH3": "амоняк (NH3)", "HCN": "циановодород (HCN)",
          "Br2": "бром (Br2)", "HI": "йодоводород (HI)", "Cl2": "хлор (Cl2)"}
USLOVIE = {"": "", "voda": "при разлив във вода", "susha": "при разлив на сушата", "orazhie": "при използване като оръжие"}


# ------------------------------------------------------------------ data
def _csv(name):
    with open(os.path.join(DATA, name), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _json(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


class Data:
    _cache = {}

    def __getattr__(self, key):
        c = Data._cache
        if key not in c:
            if key == "veshtestva":
                c[key] = _csv("veshtestva.csv")
            elif key == "hin":
                c[key] = {r["hin"]: r["opisanie"] for r in _csv("hin.csv")}
            elif key == "klasove":
                c[key] = {r["klas"]: r for r in _csv("klasove.csv")}
            elif key == "eri":
                c[key] = _json("eri_karti.json")
            elif key == "erg":
                c[key] = _json("erg_ukazaniya.json")
            elif key == "t1":
                c[key] = _csv("erg_tablica1.csv")
            elif key == "t3":
                c[key] = _csv("erg_tablica3.csv")
            elif key == "sinonimi":
                c[key] = {r["un"]: [x.strip() for x in r["dumi"].split(";")] for r in _csv("sinonimi.csv")}
            elif key == "voda":
                c[key] = {r["un"]: r["gazove"].split() for r in _csv("erg_voda.csv")}
            else:
                raise AttributeError(key)
        return c[key]


D = Data()


def norm(s):
    s = s.casefold().replace("ё", "е").replace("ѝ", "и")
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-zа-я%.]+", " ", s)).strip()


def norm_un(s):
    m = re.search(r"\d{1,4}", s or "")
    return m.group(0).zfill(4) if m else ""


def norm_hin(s):
    s = (s or "").strip().upper().replace("Х", "X").replace(" ", "")   # Cyrillic Х → Latin X
    return s


def parse_tabela(s):
    """'33/1203', '33 1203', 'X423-1428', '1203' → (hin, un). The upper number is the HIN."""
    parts = re.findall(r"[XxХх]?\d[\d.]*[A-Da-d]?", s or "")
    if not parts:
        return "", ""
    if len(parts) == 1:
        p = parts[0]
        return ("", norm_un(p)) if len(re.sub(r"\D", "", p)) == 4 and not p.upper().startswith(("X", "Х")) else (norm_hin(p), "")
    a, b = parts[0], parts[1]
    if len(re.sub(r"\D", "", a)) == 4 and len(re.sub(r"\D", "", b)) < 4:
        a, b = b, a                                   # someone read the plate bottom-up
    return norm_hin(a), norm_un(b)


# ------------------------------------------------------------------ search
def search(un="", hin="", ime="", klas="", limit=25):
    rows = D.veshtestva
    un, hin = norm_un(un) if un else "", norm_hin(hin)
    if un:
        rows = [r for r in rows if r["un"] == un]
    if hin:
        rows = [r for r in rows if hin in [h.strip() for h in r["hin"].split(",")]]
    if klas:
        k = klas.strip().replace(",", ".")
        rows = [r for r in rows if r["klas"] == k or r["klas"].startswith(k + ".")
                or any(e.split("+")[0] == k for e in r["etiketi"].split(", "))]
    if ime:
        q = norm(ime)
        ranked = []
        for r in rows:
            best = None
            for field in [r["ime"], r["ime_en"]] + D.sinonimi.get(r["un"], []):
                n = norm(field)
                head = norm(re.split(r"[,(]| или | or ", field)[0])
                if n == q or head == q:
                    rank = 0
                elif n.startswith(q):
                    rank = 1
                elif re.search(r"(^| )" + re.escape(q), n):
                    rank = 2
                elif q in n:
                    rank = 3
                else:
                    continue
                best = rank if best is None else min(best, rank)
            if best is not None:
                ranked.append((best, len(r["ime"]), r["un"], r))
        ranked.sort(key=lambda t: t[:3])
        rows = [t[3] for t in ranked]
    total = len(rows)
    return rows[:limit] if limit else rows, total


def pick(args):
    """One record from --id / --un [--hin] / --tabela. Returns (record, candidates)."""
    if getattr(args, "id", None):
        rows = [r for r in D.veshtestva if r["id"] == str(args.id)]
        return (rows[0] if rows else None), rows
    hin, un = norm_hin(getattr(args, "hin", "") or ""), norm_un(getattr(args, "un", "") or "")
    if getattr(args, "tabela", None):
        h2, u2 = parse_tabela(args.tabela)
        hin, un = hin or h2, un or u2
    if not un:
        return None, []
    rows = [r for r in D.veshtestva if r["un"] == un]
    if hin:
        exact = [r for r in rows if hin in [h.strip() for h in r["hin"].split(",")]]
        if exact:
            rows = exact
    if len(rows) == 1:
        return rows[0], rows
    if len(rows) > 1 and not hin:
        dflt = [r for r in rows if r["eri_default"] == "1"]
        same = len({(r["eri"], r["erg"], r["hin"]) for r in rows}) == 1
        if len(dflt) == 1 or same:
            return (dflt[0] if dflt else rows[0]), rows
    return None, rows


def line(r):
    plate = f"{r['hin']}/{r['un']}" if r["hin"] else f"UN {r['un']}"
    bits = [f"клас {r['klas']}"]
    if r["etiketi"]:
        bits.append(f"етикети {r['etiketi']}")
    if r["og"]:
        bits.append(f"оп. група {r['og']}")
    bits.append(f"ERI {r['eri']}" if r["eri"] else f"ERG {r['erg']}")
    return f"[{r['id']}] {plate} – {r['ime']} ({'; '.join(bits)})"


# ------------------------------------------------------------------ pieces
def hin_decode(code):
    code = norm_hin(code)
    if code in D.hin:
        return D.hin[code]
    digit = {"2": "газ (отделяне на газ вследствие на налягане или химична реакция)",
             "3": "запалимост на течности (пари) и газове, или самонагряваща се течност",
             "4": "запалимост на твърди вещества, или самонагряващо се твърдо вещество",
             "5": "окисляващо действие (усилва горенето)", "6": "токсичност или опасност от инфекция",
             "7": "радиоактивност", "8": "корозивност", "9": "опасност от спонтанна бурна реакция",
             "0": "без допълнителна опасност"}
    body = code.lstrip("X")
    if not re.fullmatch(r"\d{2,3}", body):
        return ""
    parts = [digit[c] for c in body if c in digit]
    out = "Няма го в списъка на ADR; по цифри: " + "; ".join(dict.fromkeys(parts))
    if len(body) > 1 and body[0] == body[1]:
        out += " (удвоена цифра = засилена опасност)"
    if code.startswith("X"):
        out += "; X = реагира опасно с вода"
    return out


def klas_text(r):
    k = D.klasove.get(r["klas"])
    return f"{r['klas']} – {k['opisanie']}" if k else r["klas"]


def eri_card(code):
    """→ {'zaglavie', 'sections': [(number, title, [bullets])]}"""
    c = D.eri["karti"].get(code)
    if not c:
        return None
    sections, cur = [], None
    for i in c["tekst"]:
        kind, text = D.eri["frazi"][i][:2]
        if kind in ("h1", "h2"):
            num, _, title = text.partition(" ")
            cur = [num.rstrip("."), title, []]
            sections.append(cur)
        elif cur:
            cur[2].append(text)
    return {"kod": code, "zaglavie": c["zaglavie"], "sections": [tuple(s) for s in sections]}


def erg_guide(num):
    """→ {'nomer', 'zaglavie', distances, 'sections': [(key_en, title_bg, [(kind, text)])]}"""
    g = D.erg["ukazaniya"].get(str(num).rstrip("P"))
    if not g:
        return None
    top = {"POTENTIAL HAZARDS", "EMERGENCY RESPONSE"}
    sections, cur = [], None
    for i in g["tekst"]:
        item = D.erg["frazi"][i]
        if item[0] == "h" and item[2] in top:
            continue
        if item[0] == "h" and item[2].isupper():
            cur = [item[2], item[1], []]
            sections.append(cur)
        elif cur is not None:
            cur[2].append(("sub", item[1], item[2]) if item[0] == "h" else (item[0], item[1]))
    sections = [tuple(s) for s in sections if s[2]]
    return {"nomer": str(num), "zaglavie": g["zaglavie"], "izolirane_m": g["izolirane_m"],
            "golyam_razliv_m": g["golyam_razliv_m"], "golyam_razliv_posoka": g.get("golyam_razliv_posoka", ""),
            "pozhar_m": g["pozhar_m"], "sections": sections}


def evac(g):
    """The EVACUATION block of a guide: {English sub-heading: [Bulgarian bullets]}."""
    out, cur = {}, None
    for key, _title, items in g["sections"]:
        if key != "EVACUATION":
            continue
        for item in items:
            if item[0] == "sub":
                cur = out.setdefault(item[2], [])
            elif cur is not None and item[0] == "li":
                cur.append(item[1])
    return out


def lower1(s):
    """Lower the first letter unless the sentence starts with an emphasised (ALL CAPS) word."""
    first = s.split(" ", 1)[0]
    return s if first.isupper() and len(first) > 1 else s[:1].lower() + s[1:]


def guides_of(r, override=""):
    nums = [override] if override else [g for g in r["erg"].split("/") if g]
    return [g for g in (erg_guide(n) for n in nums) if g]


def table1(un, voda=False):
    rows = [t for t in D.t1 if t["un"] == un]
    if not rows:
        return []
    if voda:
        w = [t for t in rows if t["uslovie"] == "voda"]
        return w or [t for t in rows if t["uslovie"] in ("", "susha")]
    land = [t for t in rows if t["uslovie"] in ("", "susha")]
    return land or []


def table1_all(un):
    return [t for t in D.t1 if t["un"] == un]


def table3(un, sad=""):
    rows = [t for t in D.t3 if t["un"] == un]
    if sad:
        want = SAD[sad]
        pick_ = [t for t in rows if t["sad"].startswith(want.split(" или ")[0])]
        return pick_ or rows
    return rows


def km(v):
    return f"{v.replace('.', ',')} km"


def zones(r, vid, kolichestvo, vreme, vyatar="", sad="", voda=False, erg_override=""):
    """The isolation / protective-action distances for the incident, as a list of text lines + facts."""
    un = r["un"]
    gs = guides_of(r, erg_override)
    lines, facts = [], {}
    spill = vid in ("tech", "tech-pozhar")
    fire = vid in ("pozhar", "tech-pozhar")

    def mx(key):
        vals = [g[key] for g in gs if g.get(key)]
        return max(vals) if vals else None

    one = gs[0] if len(gs) == 1 else None
    ev = evac(one) if one else {}
    threat = vid == "zaplaha"
    imm = mx("izolirane_m") if gs else None
    if imm:
        facts["izolirane_m"] = imm
        verbatim = ev.get("Immediate precautionary measure", [])
        if verbatim and (spill or "за течности" in verbatim[0]):
            lines += ["Незабавно: " + lower1(x) for x in verbatim]
        else:
            lines.append(f"Незабавно изолирайте (отцепете) района на най-малко {imm} m във всички посоки.")

    # fire first: it is the larger radius
    if fire or threat:
        f_m = mx("pozhar_m")
        if f_m:
            facts["pozhar_m"] = f_m
        if one and ev.get("Fire"):
            lines += [("Ако се запали: " if threat else "При пожар: ") + lower1(x) for x in ev["Fire"]]
        elif f_m:
            lines.append(f"{'Ако се запали' if threat else 'При пожар'}: когато е обхваната цистерна, вагон или ремарке с товара, "
                         f"изолирайте {f_m} m във всички посоки и обмислете евакуация в същия радиус.")

    t1 = table1(un, voda) if spill or threat else []
    pre = "Ако има теч – " if threat else ""
    if not t1 and not voda and (spill or threat) and any(t["uslovie"] == "voda" for t in table1_all(un)):
        lines.append("Веществото отделя токсичен газ само при контакт с вода – ако разливът е попаднал във вода "
                     "(река, канал, дъжд, гасене с вода), задайте --voda за зоните от Таблица 1.")
    if t1:
        big = kolichestvo == "golyamo"
        when = "ден" if vreme == "den" else "нощ"
        key = "den" if vreme == "den" else "nosht"
        size = "голям разлив" if big else "малък разлив"
        if not pre:
            size = size.capitalize()
        for t in t1:
            label = f" ({USLOVIE[t['uslovie']]})" if t["uslovie"] else ""
            rows3 = table3(un, sad) if big and t["tablica3"] == "1" else []
            if rows3:
                for x in rows3:
                    if vyatar:
                        lines.append(f"{pre}{size}{label}, {x['sad']}: изолирайте {x['izol_m']} m във всички посоки; "
                                     f"защитете хората по посока на вятъра на {km(x[f'{key}_{vyatar}'])} ({when}, {VYATAR[vyatar]}).")
                    else:
                        d = "; ".join(f"{VYATAR[w].split(' (')[0]} – {km(x[f'{key}_{w}'])}" for w in ("slab", "umeren", "silen"))
                        lines.append(f"{pre}{size}{label}, {x['sad']}: изолирайте {x['izol_m']} m във всички посоки; "
                                     f"защитете по посока на вятъра ({when}): {d}.")
                facts["tablica3"] = rows3
                continue
            iso = t["golyam_izol_m"] if big else t["malak_izol_m"]
            dist = t[("golyam" if big else "malak") + f"_{key}_km"]
            if not iso:
                iso, dist = t["malak_izol_m"], t[f"malak_{key}_km"]
            lines.append(f"{pre}{size}{label}: изолирайте {iso} m във всички посоки; "
                         f"защитете хората по посока на вятъра на {km(dist)} ({when}).")
            facts.setdefault("tablica1", []).append({"uslovie": t["uslovie"], "izolirane_m": iso, "zashtita_km": dist})
        lines.append("За изолирането важи по-голямото от посочените разстояния. „Защитете“ = евакуация или оставане на "
                     "закрито (затворени врати и прозорци, спряна вентилация) в зоната по посока на вятъра. „+“ след "
                     "числото – при неблагоприятни условия разстоянието може да е по-голямо.")
    elif spill and gs:
        big_m = mx("golyam_razliv_m")
        if big_m and kolichestvo == "golyamo":
            facts["golyam_razliv_m"] = big_m
        if one:
            if kolichestvo == "golyamo":
                lines += ["Голям разлив: " + lower1(x) for x in ev.get("Large Spill", [])]
            lines += ["Разлив: " + lower1(x) for x in ev.get("Spill", []) if "Таблица 1" not in x]
        elif kolichestvo == "golyamo" and big_m:
            where = {g["golyam_razliv_posoka"] for g in gs if g.get("golyam_razliv_m") == big_m}
            where = "по посока на вятъра" if where == {"vyatar"} else "във всички посоки"
            lines.append(f"Голям разлив: обмислете първоначална евакуация на {big_m} m {where}.")
    if fire and table1_all(un):
        lines.append("След пожара остатъчното изтичане на токсичен газ се отцепва по Таблица 1 (зоните за разлив).")
    if voda or un in D.voda:
        g = D.voda.get(un)
        if g:
            facts["gazove_pri_voda"] = g
            lines.append("При контакт с вода отделя токсичен газ: " + ", ".join(GAS_BG.get(x, x) for x in g) + ".")
    return lines, facts


# ------------------------------------------------------------------ rendering
def header(r):
    out = [f"## UN {r['un']} – {r['ime']}", f"_{r['ime_en']}_", ""]
    if r["hin"]:
        out.append(f"- Оранжева табела: **{r['hin']} / {r['un']}**")
    else:
        out.append("- Оранжева табела: без числа (няма номер за опасност – не се превозва в цистерни или насипно); "
                   f"UN {r['un']} е означен върху опаковките и в товарния документ")
    if r["hin"]:
        for h in [x.strip() for x in r["hin"].split(",")]:
            out.append(f"- Номер за опасност {h}: {hin_decode(h)}")
    out.append(f"- Клас {klas_text(r)}; класификационен код {r['kod'] or '—'}"
               + (f"; опаковъчна група {r['og']}" if r["og"] else ""))
    if r["etiketi"]:
        out.append(f"- Етикети (ромбове): {r['etiketi']}")
    return out


def render_eri(card, only=None):
    out = [f"### ERI карта {card['kod']}: {card['zaglavie']}"]
    for num, title, items in card["sections"]:
        if only and num not in only:
            continue
        if not items and "." not in num:
            out.append(f"**{num}. {title}**")
            continue
        out.append(f"**{num}{'.' if '.' not in num else ''} {title}**")
        out += [f"- {b}" for b in items]
    return out


def render_erg(g, only=None):
    out = [f"### Указание {g['nomer']} (ERG 2024): {g['zaglavie']}"]
    for key, title, items in g["sections"]:
        if only and key not in only:
            continue
        out.append(f"**{title}**")
        for item in items:
            kind, text = item[0], item[1]
            if text.startswith("ОБАДЕТЕ СЕ НА 112"):
                continue                      # addressed to the caller, not to the fire service
            out.append(f"_{text}_" if kind == "sub" else (f"> {text}" if kind == "note" else f"- {text}"))
    return out


def card_text(r, erg_override=""):
    out = header(r)
    card = eri_card(r["eri"]) if r["eri"] else None
    gs = guides_of(r, erg_override)
    out.append("")
    if card:
        out += render_eri(card)
    else:
        out.append("За това вещество CEFIC няма ERI карта – действията са по указанията на ERG 2024.")
        if len(gs) > 1:
            out.append("Указанията са няколко – изберете според вида на товара: "
                       + "; ".join(f"{g['nomer']} – {g['zaglavie']}" for g in gs) + ".")
        for g in gs:
            out.append("")
            out += render_erg(g)
    out.append("")
    out.append("### Разстояния (ERG 2024)")
    if gs:
        for g in gs:
            bits = [f"незабавно изолиране – {g['izolirane_m']} m" if g["izolirane_m"] else ""]
            if g["golyam_razliv_m"]:
                bits.append(f"голям разлив – евакуация {g['golyam_razliv_m']} m "
                            + ("по посока на вятъра" if g["golyam_razliv_posoka"] == "vyatar" else "във всички посоки"))
            if g["pozhar_m"]:
                bits.append(f"пожар, обхванал цистерната/товара – {g['pozhar_m']} m")
            out.append(f"- Указание {g['nomer']} ({g['zaglavie']}): " + "; ".join(b for b in bits if b) + ".")
    t1 = table1_all(r["un"])
    if t1:
        out.append("- Токсичен при вдишване – Таблица 1 (изолиране във всички посоки / защита по посока на вятъра ден / нощ):")
        for t in t1:
            label = f" {USLOVIE[t['uslovie']]}" if t["uslovie"] else ""
            small = f"малък разлив{label}: {t['malak_izol_m']} m / {km(t['malak_den_km'])} / {km(t['malak_nosht_km'])}"
            large = (f"голям разлив: {t['golyam_izol_m']} m / {km(t['golyam_den_km'])} / {km(t['golyam_nosht_km'])}"
                     if t["golyam_izol_m"] else "голям разлив: според съда и вятъра (Таблица 3, по-долу)")
            out.append(f"  - {small}; {large}")
        t3 = table3(r["un"])
        if t3:
            out.append("- Голям разлив по Таблица 3 – изолиране; защита по посока на вятъра при слаб / умерен / силен "
                       "вятър (под 10 / 10–20 / над 20 km/h):")
            for x in t3:
                out.append(f"  - {x['sad']}: {x['izol_m']} m; ден {x['den_slab']} / {x['den_umeren']} / {x['den_silen']} km; "
                           f"нощ {x['nosht_slab']} / {x['nosht_umeren']} / {x['nosht_silen']} km".replace(".", ","))
    if r["un"] in D.voda:
        out.append("- При контакт с вода отделя: " + ", ".join(GAS_BG.get(x, x) for x in D.voda[r["un"]]) + ".")
    out += ["", SOURCES, DISCLAIMER]
    return out


def incident_text(r, a):
    lines, facts = zones(r, a.vid, a.kolichestvo, a.vreme, a.vyatar or "", a.sad or "", a.voda, a.erg or "")
    card = eri_card(r["eri"]) if r["eri"] else None
    gs = guides_of(r, a.erg or "")
    spill, fire = a.vid in ("tech", "tech-pozhar"), a.vid in ("pozhar", "tech-pozhar", "zaplaha")
    out = [f"## Произшествие с UN {r['un']} – {r['ime']}", f"_{r['ime_en']}_", ""]
    cond = [VID[a.vid], "голямо количество" if a.kolichestvo == "golyamo" else "малко количество",
            "ден" if a.vreme == "den" else "нощ"]
    if a.vyatar:
        cond.append(VYATAR[a.vyatar])
    if a.sad:
        cond.append(SAD[a.sad])
    if a.voda:
        cond.append("разлив във вода")
    out.append("Обстановка: " + "; ".join(cond) + ".")
    plate = f"Табела {r['hin']}/{r['un']}" if r["hin"] else f"UN {r['un']} (без номер за опасност)"
    out.append(f"{plate}; клас {klas_text(r)}"
               + (f"; номер за опасност {r['hin']} – {hin_decode(r['hin'].split(',')[0])}" if r["hin"] else "") + ".")
    out += ["", "### 1. Зони"]
    out += [f"- {x}" for x in lines] or ["- Няма данни за разстояния – определете зоната по обстановката."]
    if card:
        sec = {num: (title, items) for num, title, items in card["sections"]}

        def block(title, nums):
            b = []
            for n in nums:
                if n in sec and sec[n][1]:
                    b += [f"- {x}" for x in sec[n][1]]
            return ([f"### {title}"] + b) if b else []
        out += [""] + block("2. Лична защита", ["3"])
        out += [""] + block("3. Общи действия", ["4.1"])
        if spill:
            out += [""] + block("4. При разлив", ["4.2"])
        if fire:
            out += [""] + block("5. При пожар" if spill else "4. При пожар", ["4.3"])
        out += [""] + block("Опасности", ["2"])
        out += [""] + block("Първа помощ", ["5"])
        out += ["", f"ERI карта {card['kod']}: {card['zaglavie']}. Пълната карта (събиране на продукта, деконтаминация): "
                    f"`adr.py karta --id {r['id']}`."]
    else:
        if len(gs) > 1:
            out += ["", "Указанията са няколко – изберете според вида на товара и подайте --erg: "
                    + "; ".join(f"{g['nomer']} – {g['zaglavie']}" for g in gs) + "."]
        for g in gs[:1] if len(gs) == 1 else gs:
            want = ["PUBLIC SAFETY", "PROTECTIVE CLOTHING"] + (["SPILL OR LEAK"] if spill or a.vid == "zaplaha" else []) \
                   + (["FIRE"] if fire else []) + ["FIRE OR EXPLOSION", "HEALTH", "FIRST AID"]
            order = {k: i for i, k in enumerate(want)}
            g2 = dict(g, sections=sorted([s for s in g["sections"] if s[0] in order], key=lambda s: order[s[0]]))
            out += [""] + render_erg(g2)
    out += ["", SOURCES, DISCLAIMER]
    return [x for i, x in enumerate(out) if not (x == "" and i and out[i - 1] == "")], facts


# ------------------------------------------------------------------ commands
def cmd_tarsi(a):
    hin, un = a.hin or "", a.un or ""
    if a.tabela:
        h2, u2 = parse_tabela(a.tabela)
        hin, un = hin or h2, un or u2
    if not (un or hin or a.ime or a.klas):
        sys.exit("Задайте --un, --tabela, --hin, --ime или --klas.")
    rows, total = search(un, hin, a.ime or "", a.klas or "", a.limit)
    note = ""
    if not rows and un and hin:
        rows, total = search(un, "", a.ime or "", a.klas or "", a.limit)
        if rows:
            note = (f"За UN {norm_un(un)} няма запис с номер за опасност {norm_hin(hin)} – проверете прочитането на табелата. "
                    f"Записите за този UN номер:")
    if a.json:
        print(json.dumps({"total": total, "note": note, "rows": rows}, ensure_ascii=False, indent=1))
    else:
        if not rows:
            print("Няма намерени записи.")
        else:
            if note:
                print(note)
            print(f"Намерени: {total}" + (f" (показани {len(rows)})" if total > len(rows) else ""))
            for r in rows:
                print(line(r))
    sys.exit(0 if rows else 2)


def others_note(r, cands):
    """A line that tells which variant was taken when the UN number has several entries."""
    rest = [c for c in cands if c["id"] != r["id"]]
    if not rest:
        return ""
    why = ("записът по подразбиране на CEFIC за случаите, когато номерът за опасност не е известен"
           if r["eri_default"] == "1" else "първият от еднаквите по действия записи")
    return (f"За UN {r['un']} има {len(cands)} записа; показан е {why}. Останалите: "
            + "; ".join(f"[{c['id']}] {c['hin'] or '—'} – {c['ime']}" for c in rest[:6])
            + (" …" if len(rest) > 6 else "") + ". Уточнете с --hin (горното число на табелата) или --id.")


def need_one(a):
    r, cands = pick(a)
    if r:
        a.note = others_note(r, cands)
        return r
    if not cands:
        print("Няма такъв запис. Проверете UN номера или потърсете по име: adr.py tarsi --ime …")
        sys.exit(2)
    print("Няколко записа – изберете с --id (или добавете --hin от табелата):")
    for c in cands:
        print(line(c))
    sys.exit(3)


def cmd_karta(a):
    r = need_one(a)
    if a.json:
        print(json.dumps({"veshtestvo": r, "hin_opisanie": {h.strip(): hin_decode(h) for h in r["hin"].split(",") if h.strip()},
                          "klas": klas_text(r), "eri": eri_card(r["eri"]) if r["eri"] else None,
                          "erg": guides_of(r, a.erg or ""), "tablica1": table1_all(r["un"]),
                          "tablica3": table3(r["un"]), "gazove_pri_voda": D.voda.get(r["un"], []),
                          "belezhka": a.note},
                         ensure_ascii=False, indent=1))
    else:
        print("\n".join(([a.note, ""] if a.note else []) + card_text(r, a.erg or "")))


def cmd_proizshestvie(a):
    r = need_one(a)
    text, facts = incident_text(r, a)
    if a.json:
        print(json.dumps({"veshtestvo": r, "obstanovka": {"vid": a.vid, "kolichestvo": a.kolichestvo, "vreme": a.vreme,
                                                           "vyatar": a.vyatar, "sad": a.sad, "voda": a.voda},
                          "zoni": facts, "belezhka": a.note, "tekst": "\n".join(text)}, ensure_ascii=False, indent=1))
    else:
        print("\n".join(([a.note, ""] if a.note else []) + text))


def cmd_hin(a):
    code = norm_hin(a.kod)
    text = hin_decode(code)
    if not text:
        print(f"„{a.kod}“ не е номер за опасност.")
        sys.exit(2)
    n = sum(1 for r in D.veshtestva if code in [h.strip() for h in r["hin"].split(",")])
    if a.json:
        print(json.dumps({"hin": code, "opisanie": text, "broy_veshtestva": n}, ensure_ascii=False))
    else:
        print(f"{code}: {text}" + (f" (в списъка: {n} вещества)" if n else ""))


def cmd_ukazanie(a):
    g = erg_guide(a.nomer)
    if not g:
        print("Няма такова указание (ERG 2024 има указания 111–174).")
        sys.exit(2)
    if a.json:
        print(json.dumps(g, ensure_ascii=False, indent=1))
    else:
        print("\n".join(render_erg(g) + ["", SOURCES]))


def add_pick(p):
    p.add_argument("--id", type=int, help="record id from 'tarsi'")
    p.add_argument("--un", help="UN number, e.g. 1203")
    p.add_argument("--hin", help="hazard identification number from the plate, e.g. 33")
    p.add_argument("--tabela", help="the orange plate as read, e.g. '33/1203'")
    p.add_argument("--erg", help="ERG guide number to use when the entry lists several (e.g. 147)")
    p.add_argument("--json", action="store_true")


def parser():
    p = argparse.ArgumentParser(description="Опасни товари – справка за спешните екипи (ADR 2025, ERICards, ERG 2024)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("tarsi", help="search")
    s.add_argument("--un"); s.add_argument("--hin"); s.add_argument("--tabela"); s.add_argument("--ime"); s.add_argument("--klas")
    s.add_argument("--limit", type=int, default=25); s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_tarsi)
    s = sub.add_parser("karta", help="full reference card")
    add_pick(s); s.set_defaults(func=cmd_karta)
    s = sub.add_parser("proizshestvie", help="incident mode")
    add_pick(s)
    s.add_argument("--vid", required=True, choices=list(VID))
    s.add_argument("--kolichestvo", required=True, choices=["malko", "golyamo"],
                   help="malko = up to ~200 l / one small package; golyamo = tank, IBC, many packages")
    s.add_argument("--vreme", required=True, choices=["den", "nosht"])
    s.add_argument("--vyatar", choices=list(VYATAR), help="only for large spills of the six Table 3 gases")
    s.add_argument("--sad", choices=list(SAD), help="container, for Table 3")
    s.add_argument("--voda", action="store_true", help="the spill has reached water")
    s.set_defaults(func=cmd_proizshestvie)
    s = sub.add_parser("hin", help="decode a hazard identification number")
    s.add_argument("--kod", required=True); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_hin)
    s = sub.add_parser("ukazanie", help="an ERG 2024 guide")
    s.add_argument("--nomer", required=True); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_ukazanie)
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
