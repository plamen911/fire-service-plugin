#!/usr/bin/env python3
"""
grafik.py — месечните графици за дежурства на РДПБЗН – Плевен: идемпотентен импорт на
разчетен график, връзване на имената с поименното разписание и справки – кой е дежурен на
дата, кога е дежурен даден служител, колко празнични дни и часове има в месеца.

Данните са в Google Drive (папка „fire-service/Графици за дежурства“), по един файл на
график и месец: `<график>_<ГГГГ-ММ>.json`. Четат се и се записват през n8n (`duty_url` в
`_shared/incident_api.json`; личният ключ идва от `api_config.py`; записва всеки активен ключ).
Видовете графици и кодовете им са в `_shared/grafici/grafici.json`.

    python3 _shared/scripts/grafik.py import READING.json              # записва/обновява месеца
    python3 _shared/scripts/grafik.py import READING.json --dry-run    # само проверява и показва разликата
    python3 _shared/scripts/grafik.py import READING.json --replace    # преписът е целият график: маха липсващите
    python3 _shared/scripts/grafik.py mesec oc 2026-10                 # решетката на месеца (за сверка със снимката)
    python3 _shared/scripts/grafik.py na-data 2026-10-04               # кои са дежурни (застъпили в 08:00 ч.)
    python3 _shared/scripts/grafik.py na-data 2026-10-04 --chas 03:30  # кой е на смяна в този час
    python3 _shared/scripts/grafik.py na-data 2026-10-04 --vsichki     # и отпуски, командировки, болнични
    python3 _shared/scripts/grafik.py sluzhitel --az --mesec 2026-10   # „кога съм дежурен“
    python3 _shared/scripts/grafik.py sluzhitel "Петров" --mesec 2026-10
    python3 _shared/scripts/grafik.py praznichni --az --mesec 2026-12  # празнични дни и часове в месеца
    python3 _shared/scripts/grafik.py praznitsi 2026                   # официалните празници
    python3 _shared/scripts/grafik.py spisak                           # кои графици и месеци има
    python3 _shared/scripts/grafik.py proverka                         # записаните файлове са в каноничен вид

`--store ПАПКА` (преди командата) работи с локална папка `<ПАПКА>/<график>/<ГГГГ-ММ>.json`
вместо с n8n – за тестове и за режим „конектор“. `--az` е служителят, чийто е личният ключ
(n8n го казва); без n8n – променливата FIRE_SERVICE_AZ.

Дежурството е 24 часа, от 08:00 ч. на деня от графика до 08:00 ч. на следващия ден.
Празничните часове се броят по календарни дни: смяната, застъпила в деня преди празника,
има 8 ч. (00:00 – 08:00), а застъпилата на празника – 16 ч. (08:00 – 24:00). В месеца влизат
само часовете от неговите дати.

Идемпотентност: ключът е (график, месец, служител). Един и същ препис, импортиран колкото и
пъти да е, дава един и същ файл до байт – без дата на запис, с подреден ред и подредени
ключове. Всички команди отговарят с JSON, освен `mesec` (таблица).
"""
import argparse
import calendar
import datetime
import difflib
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.dirname(HERE)
REGISTRY = os.path.join(SHARED, "grafici", "grafici.json")

sys.path.insert(0, HERE)
import api_config  # noqa: E402  (addresses of n8n and the personal key)
import sluzhiteli  # noqa: E402  (the roster – from n8n, or from --roster FILE)

ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
FUZZY_MIN = 0.88     # similarity of the full names for an approximate match
FUZZY_MARGIN = 0.04  # the best candidate must lead the second one by this much
SHIFT_START = 8      # a shift of day D runs from D 08:00


class Problem(Exception):
    """Something the user has to fix or know; the message is shown as is."""


def norm(text):
    return re.sub(r"\s+", " ", str(text or "").lower().replace("ѝ", "й").replace("ё", "е")).strip()


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def fail(message):
    out({"ok": False, "error": message})
    return 2


def dump(doc):
    """The one canonical serialisation of a month file (stable bytes for the same content)."""
    text = json.dumps(doc, ensure_ascii=False, indent=1)
    # the day lists on one line each: [3, 7, 11] – short files and readable diffs
    text = re.sub(r"\[\s+(\d[\d,\s]*?)\s+\]", lambda m: "[" + ", ".join(re.split(r"[,\s]+", m.group(1))) + "]", text)
    return text + "\n"


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def last_day_of(month):
    y, mo = (int(x) for x in month.split("-"))
    return calendar.monthrange(y, mo)[1]


def previous_month(month):
    y, mo = (int(x) for x in month.split("-"))
    return f"{y - 1}-12" if mo == 1 else f"{y}-{mo - 1:02d}"


# ── schedule kinds and their codes ───────────────────────────────────────────

def registry():
    with open(REGISTRY, encoding="utf-8") as f:
        return json.load(f)


def canonical_code(raw, kind, who):
    codes = kind["kodove"]
    text = str(raw).strip()
    if text in codes:
        return text
    alias = kind.get("psevdonimi", {}).get(text)
    if alias:
        return alias
    raise Problem(f"{who}: непознат код „{raw}“. Кодовете на този график са: {', '.join(codes)}")


def canonical_text(text):
    """A month file as it comes back from n8n → its canonical text. n8n hands the file over as
    re-serialised JSON: compact, and with number-like keys ("8") moved to the front of "dni", so the
    bytes are not the stored ones. The content is the same; put it back in the canonical form."""
    doc = json.loads(text)
    codes = list(registry().get(doc.get("grafik"), {}).get("kodove", {}))
    rank = {c: i for i, c in enumerate(codes)}
    for row in doc.get("sluzhiteli", []):
        if isinstance(row.get("dni"), dict):
            row["dni"] = dict(sorted(row["dni"].items(), key=lambda kv: rank.get(kv[0], len(rank))))
    return dump(doc)


# ── where the months are kept ────────────────────────────────────────────────

class LocalStore:
    """<dir>/<grafik>/<YYYY-MM>.json – tests, connector mode, offline work."""
    name = "local"

    def __init__(self, path):
        self.path = path

    def _file(self, grafik, month):
        return os.path.join(self.path, grafik, month + ".json")

    def months(self):
        found = []
        if not os.path.isdir(self.path):
            return found
        for grafik in sorted(os.listdir(self.path)):
            d = os.path.join(self.path, grafik)
            if not os.path.isdir(d) or not ID_RE.match(grafik):
                continue
            for name in sorted(os.listdir(d)):
                if name.endswith(".json") and MONTH_RE.match(name[:-5]):
                    found.append((grafik, name[:-5]))
        return found

    def get(self, grafik, month):
        path = self._file(grafik, month)
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()

    def put(self, grafik, month, text):
        path = self._file(grafik, month)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def where(self, grafik, month):
        return self._file(grafik, month)

    def whoami(self):
        return os.environ.get("FIRE_SERVICE_AZ") or None


class RemoteStore:
    """Google Drive through n8n (POST duty_url). One file per schedule kind and month."""
    name = "n8n"

    def __init__(self):
        if os.environ.get("FIRE_SERVICE_OFFLINE"):
            raise Problem("N8N_UNAVAILABLE: без мрежа графиците не са достъпни (или дай --store ПАПКА)")
        try:
            self.cfg = api_config.load()
        except (OSError, ValueError) as e:
            raise Problem(f"N8N_UNAVAILABLE: incident_api.json не се чете ({e})") from None
        if not self.cfg["key"]:
            raise Problem(api_config.NO_KEY + " – инструментите duty и duty_save, после --store ПАПКА")
        if not self.cfg.get("duty_url"):
            raise Problem("N8N_UNAVAILABLE: в incident_api.json няма duty_url")

    def _call(self, body):
        try:
            return api_config.post("duty_url", body, timeout=30)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="ignore")[:300]
            if e.code == 404 and "NOT_FOUND" in detail:
                return None
            if e.code == 404:
                raise Problem("N8N_UNAVAILABLE: n8n не познава адреса за графиците (fire-duty) – "
                              "workflow-ът „Fire Service API (skills)“ не е обновен") from None
            raise Problem(f"N8N_ERROR: HTTP {e.code} {detail}") from None
        except (OSError, ValueError) as e:
            raise Problem(f"N8N_UNAVAILABLE: {type(e).__name__}: {e}"[:300]) from None

    def months(self):
        res = self._call({"action": "list"}) or {}
        return sorted((f["grafik"], f["mesec"]) for f in res.get("files", []))

    def get(self, grafik, month):
        res = self._call({"action": "get", "grafik": grafik, "mesec": month})
        return canonical_text(res["text"]) if res else None

    def put(self, grafik, month, text):
        res = self._call({"action": "put", "grafik": grafik, "mesec": month, "text": text})
        return (res or {}).get("link") or self.where(grafik, month)

    def where(self, grafik, month):
        return f"Google Drive: fire-service/Графици за дежурства/{grafik}_{month}.json"

    def whoami(self):
        return (self._call({"action": "whoami"}) or {}).get("client")


def load_month(store, grafik, month):
    text = store.get(grafik, month)
    return json.loads(text) if text else None


# ── roster matching ──────────────────────────────────────────────────────────

def roster(store=None):
    """The staff list. Without it (a colleague with the connector and no --roster file) a question
    about duties still works: the people are then the names written in the stored schedules.
    An import needs the real list – pass store=None to insist on it."""
    try:
        _, rows = sluzhiteli.load()
        return [r for r in rows if r["status"] == "заета" and r["ime"]]
    except sluzhiteli.Unavailable as e:
        if store is None:
            raise Problem(f"{e}. За запис на график трябва поименното разписание: инструментът staff с "
                          f"csv: true за звеното → файл → grafik.py --roster ФАЙЛ …") from None
    seen, rows = set(), []
    for grafik, month in store.months():
        for row in (load_month(store, grafik, month) or {}).get("sluzhiteli", []):
            key = norm(row["ime"])
            if key in seen:
                continue
            seen.add(key)
            parts = row["ime"].split()
            rows.append({"ime": row["ime"], "ime_kratko": " ".join([parts[0], parts[-1]]) if len(parts) > 1 else row["ime"],
                         "zveno": "", "uchastak": "", "podrazdelenie": "", "zaemana_dlazhnost": "",
                         "dlazhnost_po_shtat": "", "zvanie": "", "status": "заета", "ot_grafika": True})
    return rows


def in_unit(row, kind):
    """Does the roster row belong to the unit this schedule kind is for?"""
    zveno, podr = norm(kind.get("zveno")), norm(kind.get("podrazdelenie"))
    if zveno and norm(row["zveno"]) != zveno:
        return False
    return not podr or podr in norm(row["podrazdelenie"])


def match_name(name, rows, kind):
    """Schedule name → (roster row or None, how, candidates).
    how: "точно" | "име и фамилия" | "приблизително" | "няколко" | "няма"."""
    q = norm(name)

    def narrow(found):
        if len(found) > 1:  # namesakes: the one from the schedule's own unit
            own = [r for r in found if in_unit(r, kind)]
            if len(own) == 1:
                return own
        return found

    found = narrow([r for r in rows if norm(r["ime"]) == q])
    how = "точно"
    if not found:
        found, how = narrow([r for r in rows if norm(r["ime_kratko"]) == q]), "име и фамилия"
    if len(found) == 1:
        return found[0], how, []
    if len(found) > 1:
        return None, "няколко", [r["ime"] for r in found]
    # approximate: a misread or differently spelled letter ("Мариян"/"Мариан", "Альошев"/"Алъошев")
    scored = sorted(((difflib.SequenceMatcher(None, q, norm(r["ime"])).ratio(), r["ime"], r) for r in rows),
                    key=lambda t: (-t[0], t[1]))
    best = [t for t in scored if t[0] >= FUZZY_MIN]
    if best and (len(scored) == 1 or best[0][0] - scored[1][0] >= FUZZY_MARGIN):
        return best[0][2], "приблизително", []
    return None, "няма", [t[1] for t in scored[:3] if t[0] >= 0.75]


def find_person(query, rows):
    """A person asked about in chat ("Петров", "Иван Петров") → roster rows that match."""
    q = norm(query).split()
    found = [r for r in rows if all(w in norm(r["ime_kratko"]) for w in q)]
    return found or [r for r in rows if all(w in norm(r["ime"]) for w in q)]


# ── reading → canonical rows ─────────────────────────────────────────────────

def parse_days(value, last_day, who, code):
    """[3, 7] or "5-9, 12" → sorted unique list of day numbers."""
    days = set()
    if isinstance(value, (list, tuple)):
        parts = value
    elif isinstance(value, (int, str)):
        parts = [p for p in re.split(r"[,;\s]+", str(value)) if p]
    else:
        raise Problem(f"{who}: дните за „{code}“ трябва да са списък или текст като „5-9, 12“")
    for p in parts:
        m = re.match(r"^(\d{1,2})\s*[-–]\s*(\d{1,2})$", str(p).strip())
        try:
            lo, hi = (int(m.group(1)), int(m.group(2))) if m else (int(p), int(p))
        except (TypeError, ValueError):
            raise Problem(f"{who}: „{p}“ не е ден или диапазон от дни (код „{code}“)") from None
        if lo > hi or lo < 1 or hi > last_day:
            raise Problem(f"{who}: ден „{p}“ е извън месеца (1 – {last_day}), код „{code}“")
        days.update(range(lo, hi + 1))
    return sorted(days)


def canonical_rows(reading, rows, kind, last_day):
    """The rows of a reading as stored rows + the notes about them."""
    codes = kind["kodove"]
    lines = reading.get("redove")
    if not isinstance(lines, list) or not lines:
        raise Problem("В преписа няма редове („redove“)")
    start = reading.get("ot_red", 1)
    if not isinstance(start, int) or start < 1:
        raise Problem("„ot_red“ трябва да е цяло число ≥ 1")
    numbered = [isinstance(r, dict) and r.get("nomer") is not None for r in lines]
    if any(numbered) and not all(numbered):
        raise Problem("Или всички редове имат „nomer“, или нито един (тогава редът е позицията в преписа)")
    result, notes = [], {"unmatched": [], "approx": [], "check": [], "warnings": [], "other_unit": []}
    seen_keys, seen_numbers = {}, {}
    full_shift = [c for c, d in codes.items() if d.get("dezhurstvo") and d.get("chasove") == 24]
    for i, line in enumerate(lines):
        if not isinstance(line, dict) or not str(line.get("ime", "")).strip():
            raise Problem(f"Ред {i + 1}: липсва име („ime“)")
        written = re.sub(r"\s+", " ", str(line["ime"])).strip()
        who = f"„{written}“"
        number = line["nomer"] if numbered[i] else start + i
        if not isinstance(number, int) or number < 1:
            raise Problem(f"{who}: „nomer“ трябва да е цяло число ≥ 1")
        if number in seen_numbers:
            raise Problem(f"{who}: № {number} вече е даден на „{seen_numbers[number]}“")
        seen_numbers[number] = written

        raw_days = line.get("dni") or {}
        if not isinstance(raw_days, dict):
            raise Problem(f"{who}: „dni“ трябва да е обект код → дни")
        by_code, taken = {}, {}
        for raw, value in raw_days.items():
            code = canonical_code(raw, kind, who)
            for day in parse_days(value, last_day, who, code):
                if taken.get(day, code) != code:
                    raise Problem(f"{who}: ден {day} е и „{taken[day]}“, и „{code}“")
                taken[day] = code
                by_code.setdefault(code, set()).add(day)
        for code, days in by_code.items():
            if codes[code].get("samo_posleden_den") and any(d != last_day for d in days):
                raise Problem(f"{who}: „{code}“ може да е само в последния ден на месеца ({last_day})")

        person, how, candidates = match_name(written, rows, kind)
        row = {"ime": person["ime"] if person else written, "v_razpisanieto": bool(person), "nomer": number}
        if person and norm(person["ime"]) != norm(written):
            row["kakto_e_v_grafika"] = written
        shift = str(line.get("smyana") or "").strip()
        if shift:
            row["smyana"] = shift
        row["dni"] = {c: sorted(by_code[c]) for c in codes if by_code.get(c)}
        key = norm(row["ime"])
        if key in seen_keys:
            raise Problem(f"{who}: същият служител е и на ред „{seen_keys[key]}“")
        seen_keys[key] = written
        result.append(row)

        if not person:
            notes["unmatched"].append({"ime": written, "nomer": number, "prichina": how, "podobni": candidates})
        elif how == "приблизително":
            notes["approx"].append({"v_grafika": written, "v_razpisanieto": person["ime"]})
        if person and not in_unit(person, kind):  # the schedule wins: the person is temporarily moved here
            notes["other_unit"].append({"ime": person["ime"], "nomer": number, "po_razpisanie_e_v": sluzhiteli.where(person)})
        duty = sorted(d for c in full_shift for d in row["dni"].get(c, []))
        for a, b in zip(duty, duty[1:]):
            if b - a == 1:
                notes["warnings"].append(f"{row['ime']}: 24-часово дежурство в два поредни дни ({a} и {b})")
        if len(duty) >= 3:  # a 24-hour shift repeats every 4th day; the odd ones are where misreads hide
            residues = [d % 4 for d in duty]
            usual = max(sorted(set(residues)), key=residues.count)
            odd = [d for d in duty if d % 4 != usual]
            if odd and len(odd) < len(duty) / 2:
                notes["check"].append({"ime": row["ime"], "nomer": number, "dni_izvan_tsikala": odd})
    return result, notes


def order(rows):
    return sorted(rows, key=lambda r: (r["nomer"], norm(r["ime"])))


def cmd_import(a, store):
    try:
        with open(a.reading, encoding="utf-8") as f:
            reading = json.load(f)
    except (OSError, ValueError) as e:
        raise Problem(f"Преписът не се чете: {e}") from None
    grafik = str(reading.get("grafik", "")).strip()
    month = str(reading.get("mesec", "")).strip()
    if not ID_RE.match(grafik):
        raise Problem("„grafik“ е кратко име с латински букви, цифри и тирета (напр. oc, rspbzn-pleven)")
    if not MONTH_RE.match(month):
        raise Problem("„mesec“ е във вида ГГГГ-ММ (напр. 2026-10)")
    kinds = registry()
    kind = kinds.get(grafik)
    if kind is None:
        raise Problem(f"Непознат график „{grafik}“. Познатите са в grafici.json: {', '.join(sorted(kinds))}. "
                      f"Нов вид се добавя там.")
    new_rows, notes = canonical_rows(reading, roster(), kind, last_day_of(month))

    current = store.get(grafik, month)
    old = json.loads(current) if current else None
    old_rows = (old or {}).get("sluzhiteli", [])
    incoming = {norm(r["ime"]): r for r in new_rows}
    numbers = {r["nomer"] for r in new_rows}
    kept, removed = [], []
    for r in old_rows:
        if norm(r["ime"]) in incoming:
            continue
        # same row number, another name = the earlier reading of that row was wrong
        if a.replace or r["nomer"] in numbers:
            removed.append(r["ime"])
        else:
            kept.append(r)
    before = {norm(r["ime"]): r for r in old_rows}
    added = [r["ime"] for r in new_rows if norm(r["ime"]) not in before]
    updated = [r["ime"] for r in new_rows if norm(r["ime"]) in before and before[norm(r["ime"])] != r]

    doc = {"grafik": grafik, "mesec": month}
    for field in ("zaglavie", "reg_nomer"):
        value = str(reading.get(field) or (old or {}).get(field) or "").strip()
        if value:
            doc[field] = value
    doc["sluzhiteli"] = order(kept + new_rows)
    text = dump(doc)
    changed = text != current
    where = store.where(grafik, month)
    if changed and not a.dry_run:
        where = store.put(grafik, month, text)
    out({
        "ok": True, "grafik": grafik, "mesec": month, "store": store.name, "file": where,
        "changed": changed, "written": changed and not a.dry_run, "sha256": sha(text),
        "redove_v_prepisa": len(new_rows), "redove_v_mesetsa": len(doc["sluzhiteli"]),
        "added": added, "updated": updated, "removed": removed,
        "unchanged": len(new_rows) - len(added) - len(updated),
        "unmatched": notes["unmatched"], "approx": notes["approx"],
        "vremenno_premesteni": notes["other_unit"], "za_proverka": notes["check"], "warnings": notes["warnings"],
    })
    return 0


# ── official holidays ────────────────────────────────────────────────────────

FIXED = [(1, 1, "Нова година"), (3, 3, "Ден на Освобождението на България"), (5, 1, "Ден на труда"),
         (5, 6, "Гергьовден, Ден на храбростта и Българската армия"),
         (5, 24, "Ден на светите братя Кирил и Методий, на българската азбука, просвета и култура"),
         (9, 6, "Ден на Съединението"), (9, 22, "Ден на Независимостта на България"),
         (12, 24, "Бъдни вечер"), (12, 25, "Рождество Христово"), (12, 26, "Рождество Христово")]
EASTER = [(-2, "Велики петък"), (-1, "Велика събота"), (0, "Великден"), (1, "Великден (понеделник)")]


def orthodox_easter(year):
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month, day = (d + e + 114) // 31, (d + e + 114) % 31 + 1
    return datetime.date(year, month, day) + datetime.timedelta(days=13)  # Julian → Gregorian (1900 – 2099)


def holidays(year, moved=False):
    """{date: name} – the official holidays (чл. 154, ал. 1 КТ). They are the holiday days of the
    duty questions. With `moved` also the days off given for a holiday that falls on Saturday or
    Sunday (ал. 2) – those are NOT holiday days here and are listed only on request."""
    days = {datetime.date(year, m, d): name for m, d, name in FIXED}
    easter = orthodox_easter(year)
    paschal = {easter + datetime.timedelta(days=off): name for off, name in EASTER}
    result = dict(days)
    result.update(paschal)
    if moved:
        extra = {}
        for day in sorted(days):
            if day.weekday() < 5:
                continue
            nxt = day + datetime.timedelta(days=1)
            while nxt.weekday() >= 5 or nxt in result or nxt in extra:
                nxt += datetime.timedelta(days=1)
            extra[nxt] = f"почивен ден за {day.day:02d}.{day.month:02d}. ({days[day]})"
        result.update(extra)
    return dict(sorted(result.items()))


def cmd_praznitsi(a, store):
    out({"ok": True, "godina": a.godina, "s_premestenite_pochivni_dni": a.s_premesteni,
         "praznitsi": [{"data": d.isoformat(), "den": DAYS[d.weekday()], "ime": name}
                       for d, name in holidays(a.godina, a.s_premesteni).items()]})
    return 0


DAYS = ["понеделник", "вторник", "сряда", "четвъртък", "петък", "събота", "неделя"]


# ── duties as time intervals ─────────────────────────────────────────────────

def shifts_of(row, kind, month):
    """The worked intervals of one stored row: [{start, end (datetime), kod, …}], sorted."""
    y, mo = (int(x) for x in month.split("-"))
    items = []
    for code, days in row["dni"].items():
        spec = kind["kodove"].get(code, {})
        if "chasove" not in spec:
            continue
        for day in days:
            start = datetime.datetime(y, mo, day, spec.get("ot", SHIFT_START))
            items.append({"start": start, "end": start + datetime.timedelta(hours=spec["chasove"]), "kod": code,
                          "dezhurstvo": bool(spec.get("dezhurstvo")), "myasto": spec.get("myasto")})
    return sorted(items, key=lambda s: s["start"])


def fmt(moment):
    return moment.strftime("%Y-%m-%d %H:%M")


def person_info(name, by_name, kind=None, place=None):
    """Position and rank from the roster; the unit from the schedule. The schedule wins over the
    roster: someone listed in the schedule of another unit is temporarily moved there, so `zveno` is
    the place of the duty (when the code says it) or the unit of the schedule, and the roster's unit
    is given only when it differs (`po_razpisanie_e_v`)."""
    r = by_name.get(norm(name))
    if not r:
        return {"zveno": place or kind["zveno"]} if kind else {}
    if r.get("ot_grafika"):  # no staff list at hand: only what the schedule itself says
        return {"ime_kratko": r["ime_kratko"], **({"zveno": place or kind["zveno"]} if kind else {})}
    info = {"ime_kratko": r["ime_kratko"], "dlazhnost": r["zaemana_dlazhnost"] or r["dlazhnost_po_shtat"],
            "zvanie": r["zvanie"]}
    if kind is None:
        info["zveno"] = r["uchastak"] or r["zveno"]
        if r.get("podrazdelenie"):
            info["podrazdelenie"] = r["podrazdelenie"]
        return info
    if in_unit(r, kind):
        info["zveno"] = place or r["uchastak"] or r["zveno"]
        if r.get("podrazdelenie") and not place:
            info["podrazdelenie"] = r["podrazdelenie"]
    else:
        info["zveno"] = place or kind["zveno"]
        info["vremenno_premesten"] = True
        info["po_razpisanie_e_v"] = sluzhiteli.where(r)
    return info


def code_on(row, day):
    for code, days in row["dni"].items():
        if day in days:
            return code
    return None


def resolve_person(a, store, rows):
    """The roster row asked about: a name, or --az = the owner of the personal key."""
    query = a.ime
    if a.az:
        query = store.whoami()
        if not query:
            raise Problem("Не знам кой си: n8n не каза чий е ключът. Дай името: grafik.py … \"Име Фамилия\"")
    if not query:
        raise Problem("Дай име на служител или --az")
    found = find_person(query, rows)
    if not found:
        raise Problem(f"„{query}“ го няма в поименното разписание"
                      + (" и в записаните графици" if rows and rows[0].get("ot_grafika") else ""))
    if len(found) > 1:
        raise Problem("Няколко служители отговарят на „" + query + "“: "
                      + "; ".join(r["ime"] + (f" ({r['uchastak'] or r['zveno']})" if r["zveno"] else "") for r in found[:8])
                      + ". Дай име и фамилия.")
    return found[0]


def person_months(store, person, month):
    """[(grafik, kind, doc_month, row)] of the person in `month` and in the month before it
    (the last shift of a month ends at 08:00 on the 1st of the next one)."""
    kinds, key, found, missing_prev = registry(), norm(person["ime"]), [], []
    for grafik, kind in sorted(kinds.items()):
        for m in (previous_month(month), month):
            doc = load_month(store, grafik, m)
            if doc is None:
                if m != month:
                    missing_prev.append(grafik)
                continue
            for row in doc["sluzhiteli"]:
                if norm(row["ime"]) == key:
                    found.append((grafik, kind, m, row))
    return found, missing_prev


def cmd_sluzhitel(a, store):
    rows = roster(store)
    person = resolve_person(a, store, rows)
    month = a.mesec or datetime.date.today().strftime("%Y-%m")
    if not MONTH_RE.match(month):
        raise Problem("„--mesec“ е във вида ГГГГ-ММ")
    found, _ = person_months(store, person, month)
    current = [f for f in found if f[2] == month]
    result = []
    for grafik, kind, _, row in current:
        duties, other = [], {}
        for s in shifts_of(row, kind, month):
            duties.append({"data": s["start"].strftime("%Y-%m-%d"), "den": DAYS[s["start"].weekday()],
                           "kod": s["kod"], "ot": fmt(s["start"]), "do": fmt(s["end"]),
                           "chasove": int((s["end"] - s["start"]).total_seconds() // 3600),
                           **({"myasto": s["myasto"]} if s["myasto"] else {})})
        for code, days in row["dni"].items():
            if "chasove" not in kind["kodove"].get(code, {}):
                other[code] = {"znachenie": kind["kodove"].get(code, {}).get("znachenie", ""), "dni": days}
        result.append({"grafik": grafik, "ime_na_grafika": kind["ime"],
                       **({"smyana": row["smyana"]} if row.get("smyana") else {}),
                       "dezhurstva": duties, "broi_dezhurstva": len(duties),
                       "chasove_obshto": sum(d["chasove"] for d in duties), "drugi": other})
    info = person_info(person["ime"], {norm(person["ime"]): person}, current[0][1] if current else None)
    out({"ok": True, "sluzhitel": person["ime_kratko"], "mesec": month, **info,
         "grafici": result,
         **({} if result else {"belezhka": f"Няма го в записан график за {month}"})})
    return 0


def cmd_praznichni(a, store):
    rows = roster(store)
    person = resolve_person(a, store, rows)
    month = a.mesec or datetime.date.today().strftime("%Y-%m")
    if not MONTH_RE.match(month):
        raise Problem("„--mesec“ е във вида ГГГГ-ММ")
    y, mo = (int(x) for x in month.split("-"))
    moved = a.s_premesteni
    days = {d: n for d, n in holidays(y, moved).items() if d.month == mo}
    found, missing_prev = person_months(store, person, month)
    in_month = [f for f in found if f[2] == month]
    by_day = {}
    for grafik, kind, m, row in found:
        for s in shifts_of(row, kind, m):
            for day in days:
                lo = max(s["start"], datetime.datetime.combine(day, datetime.time(0)))
                hi = min(s["end"], datetime.datetime.combine(day, datetime.time(0)) + datetime.timedelta(days=1))
                hours = (hi - lo).total_seconds() / 3600
                if hours > 0:
                    by_day.setdefault(day, []).append(
                        {"chasove": int(hours) if hours == int(hours) else round(hours, 2),
                         "ot": lo.strftime("%H:%M"), "do": "24:00" if hi.time() == datetime.time(0) else hi.strftime("%H:%M"),
                         "smyana_ot": s["start"].strftime("%Y-%m-%d"), "kod": s["kod"], "grafik": grafik})
    listed = [{"data": d.isoformat(), "den": DAYS[d.weekday()], "praznik": days[d],
               "chasove": sum(p["chasove"] for p in by_day[d]), "chasti": by_day[d]} for d in sorted(by_day)]
    notes = []
    if not in_month:
        notes.append(f"Няма го в записан график за {month}")
    first = datetime.date(y, mo, 1)
    if first in days and missing_prev and not any(f[2] != month for f in found):
        notes.append(f"1-ви е празник, а за {previous_month(month)} няма записан график – часовете от 00:00 до 08:00 "
                     f"на 1-ви от дежурство в последния ден на предния месец не са включени")
    out({"ok": True, "sluzhitel": person["ime_kratko"], "mesec": month,
         "s_premestenite_pochivni_dni": moved,
         "praznitsi_v_mesetsa": [{"data": d.isoformat(), "den": DAYS[d.weekday()], "ime": n} for d, n in days.items()],
         "praznichni_dni_s_dezhurstvo": len(listed), "praznichni_chasove": sum(d["chasove"] for d in listed),
         "dni": listed, "belezhki": notes})
    return 0


def cmd_na_data(a, store):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", a.date)
    if not m:
        raise Problem("Датата е във вида ГГГГ-ММ-ДД")
    try:
        day = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        raise Problem("Няма такава дата") from None
    hour, minute = SHIFT_START, 0
    if a.chas:
        hm = re.match(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$", a.chas)
        if not hm:
            raise Problem("Часът е във вида ЧЧ:ММ")
        hour, minute = int(hm.group(1)), int(hm.group(2))
    moment = datetime.datetime.combine(day, datetime.time(hour, minute))
    month = a.date[:7]
    kinds = registry()
    by_name = {norm(r["ime"]): r for r in roster(store)}
    result, missing = [], []
    for grafik in ([a.grafik] if a.grafik else sorted(kinds)):
        kind = kinds.get(grafik)
        if kind is None:
            raise Problem(f"Непознат график „{grafik}“")
        docs = [(mm, load_month(store, grafik, mm)) for mm in (previous_month(month), month)]
        if docs[1][1] is None:
            missing.append(grafik)
            if docs[0][1] is None or moment.day != 1 or moment.hour >= SHIFT_START:
                continue
        on_duty, working, others = [], [], []
        for mm, doc in docs:
            for row in (doc or {}).get("sluzhiteli", []):
                base = {"ime": row["ime"], "nomer": row["nomer"],
                        **({"smyana": row["smyana"]} if row.get("smyana") else {})}
                for s in shifts_of(row, kind, mm):
                    if s["start"] <= moment < s["end"]:
                        entry = {**base, **person_info(row["ime"], by_name, kind, s["myasto"]),
                                 "kod": s["kod"], "ot": fmt(s["start"]), "do": fmt(s["end"]),
                                 **({"myasto": s["myasto"]} if s["myasto"] else {})}
                        (on_duty if s["dezhurstvo"] else working).append(entry)
                if mm == month and a.vsichki:
                    code = code_on(row, moment.day)
                    if code and "chasove" not in kind["kodove"].get(code, {}):
                        others.append({**base, **person_info(row["ime"], by_name, kind), "kod": code,
                                       "znachenie": kind["kodove"].get(code, {}).get("znachenie", "")})
        entry = {"grafik": grafik, "ime_na_grafika": kind["ime"], "dezhurni": on_duty}
        if working:
            entry["na_rabota_bez_dezhurstvo"] = working
        if a.vsichki:
            entry["otsastvat"] = others
        result.append(entry)
    out({"ok": True, "kam": fmt(moment), "den": DAYS[day.weekday()],
         **({"praznik": holidays(day.year)[day]} if day in holidays(day.year) else {}),
         "grafici": result, "nyama_grafik_za_mesetsa": missing})
    return 0


def cmd_spisak(a, store):
    kinds = registry()
    items = []
    for grafik, month in store.months():
        text = store.get(grafik, month)
        doc = json.loads(text)
        items.append({"grafik": grafik, "mesec": month, "sluzhiteli": len(doc["sluzhiteli"]),
                      "izvan_razpisanieto": sum(1 for r in doc["sluzhiteli"] if not r["v_razpisanieto"]),
                      "sha256": sha(text)})
    out({"ok": True, "store": store.name,
         "vidove": {g: {"ime": k["ime"], "kodove": {c: d["znachenie"] for c, d in k["kodove"].items()}}
                    for g, k in kinds.items()},
         "mesetsi": items})
    return 0


def cmd_proverka(a, store):
    """Integrity of the store: every month file is canonical (not edited by hand) and valid."""
    kinds, problems, checked = registry(), [], 0
    for grafik, month in store.months():
        checked += 1
        where = f"{grafik} {month}"
        text = store.get(grafik, month)
        try:
            doc = json.loads(text)
        except ValueError as e:
            problems.append(f"{where}: не е JSON ({e})")
            continue
        last_day = last_day_of(month)
        rows = doc.get("sluzhiteli", [])
        codes = kinds.get(grafik, {}).get("kodove", {})
        if grafik not in kinds:
            problems.append(f"{where}: видът „{grafik}“ го няма в grafici.json")
        if doc.get("grafik") != grafik or doc.get("mesec") != month:
            problems.append(f"{where}: „grafik“/„mesec“ във файла не отговарят на името му")
        if rows != order(rows) or dump(doc) != text:
            problems.append(f"{where}: не е в каноничния вид – редактиран е на ръка; импортирай преписа отново")
        names, numbers = [norm(r.get("ime")) for r in rows], [r.get("nomer") for r in rows]
        if len(set(names)) != len(names) or len(set(numbers)) != len(numbers):
            problems.append(f"{where}: повтарящ се служител или №")
        for r in rows:
            taken = [d for days in r.get("dni", {}).values() for d in days]
            bad_code = [c for c in r.get("dni", {}) if c not in codes]
            if bad_code or len(set(taken)) != len(taken) or any(not 1 <= d <= last_day for d in taken):
                problems.append(f"{where}: {r.get('ime')} – непознат код, двоен ден или ден извън месеца")
    out({"ok": not problems, "store": store.name, "provereni": checked, "problemi": problems})
    return 1 if problems else 0


def cmd_mesec(a, store):
    doc = load_month(store, a.grafik, a.mesec)
    if doc is None:
        raise Problem(f"Няма график „{a.grafik}“ за {a.mesec}")
    last_day = last_day_of(a.mesec)
    print(f"{doc.get('zaglavie') or a.grafik} – {a.mesec}"
          + (f" (рег. № {doc['reg_nomer']})" if doc.get("reg_nomer") else ""))
    print("| № | Служител | См. | " + " | ".join(str(d) for d in range(1, last_day + 1)) + " |")
    print("|---|---|---|" + "---|" * last_day)
    for row in doc["sluzhiteli"]:
        cells = [code_on(row, d) or "" for d in range(1, last_day + 1)]
        name = row["ime"] + ("" if row["v_razpisanieto"] else " ⚠")
        print(f"| {row['nomer']} | {name} | {row.get('smyana', '')} | " + " | ".join(cells) + " |")
    if any(not r["v_razpisanieto"] for r in doc["sluzhiteli"]):
        print("\n⚠ = няма го в поименното разписание")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", help="локална папка с графиците вместо n8n (тестове, режим „конектор“)")
    ap.add_argument("--roster", metavar="ФАЙЛ", help="поименното разписание от файл вместо от n8n "
                                                     "(редовете от инструмента staff с csv: true)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import", help="записва или обновява месец от препис на снимка")
    p.add_argument("reading")
    p.add_argument("--replace", action="store_true", help="преписът е целият график: маха служителите, които ги няма в него")
    p.add_argument("--dry-run", action="store_true", help="само проверка; нищо не се записва")
    p.set_defaults(fn=cmd_import)
    p = sub.add_parser("na-data", help="кои са дежурни на дата")
    p.add_argument("date")
    p.add_argument("--chas", help="час ЧЧ:ММ (по подразбиране 08:00 – застъпващите на тази дата)")
    p.add_argument("--grafik")
    p.add_argument("--vsichki", action="store_true", help="и отпуски, командировки, болнични")
    p.set_defaults(fn=cmd_na_data)
    for name, fn, text in (("sluzhitel", cmd_sluzhitel, "кога е дежурен един служител"),
                           ("praznichni", cmd_praznichni, "празнични дни и часове на един служител в месеца")):
        p = sub.add_parser(name, help=text)
        p.add_argument("ime", nargs="?")
        p.add_argument("--az", action="store_true", help="служителят, чийто е личният ключ")
        p.add_argument("--mesec", help="ГГГГ-ММ (по подразбиране текущият месец)")
        if name == "praznichni":
            p.add_argument("--s-premesteni", action="store_true", help="брои и преместените почивни дни")
        p.set_defaults(fn=fn)
    p = sub.add_parser("praznitsi", help="официалните празници за година")
    p.add_argument("godina", type=int)
    p.add_argument("--s-premesteni", action="store_true", help="и преместените почивни дни")
    p.set_defaults(fn=cmd_praznitsi)
    p = sub.add_parser("mesec", help="решетката на месеца като таблица")
    p.add_argument("grafik")
    p.add_argument("mesec")
    p.set_defaults(fn=cmd_mesec)
    p = sub.add_parser("spisak", help="кои графици и месеци има")
    p.set_defaults(fn=cmd_spisak)
    p = sub.add_parser("proverka", help="проверява записаните месеци: каноничен вид, кодове, дни")
    p.set_defaults(fn=cmd_proverka)
    a = ap.parse_args()
    if a.roster:
        sluzhiteli.STAFF_FILE = a.roster
    try:
        store = None if a.cmd == "praznitsi" else (LocalStore(a.store) if a.store else RemoteStore())
        sys.exit(a.fn(a, store))
    except Problem as e:
        sys.exit(fail(str(e)))


if __name__ == "__main__":
    main()
