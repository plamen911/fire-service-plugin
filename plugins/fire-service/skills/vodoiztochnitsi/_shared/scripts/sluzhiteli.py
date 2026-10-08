#!/usr/bin/env python3
"""
sluzhiteli.py — служителите на РДПБЗН – Плевен по поименното разписание
(датата е в първия ред на таблицата).

Таблицата е в n8n (`staff_url` в `_shared/incident_api.json`) и се чете с личния ключ – така
промените стигат до всички без нова инсталация. В пакета няма копие. Без ключ (колега с
конектора Fire Service) скриптът спира с `NO_KEY` – тогава служителите се търсят с
инструмента `staff`, а за изчисленията тук се подава файл: `--csv ФАЙЛ` (редовете от
`staff` с `csv: true`) или `--zapis '{…}'` (един ред от `staff` / `whoami`).

    python3 _shared/scripts/sluzhiteli.py Петров                      # по име (част от него)
    python3 _shared/scripts/sluzhiteli.py --zveno Кнежа               # цялото звено
    python3 _shared/scripts/sluzhiteli.py --zveno Кнежа --dl началник # началникът на РСПБЗН – Кнежа
    python3 _shared/scripts/sluzhiteli.py --dl "началник на дежурна смяна" --zveno Левски
    python3 _shared/scripts/sluzhiteli.py --rakovoditeli              # директор, началници на сектори, групи, служби, участъци
    python3 _shared/scripts/sluzhiteli.py --nezaeti                   # незаетите длъжности
    python3 _shared/scripts/sluzhiteli.py Бранко --spravka            # данни за справка от негово име
    python3 _shared/scripts/sluzhiteli.py --nachalnik Левски          # звание и име на началника на РСПБЗН
    python3 _shared/scripts/sluzhiteli.py --direktor                  # директорът на РДПБЗН – Плевен (за подписа)
    python3 _shared/scripts/sluzhiteli.py --katalog                   # списъците звания, длъжности, звена (JSON)
    python3 _shared/scripts/sluzhiteli.py --profil                    # моите данни за документите (по личния ключ)
    python3 _shared/scripts/sluzhiteli.py --profil --zapis '{"ime": "…", "zvanie": "…", …}'   # от реда на whoami

Търсенето не прави разлика между главни и малки букви; --zveno търси и в участъка и
подразделението („Сторгозия“, „Оперативен център“). Името може да е и галено („Бранко“,
„Гошо“, „Краси“): ако няма точно съвпадение, се търси по галените имена в NICK и накрая
по първите 4 букви; тогава редовете са с "match": "приблизително" – потвърди в чата.

--spravka дава JSON с готовите полета за справката по чл. 20, ал. 3: ime, malko_ime, uvod
(„длъжност в/при звено“ за уводния абзац), izgotvil (званието под „ИЗГОТВИЛ:“ в справката – „мл. експерт“, „инспектор IV ст.“), signer_title (длъжност с главни букви), unit (РСПБЗН) и email
(къде да се изпрати справката; празно = още не е даден).

--profil дава JSON с данните на потребителя за документите: ime, ime_palno, zvanie, dlazhnost,
zveno, spravka_uvod и spravka_izgotvil (справка по чл. 20, ал. 3), izgotvil_position и
izgotvil_short („Изготвил“ в писма, удостоверения и сметката), expert_title, expert_position,
obrazovanie и specialnost (експертиза). Образованието и специалността са по подразбиране
„Висше“ и „Пожарна и аварийна безопасност“ – ако потребителят каже други, важат неговите.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RAK = re.compile(r"^(ВПД )?(ДИРЕКТОР|НАЧАЛНИК( НА (СЕКТОР|ГРУПА|УЧАСТЪК))?)$")


def n(s):
    return re.sub(r"\s+", " ", (s or "").lower().replace("ѝ", "й")).strip()


sys.path.insert(0, HERE)
import api_config  # noqa: E402  (addresses of n8n and the personal key)

CACHE = os.path.join(tempfile.gettempdir(), "fire_service_staff.csv")
CACHE_SECONDS = 600
# A CSV to read instead of asking n8n: tests, and a colleague's rows saved from the connector tool `staff`.
STAFF_FILE = os.environ.get("FIRE_SERVICE_STAFF_CSV") or None
COLUMNS = ["zveno", "uchastak", "podrazdelenie", "nomer", "dlazhnost_po_shtat", "zaemana_dlazhnost", "zvanie",
           "ime", "ime_kratko", "status", "belezhka", "email"]


class Unavailable(Exception):
    """The staff list cannot be read: no personal key, or n8n does not answer."""


def remote_csv():
    """The current staff table from n8n. Raises Unavailable."""
    if not api_config.has_key():  # the cached copy is for the key's owner only
        raise Unavailable(api_config.NO_KEY + " – инструментът staff")
    try:
        if time.time() - os.path.getmtime(CACHE) < CACHE_SECONDS:
            with open(CACHE, encoding="utf-8") as f:
                return f.read()
    except OSError:
        pass
    try:
        text = api_config.post("staff_url", {}, timeout=15)["csv"]
        lines = text.split("\n", 2)
        if not (lines[0].startswith("#") and lines[1].startswith("zveno,")):
            raise ValueError("unexpected staff table")
    except Exception as e:  # noqa: BLE001  (network, HTTP status, shape)
        raise Unavailable(f"N8N_UNAVAILABLE: списъкът на служителите не се чете ({type(e).__name__})") from None
    try:
        api_config.write_private(CACHE, text)
    except OSError:
        pass
    return text


def load():
    """(source line, rows). Rows always carry every column of COLUMNS."""
    if STAFF_FILE:
        with open(STAFF_FILE, encoding="utf-8") as f:
            text = f.read()
    else:
        text = remote_csv()
    f = io.StringIO(text.lstrip("\ufeff"))
    first = f.readline()
    if first.startswith("#"):
        header = first.lstrip("# ").strip()
    else:  # rows saved from the connector: no comment line
        header, f = "Служители на РДПБЗН – Плевен (редове от конектора)", io.StringIO(text.lstrip("\ufeff"))
    rows = []
    for r in csv.DictReader(f):
        row = {c: (r.get(c) or "") for c in COLUMNS}
        if not row["dlazhnost_po_shtat"]:
            row["dlazhnost_po_shtat"] = row["zaemana_dlazhnost"]
        if not row["status"]:
            row["status"] = "заета" if row["ime"] else "незаета"
        rows.append(row)
    return header, rows


def row_from_view(v):
    """A row of the connector tools `staff` / `whoami` ({zveno, dlazhnost, zvanie, ime, ime_palno, …}) → a table row."""
    dl = v.get("dlazhnost") or v.get("zaemana_dlazhnost") or ""
    short = v.get("ime") or v.get("ime_kratko") or ""
    return {"zveno": v.get("zveno") or "", "uchastak": v.get("uchastak") or "", "podrazdelenie": v.get("podrazdelenie") or "",
            "nomer": "", "dlazhnost_po_shtat": dl, "zaemana_dlazhnost": dl, "zvanie": v.get("zvanie") or "",
            "ime": v.get("ime_palno") or short, "ime_kratko": short, "status": "заета", "belezhka": "",
            "email": v.get("email") or ""}


# Галено име → официално (малки букви). Само имена, които се срещат в разписанието.
NICK = {
    "бранко": ["бранимир"], "гошо": ["георги"], "жоро": ["георги"], "гого": ["георги"],
    "ники": ["николай"], "кольо": ["николай"], "колю": ["николай"], "коля": ["николай"],
    "стефчо": ["стефан"], "стефо": ["стефан"], "иво": ["ивайло", "иво", "ивелин"],
    "ивчо": ["ивайло"], "боби": ["борислав", "бойко"], "божо": ["божидар"],
    "митко": ["димитър"], "мито": ["димитър"], "димо": ["димитър"], "венци": ["венцислав"],
    "венко": ["венцислав", "венелин"], "свето": ["светослав", "светлин"], "ваньо": ["иван"],
    "ванко": ["иван"], "любо": ["любомир", "любен"], "тихо": ["тихомир"], "владо": ["владимир", "владислав"],
    "влади": ["владимир", "владислав"], "краси": ["красимир", "красимира"], "ицо": ["христо"],
    "радо": ["радослав"], "миро": ["мирослав"], "данчо": ["йордан", "даниел"], "дачо": ["йордан"],
    "тошо": ["тодор"], "цецо": ["цветан", "цветослав"], "цеци": ["цветан", "цветослав"], "пешо": ["петър", "петко"],
    "петьо": ["петър"], "вальо": ["валентин", "валери"], "сашо": ["александър"],
    "мишо": ["михаил"], "киро": ["кирил"], "коце": ["константин"], "коко": ["константин"],
    "емо": ["емил"], "кало": ["калоян"], "тольо": ["анатоли", "анатолий"], "дани": ["даниел", "даниела"],
    "ильо": ["илия", "илиян", "илиан"], "добри": ["добромир"], "лъчо": ["лъчезар"],
    "драго": ["драгомир"], "мони": ["симеон"], "весо": ["веселин"], "веско": ["веселин"],
    "стани": ["станислав"], "пацо": ["пламен"], "плами": ["пламен", "пламена"],
    "милко": ["милен"], "руми": ["румен"], "генчо": ["генади"], "чочо": ["христо"],
}

# Подразделение → както се пише в справката
PODR = {
    "ГРУПА „ОПЕРАТИВЕН ЦЕНТЪР“": "група „ОЦ”",
    "ГРУПА „ПОЖАРОГАСИТЕЛНА И СПАСИТЕЛНА ДЕЙНОСТ“": "група „ПГ и СД”",
    "ГРУПА „ДЪРЖАВЕН ПРОТИВОПОЖАРЕН КОНТРОЛ И ПРЕВАНТИВНА ДЕЙНОСТ“": "група „ДПК и ПД”",
    "ГРУПА „ПРЕВАНТИВЕН КОНТРОЛ И ПРЕВАНТИВНА ДЕЙНОСТ“": "група „ПК и ПД”",
    "СЕКТОР „ПОЖАРОГАСИТЕЛНА И СПАСИТЕЛНА ДЕЙНОСТ“": "сектор „ПГ и СД”",
    "СЕКТОР „ПРЕВАНТИВНА И КОНТРОЛНА ДЕЙНОСТ“": "сектор „ПКД”",
    "СЕКТОР „АДМИНИСТРАТИВЕН“": "сектор „Административен”",
}

ROMAN = re.compile(r"^[IVXІХ]+[,.)]?$")


def human(dl):
    out = []
    for i, w in enumerate(dl.split(" ")):
        out.append(w if ROMAN.match(w) or w == "ВПД" else w.lower())
    return " ".join(out)


def name_match(r, q, field="ime"):
    """q = списък от думи; всяка трябва да се среща в името (field)."""
    return all(t in n(r[field]) for t in q)


def nick_match(r, q):
    words = n(r["ime_kratko"]).split()
    for t in q:
        full = NICK.get(t)
        if t in n(r["ime_kratko"]):
            continue
        if not full or not any(w == f for w in words for f in full):
            return False
    return True


def prefix_match(r, q):
    words = n(r["ime_kratko"]).split()
    return all(t in n(r["ime_kratko"]) or any(w.startswith(t[:4]) for w in words) for t in q)


def short_dl(dl):
    """„ИНСПЕКТОР IV степен (ПБЗН)“ → „инспектор IV ст.“"""
    d = re.sub(r"\s*\((ПБЗН|ГДЗС|РХБЗ)\)", "", dl)
    d = re.sub(r"\s+степен", " ст.", d)
    return human(d)


def izgotvil_title(zvanie, dl):
    """The line under „ИЗГОТВИЛ:“ – the rank, abbreviated: „Младши експерт“ → „мл. експерт“.
    When the position is the rank plus a degree („ИНСПЕКТОР IV степен“, rank „Инспектор“) the
    degree stays: „инспектор IV ст.“. Without a usable rank – the short position."""
    z = (zvanie or "").strip()
    d = short_dl(dl)
    if not z or "/" in z or "ниво" in z.lower():
        return d
    low = z[0].lower() + z[1:]
    for full, abbr in (("младши ", "мл. "), ("старши ", "ст. "), ("главен ", "гл. ")):
        if low.startswith(full):
            low = abbr + low[len(full):]
    if d.lower().startswith(z.lower() + " ") and d.endswith(" ст."):
        return low + d[len(z):]
    return low


def direktor():
    """{"label", "rank", "name"} of the director of РДПБЗН – Плевен for the signature block, or None
    (also when the staff list cannot be read – then the caller must be given the director)."""
    try:
        _, rows = load()
    except Unavailable:
        return None
    for r in rows:
        dl = (r["zaemana_dlazhnost"] or r["dlazhnost_po_shtat"]).strip().upper()
        if r["status"] == "заета" and r["ime_kratko"] and dl in ("ДИРЕКТОР", "ВПД ДИРЕКТОР"):
            return {"label": dl + ":", "rank": r["zvanie"].upper(), "name": r["ime_kratko"]}
    return None


def spravka_fields(r):
    dl = r["zaemana_dlazhnost"] or r["dlazhnost_po_shtat"]
    d = short_dl(dl)
    grupa = PODR.get(r["podrazdelenie"], r["podrazdelenie"])
    zv, uch = r["zveno"], r["uchastak"]
    base = n(dl)
    vpd = "ВПД " if dl.startswith("ВПД ") else ""
    head = base[4:] if vpd else base  # "впд началник" → "началник"
    if head in ("директор", "началник"):
        uvod = f"{vpd}{head} на {zv}"
    elif base.endswith("началник на група") or base.endswith("началник на сектор"):
        uvod = f"началник на {grupa} при {zv}"
    elif base.endswith("началник на участък"):
        uvod = f"{'ВПД ' if dl.startswith('ВПД') else ''}началник на {uch} при {zv}"
    elif uch:
        uvod = f"{d} в {uch} при {zv}"
    elif grupa:
        uvod = f"{d} в {grupa} при {zv}"
    else:
        uvod = f"{d} в {zv}"
    def up(g):  # „група „ПГ и СД”“ → „ГРУПА „ПГ и СД”“ – съкращението остава
        k, _, rest = g.partition(" ")
        return k.upper() + " " + rest
    title = re.sub(r"\s*\((ПБЗН|ГДЗС|РХБЗ)\)", "", dl)
    title = re.sub(r"\s+[IVXІ\-– ]+\s*степен.*$", "", title).upper()
    if (base.endswith("началник на група") or base.endswith("началник на сектор")) and grupa:
        title = ("ВПД " if dl.startswith("ВПД") else "") + "НАЧАЛНИК НА " + up(grupa)
    elif base.endswith("началник на участък") and uch:
        title = ("ВПД " if dl.startswith("ВПД") else "") + "НАЧАЛНИК НА " + uch
    elif head == "началник":
        title = vpd + "НАЧАЛНИК НА " + zv
    elif title.startswith("ИНСПЕКТОР") and grupa:
        title += " В " + up(grupa)
    unit = zv.split("– ", 1)[1].upper() if zv.startswith("РСПБЗН") else None
    return {"ime": r["ime_kratko"], "malko_ime": r["ime_kratko"].split(" ")[0],
            "email": r.get("email", ""), "uvod": uvod, "izgotvil": izgotvil_title(r["zvanie"], dl), "signer_title": title, "unit": unit,
            "zveno": zv, "uchastak": uch, "podrazdelenie": r["podrazdelenie"], "dlazhnost": dl}


DEFAULT_OBRAZOVANIE = "Висше"
DEFAULT_SPECIALNOST = "Пожарна и аварийна безопасност"


def profil_fields(r, admin=None):
    """The user's own data for the documents, from their row in the staff list; the personal skill
    `fire-service-key` may override single fields (api_config.profile())."""
    f = spravka_fields(r)
    dl = r["zaemana_dlazhnost"] or r["dlazhnost_po_shtat"]
    d = short_dl(dl)
    zv = r["zveno"]
    grupa = PODR.get(r["podrazdelenie"], r["podrazdelenie"]).replace("„", "").replace("”", "").replace("“", "")
    rank = izgotvil_title(r["zvanie"], "")  # the rank alone, abbreviated: „мл. експерт“, „инспектор“
    where_ = " ".join(x for x in [f"в {r['uchastak']}" if r["uchastak"] else (f"в {grupa}" if grupa else ""),
                                  f"на {zv} към РДПБЗН – Плевен" if zv.startswith("РСПБЗН") else f"към {zv}"] if x)
    first, _, last = r["ime_kratko"].partition(" ")
    out = {
        "ime": r["ime_kratko"], "ime_palno": r["ime"], "zvanie": (r["zvanie"] or "").lower(), "dlazhnost": d,
        "zveno": zv, "uchastak": r["uchastak"], "podrazdelenie": r["podrazdelenie"], "email": r.get("email", ""),
        "spravka_uvod": f["uvod"], "spravka_izgotvil": f["izgotvil"],
        "izgotvil_position": f["izgotvil"], "izgotvil_short": f"{first[:1]}. {last}" if last else r["ime_kratko"],
        "expert_title": rank, "expert_position": f"{d} {where_} при ГДПБЗН – МВР",
        "obrazovanie": DEFAULT_OBRAZOVANIE, "specialnost": DEFAULT_SPECIALNOST,
    }
    if admin is not None:
        out["admin"] = bool(admin)
    own = {k: v for k, v in api_config.profile().items() if k in out and k != "admin"}
    out.update(own)
    return out


def nachalnik(unit):
    """Началникът на РСПБЗН – {unit} (напр. "ПЛЕВЕН", "Червен бряг") → {"zvanie", "ime", "vpd"}
    или None (и когато списъкът не се чете). Взема заемащия длъжността НАЧАЛНИК, иначе ВПД НАЧАЛНИК."""
    try:
        _, rows = load()
    except Unavailable:
        return None
    u = n(unit)
    rows = [r for r in rows if r["status"] == "заета" and n(r["zveno"]) == "рспбзн – " + u
            and not r["uchastak"] and not r["podrazdelenie"]]
    for want in ("НАЧАЛНИК", "ВПД НАЧАЛНИК"):
        for r in rows:
            if (r["zaemana_dlazhnost"] or r["dlazhnost_po_shtat"]) == want:
                # "post rank/ own rank" (acting head) → the person's own rank
                return {"zvanie": r["zvanie"].split("/")[-1].strip(), "ime": r["ime_kratko"],
                        "vpd": want.startswith("ВПД"),
                        "zveno": r["zveno"]}
    return None


# ── Каталог: звания, длъжности и звена за падащите менюта (уеб приложението) ──

TRANSLIT = dict(zip("абвгдежзийклмнопрстуфхцчшщъьюя",
                    ["a", "b", "v", "g", "d", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s",
                     "t", "u", "f", "h", "ts", "ch", "sh", "sht", "a", "y", "yu", "ya"]))
ROMANS = ["I", "II", "III", "IV", "V", "VI"]
RANK_LADDER = ["главен комисар", "старши комисар", "комисар", "главен инспектор", "старши инспектор",
               "инспектор", "младши инспектор", "младши експерт"]
GROUPS = ["Ръководни", "Инспекторски", "Оперативен състав", "Служители"]
OPERATIVNI = ("началник на дежурна смяна", "командир", "младши инспектор", "пожарникар", "старши пожарникар",
              "спасител", "старши спасител", "водач")
SLUZHITELI = ("главен експерт", "главен счетоводител", "системен оператор", "младши специалист", "домакин",
              "отчетник", "технически изпълнител", "работник", "чистач")
# Ред в групата; каквото го няма тук – след тях, по реда в разписанието.
POSITION_ORDER = ["директор на РДПБЗН", "началник на РСПБЗН", "началник на сектор", "началник на група",
                  "началник на участък", "инспектор", "инспектор по ЗН", "началник на дежурна смяна",
                  "командир на екип", "младши инспектор", "старши пожарникар", "пожарникар", "старши спасител",
                  "спасител", "водач на специален автомобил"]
UPPER_WORDS = {"рспбзн": "РСПБЗН", "рдпбзн": "РДПБЗН", "зн": "ЗН"}


def slug(text):
    t = "".join(TRANSLIT.get(ch, ch) for ch in text.lower())
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def latin_roman(text):
    """Кирилско „І“ в римските цифри → латинско „I“ („ІV“ → „IV“)."""
    return re.sub(r"\b[IVXІ]+\b", lambda m: m.group(0).replace("І", "I"), text)


def clean_position(raw):
    """„ИНСПЕКТОР ПО ЗН ІV степен (РХБЗ)“ → [„инспектор по ЗН IV степен“]; диапазоните се разгръщат."""
    t = latin_roman(raw)
    t = re.sub(r"\s*\([^)]*\)", "", t)          # (ПБЗН), (ГДЗС), (домакин) …
    t = re.sub(r"\s*/.*$", "", t)                 # „/ПО ЗАПЛАЩАНЕТО НА ТРУДА“
    t = re.sub(r",\s*той и пожарникар", "", t)
    t = re.sub(r"^ВПД\s+", "", t)
    t = re.sub(r"\s*-\s*0,\d+$", "", t)          # „ЧИСТАЧ - 0,5“
    t = re.sub(r",.*$", "", t)                     # „ОТЧЕТНИК, ПЛАНИРАНЕ …“, „РАБОТНИК, СТРОИТЕЛСТВО“
    t = t.strip()
    words = [UPPER_WORDS.get(w.lower(), w if w in ROMANS else w.lower()) for w in t.split()]
    t = " ".join(words)
    if t == "началник":
        return ["началник на РСПБЗН"]
    if t == "директор":
        return ["директор на РДПБЗН"]
    m = re.match(r"^(.*?)\s*([IV]+)\s*-\s*([IV]+)\s+степен$", t)
    if m:
        lo, hi = sorted([ROMANS.index(m.group(2)), ROMANS.index(m.group(3))])
        return [f"{m.group(1)} {ROMANS[i]} степен" for i in range(lo, hi + 1)]
    m = re.match(r"^(.+?)\s*-\s*(.+)$", t)
    if m and not re.search(r"\d", t):
        return [m.group(1).strip(), m.group(2).strip()]
    return [t]


def position_group(name):
    if name.startswith(("директор", "началник на РСПБЗН", "началник на сектор", "началник на група", "началник на участък")):
        return "Ръководни"
    if name.startswith(OPERATIVNI):
        return "Оперативен състав"
    if name.startswith("инспектор"):
        return "Инспекторски"
    return "Служители" if name.startswith(SLUZHITELI) else "Служители"


def short_form(name):
    s = name.replace(" степен", " ст.").replace("водач на специален автомобил", "водач СА")
    s = s.replace("началник на дежурна смяна", "началник ДС")
    return re.sub(r"^(главен|старши|младши)\s", lambda m: {"главен": "гл. ", "старши": "ст. ", "младши": "мл. "}[m.group(1)], s)


def katalog():
    """Званията, длъжностите и звената от разписанието – за падащите менюта на приложението."""
    src, rows = load()
    ranks, positions, units = [], [], []

    for r in rows:
        for part in re.split(r"\s*/\s*", r["zvanie"]):
            z = part.strip().lower()
            if z and "ниво" not in z and "ранг" not in z and z not in ranks:
                ranks.append(z)
        for raw in (r["zaemana_dlazhnost"], r["dlazhnost_po_shtat"]):
            for name in clean_position(raw) if raw else []:
                if name not in positions:
                    positions.append(name)
        for name in (r["zveno"], r["uchastak"]):
            if name and name not in [u[0] for u in units]:
                units.append((name, r["zveno"]))

    ranks.sort(key=lambda z: RANK_LADDER.index(z) if z in RANK_LADDER else len(RANK_LADDER))

    base = lambda p: re.sub(r"\s*\b[IV]+ степен$", "", p)
    first_seen = {b: i for i, b in enumerate(POSITION_ORDER)}
    for p in positions:
        first_seen.setdefault(base(p), len(first_seen))

    def pos_key(name):
        m = re.search(r"\b([IV]+) степен$", name)
        return (GROUPS.index(position_group(name)), first_seen[base(name)], ROMANS.index(m.group(1)) if m else 0)

    positions.sort(key=pos_key)

    def unit_entry(i, name, parent):
        kind, _, place = name.partition(" – ")
        letter = (parent.partition(" – ")[2] if kind == "УПБЗН" else place).upper()
        return {"key": slug(name), "name": name, "short": place, "type": kind, "order": i + 1, "letterhead": letter}

    return {
        "source": src,
        "zvaniya": [{"key": slug(z), "name": z, "short": short_form(z), "order": i + 1} for i, z in enumerate(ranks)],
        "dlazhnosti": [{"key": slug(p), "name": p, "short": short_form(p), "group": position_group(p), "order": i + 1}
                       for i, p in enumerate(positions)],
        "unit": [unit_entry(i, n, parent) for i, (n, parent) in enumerate(units)],
    }


def where(r):
    return ", ".join(x for x in (r["podrazdelenie"], r["uchastak"], r["zveno"]) if x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ime", nargs="?")
    ap.add_argument("--zveno")
    ap.add_argument("--dl", help="длъжност (част от наименованието)")
    ap.add_argument("--rakovoditeli", action="store_true")
    ap.add_argument("--nezaeti", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--spravka", action="store_true", help="JSON с полетата за справката по чл. 20, ал. 3")
    ap.add_argument("--nachalnik", metavar="СЛУЖБА", help="началникът на РСПБЗН – СЛУЖБА (звание и име), JSON")
    ap.add_argument("--direktor", action="store_true", help="директорът на РДПБЗН – Плевен (звание и име), JSON")
    ap.add_argument("--katalog", action="store_true", help="званията, длъжностите и звената (JSON) за падащите менюта")
    ap.add_argument("--profil", action="store_true", help="данните на потребителя за документите (JSON)")
    ap.add_argument("--zapis", metavar="JSON", help="с --profil или --spravka: ред от инструмента staff / whoami вместо търсене")
    ap.add_argument("--csv", metavar="ФАЙЛ", help="таблица вместо n8n (редове от инструмента staff с csv: true)")
    a = ap.parse_args()
    global STAFF_FILE
    if a.csv:
        STAFF_FILE = a.csv
    try:
        run(a)
    except Unavailable as e:
        sys.exit(str(e))


def run(a):
    if a.zapis:
        try:
            v = json.loads(a.zapis)
            v = v.get("staff") or v  # the whole answer of whoami is fine too
            row = row_from_view(v)
            if not row["ime_kratko"]:
                raise ValueError("no name")
        except (ValueError, AttributeError):
            sys.exit("BAD_INPUT: --zapis е JSON ред от инструмента staff или whoami (zveno, dlazhnost, zvanie, ime, …)")
        if a.profil:
            print(json.dumps({"profil": profil_fields(row)}, ensure_ascii=False, indent=1))
        else:
            print(json.dumps({"source": "ред от конектора", "match": "точно", "rows": [spravka_fields(row)]},
                             ensure_ascii=False, indent=1))
        return
    if a.profil:
        who = api_config.post("staff_url", {"action": "whoami"}, timeout=15) if api_config.has_key() and not STAFF_FILE else None
        if not who:
            raise Unavailable(api_config.NO_KEY + " – инструментът whoami, после --profil --zapis '{…}'")
        _, rows = load()
        mine = [r for r in rows if r["status"] == "заета" and n(r["ime_kratko"]) == n(who.get("client"))]
        if not mine:
            print(json.dumps({"profil": None, "client": who.get("client"), "admin": who.get("admin") is True,
                              "note": "ключът не е на служител от разписанието – попитай за име, звание и длъжност"},
                             ensure_ascii=False, indent=1))
            return
        print(json.dumps({"profil": profil_fields(mine[0], who.get("admin") is True)}, ensure_ascii=False, indent=1))
        return
    if a.katalog:
        print(json.dumps(katalog(), ensure_ascii=False, indent=1))
        return
    if a.direktor:
        print(json.dumps({"direktor": direktor()}, ensure_ascii=False, indent=1))
        return
    src, rows = load()
    if a.nachalnik:
        print(json.dumps({"source": src, "nachalnik": nachalnik(a.nachalnik)}, ensure_ascii=False, indent=1))
        return
    if not a.nezaeti:
        rows = [r for r in rows if r["status"] == "заета"]
    else:
        rows = [r for r in rows if r["status"] == "незаета"]
    match = "точно"
    if a.ime:
        q = n(a.ime).split()
        # първо по име и фамилия (иначе „Бранимир“ хваща и бащиното „Бранимиров“)
        found = [r for r in rows if name_match(r, q, "ime_kratko")]
        if not found:
            found = [r for r in rows if name_match(r, q)]
        if not found:
            found, match = [r for r in rows if nick_match(r, q)], "галено име"
        if not found:
            found, match = [r for r in rows if prefix_match(r, q)], "приблизително"
        rows = found
    if a.zveno:
        q = n(a.zveno)
        rows = [r for r in rows if q in n(r["zveno"]) or q in n(r["uchastak"]) or q in n(r["podrazdelenie"])]
    if a.dl:
        q = n(a.dl)
        rows = [r for r in rows if q in n(r["zaemana_dlazhnost"]) or q in n(r["dlazhnost_po_shtat"])]
        if q.startswith("началник") and "смяна" not in q:
            rows = [r for r in rows if "смяна" not in n(r["dlazhnost_po_shtat"])] or rows
    if a.rakovoditeli:
        rows = [r for r in rows if RAK.match(r["zaemana_dlazhnost"] or r["dlazhnost_po_shtat"])]
    if a.spravka:
        print(json.dumps({"source": src, "match": match if rows else "няма",
                          "rows": [spravka_fields(r) for r in rows]}, ensure_ascii=False, indent=1))
        return
    if a.json:
        print(json.dumps({"source": src, "match": match, "rows": rows}, ensure_ascii=False, indent=1))
        return
    print(f"Източник: {src}" + (f" · съвпадение: {match}" if a.ime and match != "точно" else "") + "\n")
    if not rows:
        print("NOT_FOUND: няма такъв служител/длъжност в разписанието")
        return
    for r in rows:
        dl = r["zaemana_dlazhnost"] or r["dlazhnost_po_shtat"]
        who = r["ime"] or "— незаета —"
        extra = f" ({r['belezhka']})" if r["belezhka"] else ""
        zv = f", {r['zvanie']}" if r["zvanie"] else ""
        print(f"{who} – {human(dl)}{zv}{extra} | {where(r)}")
    print(f"\n{len(rows)} записа")


if __name__ == "__main__":
    main()
