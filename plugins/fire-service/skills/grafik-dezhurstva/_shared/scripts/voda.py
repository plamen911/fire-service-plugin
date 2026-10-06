#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
voda.py — водоизточниците за пожарогасене в района на РДПБЗН – Плевен: пожарни хидранти,
водоеми, смукателни точки. Къде са, колко точни са координатите им, кои са най-близо.

Таблицата (`vodoiztochnitsi.csv`) не е в пакета – пази се в Google Drive и се чете през n8n с
личния ключ (кешира се за 10 минути). Без ключ скриптът спира с `NO_KEY` – тогава данните идват
от инструментите `voda` и `voda_save` на конектора Fire Service (`_shared/connector.md`).

    python3 _shared/scripts/voda.py masto Биволаре                  # водоизточниците в населено място
    python3 _shared/scripts/voda.py masto Искър --obshtina Гулянци  # когато името се повтаря
    python3 _shared/scripts/voda.py sluzhba Кнежа                   # по населени места в района на служба/участък
    python3 _shared/scripts/voda.py blizo --lat 43.4852 --lon 24.5591          # най-близките до точка
    python3 _shared/scripts/voda.py blizo --link "https://maps.google.com/?q=43.4852,24.5591"
    python3 _shared/scripts/voda.py blizo --masto Тръстеник         # най-близките до центъра на населено място
    python3 _shared/scripts/voda.py statistika                      # колко са, с какви координати, къде няма
    python3 _shared/scripts/voda.py eksport --masto Рибен --format kml -o ribn.kml   # за карта в телефона

Запис (всеки с личен ключ; промяната се прилага на сървъра върху текущата таблица):
    python3 _shared/scripts/voda.py dobavi --masto Биволаре --vid хидрант --tip надземен --lat 43.4852 --lon 24.5591 \
        --orientir "пред кметството"
    python3 _shared/scripts/voda.py potvardi 03993-001 --link "https://maps.google.com/?q=43.4852,24.5591"
    python3 _shared/scripts/voda.py promeni 03993-001 sastoyanie=неизправен belezhka="без капак"
Всяка от трите приема --dry-run (само показва какво би записала).

Администраторът, когато излезе нова заповед за районите на действие:
    python3 _shared/scripts/voda.py mesta -o vodoiztochnitsi_mesta.csv   # населените места за сървъра
    python3 tools/admin.py files put raioni vodoiztochnitsi_mesta.csv

Точност на координатите (колона `tochnost`):
    проверена – снета на място при хидранта;        вик – от списъка на „ВиК“ ЕООД – Плевен;
    адрес     – геокодирана по улица и номер;        улица – геокодирана само по улица (средата ѝ);
    (празно)  – няма координати.
„Точни“ са само „проверена“ и „вик“. Останалите са ориентир и никога не се дават като място на хидранта.

Всички команди приемат --json и --csv ФАЙЛ (таблица от файл вместо от n8n; записът също отива във файла).
"""
import argparse
import csv
import datetime
import io
import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import api_config  # noqa: E402
import koya_sluzhba  # noqa: E402  (settlement → service, by the order for the районите на действие)

TABLE, KIND = "vodoiztochnitsi.csv", "raioni"
CACHE_SECONDS = 600
CSV_FILE = os.environ.get("FIRE_SERVICE_VODA_CSV") or None
CENTRES = os.environ.get("FIRE_SERVICE_CENTRES_CSV") or os.path.join(os.path.dirname(HERE), "raioni", "koordinati_pleven.csv")
PLEVEN = "РДПБЗН – Плевен"
FIELDS = ["id", "ekatte", "naseleno_masto", "obshtina", "sluzhba", "uchastak", "vid", "tip", "diametar",
          "kvartal", "ok", "ulitsa", "orientir", "lat", "lon", "tochnost", "sastoyanie", "proveren_na",
          "proveril", "iztochnik", "belezhka"]
VID = ["хидрант", "водоем", "смукателна точка", "резервоар", "сондаж"]
TIP = ["надземен", "подземен", "стенен", ""]
TOCHNOST = {"проверена": "проверена на място", "вик": "от списъка на ВиК",
            "адрес": "приблизителна – по адрес", "улица": "приблизителна – по улица (средата ѝ)", "": "няма координати"}
EXACT = ("проверена", "вик")
EDITABLE = ["vid", "tip", "diametar", "kvartal", "ok", "ulitsa", "orientir", "sastoyanie", "belezhka",
            "proveren_na", "proveril"]
BBOX = (43.0, 43.9, 23.9, 25.4)   # област Плевен with a margin: south, north, west, east
SAME_M = 15                        # a new point this close to an exact one is the same water source
FAR_KM = 8                         # a point this far from the settlement's centre is refused


class Problem(Exception):
    pass


def norm(s):
    return koya_sluzhba.norm(s)


def metres(a, b):
    """Distance between two (lat, lon) points."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def point(r):
    try:
        return float(r["lat"]), float(r["lon"])
    except (TypeError, ValueError, KeyError):
        return None


def link(p):
    return f"https://www.google.com/maps?q={p[0]:.7f},{p[1]:.7f}"


# ── storage ────────────────────────────────────────────────────────────────────────────────
class Store:
    """The table: a local CSV file (tests, --csv) or the file behind n8n."""

    def __init__(self, path=None):
        self.path = path or CSV_FILE
        self.cache = os.path.join(tempfile.gettempdir(), "fire_service_" + TABLE)

    def _remote(self, fresh):
        if not api_config.has_key():
            raise Problem(api_config.NO_KEY + " – инструментите voda и voda_save")
        if not fresh:
            try:
                if time.time() - os.path.getmtime(self.cache) < CACHE_SECONDS:
                    with open(self.cache, encoding="utf-8") as f:
                        return f.read()
            except OSError:
                pass
        try:
            text = api_config.post("samples_url", {"action": "get", "kind": KIND, "name": TABLE}, timeout=120)["text"]
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="ignore")[:200]
            if e.code == 404 or "NOT_FOUND" in body:
                raise Problem("NO_DATA: таблицата с водоизточниците още не е качена")
            raise Problem(f"N8N_UNAVAILABLE: HTTP {e.code} {body}")
        except (OSError, KeyError, ValueError) as e:
            raise Problem(f"N8N_UNAVAILABLE: {type(e).__name__}: {e}"[:300])
        self._keep(text)
        return text

    def _keep(self, text):
        try:
            with open(self.cache, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass

    def rows(self, fresh=False):
        if self.path:
            try:
                with open(self.path, encoding="utf-8-sig") as f:
                    text = f.read()
            except OSError as e:
                raise Problem(f"NO_DATA: {e}")
        else:
            text = self._remote(fresh)
        return [{k: (r.get(k) or "").strip() for k in FIELDS} for r in csv.DictReader(io.StringIO(text))]

    def save(self, rows):
        text = dump(rows)
        if self.path:
            with open(self.path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            return {"where": self.path}
        raise Problem("BUG: the table behind n8n is changed one water source at a time (see remote_write)")

    def forget(self):
        """Drop the cached copy after a change on the server."""
        try:
            os.remove(self.cache)
        except OSError:
            pass


def remote_write(a, store, body):
    """One change, applied by n8n to the current table (any active key may write)."""
    body = {k: v for k, v in body.items() if v not in ("", None, False)}
    try:
        with urllib.request.urlopen(api_config.request("voda_url", body), timeout=120) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="ignore")
        try:
            msg = str(json.loads(raw).get("error") or raw)
        except ValueError:
            msg = raw
        if e.code in (401, 403) and "UNAUTHORIZED" in msg:
            raise Problem(f"KEY_REJECTED: n8n не приема личния ключ – {msg}"[:300])
        raise Problem(msg[:400] if re.match(r"^[A-Z_]+:", msg) else f"N8N_UNAVAILABLE: HTTP {e.code} {msg}"[:300])
    except (OSError, ValueError) as e:
        raise Problem(f"N8N_UNAVAILABLE: {type(e).__name__}: {e}"[:300])
    store.forget()
    v = {k: ("" if x is None else x) for k, x in (res.get("vodoiztochnik") or {}).items()}
    what = {"dobaven": "Добавен", "obnoven": "Вече има водоизточник на това място – обновен е", "potvarden": "Потвърден на място",
            "promenen": "Променен", "bez_promyana": "Без промяна"}.get(res.get("deystvie"), str(res.get("deystvie")))
    emit(a, res, f"{what}: {describe(v)}" + (" (проба – нищо не е записано)" if res.get("dry_run") else ""))


def order(rows):
    return sorted(rows, key=lambda r: (r["sluzhba"], r["uchastak"], r["obshtina"], norm(r["naseleno_masto"]), r["id"]))


def dump(rows):
    """The canonical text of the table: fixed columns, fixed order, \\n line ends."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    for r in order(rows):
        w.writerow({k: r.get(k, "") for k in FIELDS})
    return buf.getvalue()


# ── settlements ────────────────────────────────────────────────────────────────────────────
def centres():
    out = {}
    try:
        with open(CENTRES, encoding="utf-8") as f:
            for r in csv.DictReader(line for line in f if not line.startswith("#")):
                out[r["ekatte"]] = (float(r["lat"]), float(r["lng"]))
    except (OSError, ValueError, KeyError):
        pass
    return out


def settlement(name, obshtina=None):
    """One settlement of РДПБЗН – Плевен by name (and община when the name repeats)."""
    q = norm(name)
    if not q:
        raise Problem("BAD_INPUT: липсва населено място")
    hit = [r for r in koya_sluzhba.load() if r["rdpbzn"] == PLEVEN and norm(r["naseleno_masto"]) == q]
    if obshtina:
        hit = [r for r in hit if norm(r["obshtina"]) == norm(obshtina)]
    if not hit:
        raise Problem(f"NOT_FOUND: няма населено място „{name}“ в района на РДПБЗН – Плевен"
                      + (f" в община {obshtina}" if obshtina else ""))
    if len(hit) > 1:
        raise Problem("AMBIGUOUS: " + "; ".join(f'{r["vid"]} {r["naseleno_masto"]}, общ. {r["obshtina"]}' for r in hit)
                      + " – добави --obshtina")
    return hit[0]


def place_name(s):
    return f'{s["vid"]} {s["naseleno_masto"]}'


def unit(r):
    return r["uchastak"] + f' ({r["sluzhba"]})' if r["uchastak"] else r["sluzhba"]


# ── output ─────────────────────────────────────────────────────────────────────────────────
def describe(r):
    kind = ", ".join(x for x in (r["vid"], r["tip"], r["diametar"]) if x)
    where = ", ".join(x for x in (("ул. " + r["ulitsa"]) if r["ulitsa"] else "", r["orientir"]) if x) or "без адрес"
    p = point(r)
    coord = f'{p[0]:.7f}, {p[1]:.7f} – {TOCHNOST.get(r["tochnost"], r["tochnost"])}' if p else TOCHNOST[""]
    line = f'{r["id"]} | {kind} | {where} | {coord}'
    if r["sastoyanie"]:
        line += f' | състояние: {r["sastoyanie"]}'
    if r["belezhka"]:
        line += f' | {r["belezhka"]}'
    if p and r["tochnost"] in EXACT:
        line += f" | {link(p)}"
    return line


def public(r, extra=None):
    out = dict(r)
    p = point(r)
    out["lat"], out["lon"] = (p[0], p[1]) if p else (None, None)
    out["tochni_koordinati"] = bool(p) and r["tochnost"] in EXACT
    out["tochnost_opisanie"] = TOCHNOST.get(r["tochnost"], r["tochnost"])
    out["navigatsiya"] = link(p) if p and r["tochnost"] in EXACT else None
    out.update(extra or {})
    return out


def counts(rows):
    c = {"obshto": len(rows), "tochni": 0, "priblizitelni": 0, "bez_koordinati": 0}
    for r in rows:
        if not point(r):
            c["bez_koordinati"] += 1
        elif r["tochnost"] in EXACT:
            c["tochni"] += 1
        else:
            c["priblizitelni"] += 1
    return c


def nearest(rows, origin, n, radius=None, approx=False, skip_ekatte=None):
    found = []
    for r in rows:
        p = point(r)
        if not p or (r["tochnost"] not in EXACT and not approx) or r["ekatte"] == skip_ekatte:
            continue
        d = metres(origin, p)
        if radius is None or d <= radius:
            found.append((d, r))
    found.sort(key=lambda x: x[0])
    return found[:n]


def emit(a, obj, text):
    if a.json:
        print(json.dumps(obj, ensure_ascii=False, indent=1))
    else:
        print(text)


# ── read commands ──────────────────────────────────────────────────────────────────────────
def cmd_masto(a, store):
    s = settlement(a.ime, a.obshtina)
    rows = [r for r in store.rows() if r["ekatte"] == s["ekatte"]]
    if a.vid:
        rows = [r for r in rows if r["vid"] == a.vid]
    rows.sort(key=lambda r: (r["tochnost"] not in EXACT, not point(r), r["id"]))
    head = f'{place_name(s)}, общ. {s["obshtina"]} – {unit(s)}'
    obj = {"masto": place_name(s), "ekatte": s["ekatte"], "obshtina": s["obshtina"], "sluzhba": s["sluzhba"],
           "uchastak": s["uchastak"], **counts(rows), "vodoiztochnitsi": [public(r) for r in rows]}
    lines = [head]
    c = counts(rows)
    if rows:
        lines.append(f'Водоизточници: {c["obshto"]} – с точни координати {c["tochni"]}, '
                     f'с приблизителни {c["priblizitelni"]}, без координати {c["bez_koordinati"]}')
        lines += ["  " + describe(r) for r in rows]
    if not c["tochni"]:
        centre = centres().get(s["ekatte"])
        if not rows:
            lines.append("Няма въведени водоизточници за това населено място.")
        if centre:
            near = nearest(store.rows(), centre, 3, skip_ekatte=s["ekatte"])
            obj["nay_blizki_drugade"] = [public(r, {"razstoyanie_m": round(d)}) for d, r in near]
            if near:
                lines.append("Най-близките с точни координати в други населени места (от центъра на населеното място):")
                lines += [f'  {d / 1000:.1f} km – {r["naseleno_masto"]}: {describe(r)}' for d, r in near]
    emit(a, obj, "\n".join(lines))


def cmd_sluzhba(a, store):
    q = norm(a.ime)
    rows = [r for r in store.rows() if q in norm(r["sluzhba"]) or q in norm(r["uchastak"])]
    if a.samo_uchastak:
        rows = [r for r in rows if q in norm(r["uchastak"])]
    if not rows:
        raise Problem(f"NOT_FOUND: няма водоизточници за служба или участък „{a.ime}“")
    groups = {}
    for r in rows:
        groups.setdefault((unit(r), r["obshtina"], r["naseleno_masto"], r["ekatte"]), []).append(r)
    places = [{"sluzhba": k[0], "obshtina": k[1], "masto": k[2], "ekatte": k[3], **counts(v)} for k, v in sorted(groups.items())]
    total = counts(rows)
    lines = [f'„{a.ime}“: {total["obshto"]} водоизточника в {len(places)} населени места – с точни координати '
             f'{total["tochni"]}, с приблизителни {total["priblizitelni"]}, без координати {total["bez_koordinati"]}']
    lines += [f'  {p["masto"]} (общ. {p["obshtina"]}; {p["sluzhba"]}): {p["obshto"]} – точни {p["tochni"]}, '
              f'приблизителни {p["priblizitelni"]}, без {p["bez_koordinati"]}' for p in places]
    emit(a, {"zayavka": a.ime, **total, "naseleni_mesta": places}, "\n".join(lines))


def parse_link(text):
    """(lat, lon) from a Google/Apple Maps link or a "43.48, 24.55" pair."""
    t = text.strip()
    for pat in (r"[?&](?:q|query|ll|center|destination)=(-?\d+\.\d+)(?:,|%2C)\s*(-?\d+\.\d+)",
                r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", r"@(-?\d+\.\d+),(-?\d+\.\d+)",
                r"^\s*(-?\d+\.\d+)\s*[,;\s]\s*(-?\d+\.\d+)\s*$"):
        m = re.search(pat, t)
        if m:
            return float(m.group(1)), float(m.group(2))
    raise Problem("BAD_INPUT: в това няма координати – дай ширина и дължина (43.4852, 24.5591) или пълен линк от "
                  "картата; съкратените линкове (maps.app.goo.gl) не съдържат координати")


def origin_of(a):
    if a.link:
        return parse_link(a.link)
    if a.lat is not None and a.lon is not None:
        return a.lat, a.lon
    raise Problem("BAD_INPUT: дай --lat и --lon или --link")


def check_point(p):
    if not (BBOX[0] <= p[0] <= BBOX[1] and BBOX[2] <= p[1] <= BBOX[3]):
        raise Problem(f"BAD_INPUT: точката {p[0]}, {p[1]} е извън област Плевен – провери дали ширината и дължината не са разменени")
    return p


def cmd_blizo(a, store):
    skip = None
    if a.masto:
        s = settlement(a.masto, a.obshtina)
        origin = centres().get(s["ekatte"])
        if not origin:
            raise Problem(f"NOT_FOUND: няма координати на центъра на {place_name(s)} – дай --lat и --lon")
        label = f'центъра на {place_name(s)}'
    else:
        origin = check_point(origin_of(a))
        label = f"{origin[0]:.6f}, {origin[1]:.6f}"
    near = nearest(store.rows(), origin, a.broi, a.radius_m, a.s_priblizitelni, skip)
    obj = {"ot": label, "lat": origin[0], "lon": origin[1], "samo_tochni": not a.s_priblizitelni,
           "vodoiztochnitsi": [public(r, {"razstoyanie_m": round(d)}) for d, r in near]}
    lines = [f"Най-близки водоизточници до {label}" + ("" if a.s_priblizitelni else " (само с точни координати)") + ":"]
    lines += [f'  {round(d)} m – {r["naseleno_masto"]}: {describe(r)}' for d, r in near] or ["  няма в зададения радиус"]
    emit(a, obj, "\n".join(lines))


def cmd_statistika(a, store):
    rows = store.rows()
    by_unit, with_data = {}, set()
    for r in rows:
        by_unit.setdefault(unit(r), []).append(r)
        with_data.add(r["ekatte"])
    units = [{"sluzhba": k, **counts(v), "naseleni_mesta": len({r["ekatte"] for r in v})} for k, v in sorted(by_unit.items())]
    missing = []
    try:
        missing = sorted(f'{s["vid"]} {s["naseleno_masto"]} (общ. {s["obshtina"]})' for s in koya_sluzhba.load()
                         if s["rdpbzn"] == PLEVEN and s["ekatte"] not in with_data)
    except SystemExit:
        pass
    total = counts(rows)
    kinds = {}
    for r in rows:
        kinds[r["vid"]] = kinds.get(r["vid"], 0) + 1
    lines = [f'Водоизточници: {total["obshto"]} в {len(with_data)} населени места – с точни координати {total["tochni"]}, '
             f'с приблизителни {total["priblizitelni"]}, без координати {total["bez_koordinati"]}',
             "По вид: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items()))]
    lines += [f'  {u["sluzhba"]}: {u["obshto"]} – точни {u["tochni"]}, приблизителни {u["priblizitelni"]}, '
              f'без {u["bez_koordinati"]}' for u in units]
    if missing:
        lines.append(f"Населени места без нито един въведен водоизточник ({len(missing)}): " + ", ".join(missing))
    emit(a, {**total, "po_vid": kinds, "po_sluzhba": units, "bez_vodoiztochnitsi": missing}, "\n".join(lines))


def cmd_eksport(a, store):
    rows = store.rows()
    if a.masto:
        s = settlement(a.masto, a.obshtina)
        rows = [r for r in rows if r["ekatte"] == s["ekatte"]]
    if a.sluzhba:
        q = norm(a.sluzhba)
        rows = [r for r in rows if q in norm(r["sluzhba"]) or q in norm(r["uchastak"])]
    if not a.s_priblizitelni:
        rows = [r for r in rows if r["tochnost"] in EXACT]
    rows = [r for r in order(rows) if point(r) or a.format == "csv"]
    if not rows:
        raise Problem("NOT_FOUND: няма водоизточници с точни координати за това търсене")
    if a.format == "csv":
        text = dump(rows)
    else:
        esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
        marks = []
        for r in rows:
            p = point(r)
            desc = "; ".join(x for x in (r["tip"], r["diametar"], ("ул. " + r["ulitsa"]) if r["ulitsa"] else "", r["orientir"],
                                         TOCHNOST.get(r["tochnost"], ""), r["sastoyanie"], r["belezhka"]) if x)
            marks.append(f'<Placemark><name>{esc(r["naseleno_masto"] + " – " + r["vid"] + " " + r["id"])}</name>'
                         f"<description>{esc(desc)}</description><Point><coordinates>{p[1]:.7f},{p[0]:.7f},0</coordinates></Point></Placemark>")
        text = ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
                "<name>Водоизточници – РДПБЗН – Плевен</name>\n" + "\n".join(marks) + "\n</Document></kml>\n")
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    emit(a, {"file": a.out, "format": a.format, "broi": len(rows)}, f"{a.out}: {len(rows)} водоизточника")


# ── write commands ─────────────────────────────────────────────────────────────────────────
def who(a, store):
    if a.proveril:
        return a.proveril.strip()
    if store.path:
        return ""
    try:
        return str((api_config.post("duty_url", {"action": "whoami"}, timeout=30) or {}).get("client") or "")
    except (Exception, SystemExit):  # noqa: BLE001  the name is a courtesy, never a reason to fail
        return ""


def today():
    return datetime.date.today().isoformat()


def finish(a, store, rows, obj, text):
    obj["dry_run"] = bool(a.dry_run)
    if not a.dry_run:
        obj["zapis"] = store.save(rows)
    emit(a, obj, text + (" (проба – нищо не е записано)" if a.dry_run else ""))


def cmd_dobavi(a, store):
    p = check_point(origin_of(a))
    if not store.path:
        return remote_write(a, store, {"action": "dobavi", "masto": a.masto, "obshtina": a.obshtina, "vid": a.vid, "tip": a.tip,
                                       "lat": p[0], "lon": p[1], "diametar": a.diametar, "ulitsa": a.ulitsa, "orientir": a.orientir,
                                       "sastoyanie": a.sastoyanie, "belezhka": a.belezhka, "vapreki": a.vapreki,
                                       "dry_run": a.dry_run, "proveril": a.proveril})
    s = settlement(a.masto, a.obshtina)
    centre = centres().get(s["ekatte"])
    if centre and metres(centre, p) > FAR_KM * 1000 and not a.vapreki:
        raise Problem(f"TOO_FAR: точката е на {metres(centre, p) / 1000:.1f} km от центъра на {place_name(s)} – "
                      "провери населеното място или координатите (--vapreki записва въпреки това)")
    if a.vid not in VID:
        raise Problem("BAD_INPUT: --vid е едно от: " + ", ".join(VID))
    if a.tip not in TIP:
        raise Problem("BAD_INPUT: --tip е надземен, подземен или стенен")
    rows = store.rows(fresh=True)
    given = {"tip": a.tip, "diametar": a.diametar, "ulitsa": a.ulitsa, "orientir": a.orientir,
             "sastoyanie": a.sastoyanie, "belezhka": a.belezhka}
    same = [(metres(p, point(r)), r) for r in rows if point(r) and r["tochnost"] in EXACT and metres(p, point(r)) <= SAME_M]
    same.sort(key=lambda x: x[0])
    name = who(a, store)
    if same:  # the same water source: confirm it, keep what is already known, add what is new
        r = same[0][1]
        for k, v in given.items():
            if v:
                r[k] = v
        r.update(lat=f"{p[0]:.7f}", lon=f"{p[1]:.7f}", tochnost="проверена", proveren_na=today(), proveril=name or r["proveril"])
        return finish(a, store, rows, {"deystvie": "obnoven", "razstoyanie_m": round(same[0][0], 1), "vodoiztochnik": public(r)},
                      f'Вече има водоизточник на {same[0][0]:.0f} m – обновен е: {describe(r)}')
    used = [int(r["id"].split("-")[1]) for r in rows if r["ekatte"] == s["ekatte"] and re.match(r"^\d{5}-\d+$", r["id"])]
    r = {k: "" for k in FIELDS}
    r.update(given, id=f'{s["ekatte"]}-{max(used, default=0) + 1:03d}', ekatte=s["ekatte"], naseleno_masto=place_name(s),
             obshtina=s["obshtina"], sluzhba=s["sluzhba"], uchastak=s["uchastak"], vid=a.vid, lat=f"{p[0]:.7f}",
             lon=f"{p[1]:.7f}", tochnost="проверена", proveren_na=today(), proveril=name, iztochnik="въведен на място")
    rows.append(r)
    finish(a, store, rows, {"deystvie": "dobaven", "vodoiztochnik": public(r)}, f"Добавен: {describe(r)}")


def find(rows, ident):
    hit = [r for r in rows if r["id"] == ident.strip()]
    if not hit:
        raise Problem(f"NOT_FOUND: няма водоизточник с номер {ident}")
    return hit[0]


def cmd_potvardi(a, store):
    p = check_point(origin_of(a))
    if not store.path:
        return remote_write(a, store, {"action": "potvardi", "id": a.id, "lat": p[0], "lon": p[1], "sastoyanie": a.sastoyanie,
                                       "dry_run": a.dry_run, "proveril": a.proveril})
    rows = store.rows(fresh=True)
    r = find(rows, a.id)
    old = point(r)
    moved = round(metres(old, p)) if old else None
    r.update(lat=f"{p[0]:.7f}", lon=f"{p[1]:.7f}", tochnost="проверена", proveren_na=today(), proveril=who(a, store) or r["proveril"])
    if a.sastoyanie:
        r["sastoyanie"] = a.sastoyanie
    finish(a, store, rows, {"deystvie": "potvarden", "premesten_m": moved, "vodoiztochnik": public(r)},
           f"Потвърден на място: {describe(r)}" + (f" (преместен с {moved} m спрямо предишните координати)" if moved else ""))


def cmd_promeni(a, store):
    pairs = {}
    for item in a.fields:
        k, sep, v = item.partition("=")
        k, v = k.strip(), v.strip()
        if not sep or k not in EDITABLE:
            raise Problem(f"BAD_INPUT: „{item}“ – очаква се поле=стойност; полета: " + ", ".join(EDITABLE)
                          + " (координатите се сменят с potvardi)")
        pairs[k] = v
    if not store.path:
        return remote_write(a, store, {"action": "promeni", "id": a.id, "set": pairs, "dry_run": a.dry_run})
    rows = store.rows(fresh=True)
    r = find(rows, a.id)
    changed = {}
    for k, v in pairs.items():
        if k == "vid" and v not in VID:
            raise Problem("BAD_INPUT: vid е едно от: " + ", ".join(VID))
        if k == "tip" and v not in TIP:
            raise Problem("BAD_INPUT: tip е надземен, подземен или стенен")
        if r[k] != v:
            changed[k] = {"ot": r[k], "na": v}
            r[k] = v
    if not changed:
        return emit(a, {"deystvie": "bez_promyana", "vodoiztochnik": public(r)}, f"Без промяна: {describe(r)}")
    finish(a, store, rows, {"deystvie": "promenen", "promeni": changed, "vodoiztochnik": public(r)}, f"Променен: {describe(r)}")


def cmd_mesta(a, store):
    """The settlements of РДПБЗН – Плевен with their service and centre: what n8n checks a new point against."""
    c = centres()
    places = sorted((s for s in koya_sluzhba.load() if s["rdpbzn"] == PLEVEN), key=lambda s: s["ekatte"])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["ekatte", "vid", "naseleno_masto", "obshtina", "sluzhba", "uchastak", "lat", "lon"])
    for s in places:
        p = c.get(s["ekatte"])
        w.writerow([s["ekatte"], s["vid"], s["naseleno_masto"], s["obshtina"], s["sluzhba"], s["uchastak"],
                    f"{p[0]:.5f}" if p else "", f"{p[1]:.5f}" if p else ""])
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())
    emit(a, {"file": a.out, "broi": len(places), "bez_tsentar": sum(1 for s in places if s["ekatte"] not in c)},
         f"{a.out}: {len(places)} населени места")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    common.add_argument("--csv", metavar="ФАЙЛ", help="таблицата от файл вместо от n8n")
    where = argparse.ArgumentParser(add_help=False)
    where.add_argument("--lat", type=float)
    where.add_argument("--lon", type=float)
    where.add_argument("--link", help="линк от картата или „ширина, дължина“")
    write = argparse.ArgumentParser(add_help=False)
    write.add_argument("--dry-run", action="store_true", help="само проба; нищо не се записва")
    write.add_argument("--proveril", help="кой е проверил на място (по подразбиране – чийто е ключът)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("masto", parents=[common]); p.add_argument("ime"); p.add_argument("--obshtina")
    p.add_argument("--vid", choices=VID)
    p = sub.add_parser("sluzhba", parents=[common]); p.add_argument("ime")
    p.add_argument("--samo-uchastak", action="store_true", help="само участъка, не цялата районна служба")
    p = sub.add_parser("blizo", parents=[common, where]); p.add_argument("--masto"); p.add_argument("--obshtina")
    p.add_argument("--broi", type=int, default=5); p.add_argument("--radius-m", type=float)
    p.add_argument("--s-priblizitelni", action="store_true", help="и геокодираните по адрес/улица")
    sub.add_parser("statistika", parents=[common])
    p = sub.add_parser("eksport", parents=[common]); p.add_argument("--masto"); p.add_argument("--obshtina")
    p.add_argument("--sluzhba"); p.add_argument("--format", choices=["kml", "csv"], default="kml")
    p.add_argument("--s-priblizitelni", action="store_true"); p.add_argument("-o", "--out", required=True)
    p = sub.add_parser("dobavi", parents=[common, where, write]); p.add_argument("--masto", required=True)
    p.add_argument("--obshtina"); p.add_argument("--vid", default="хидрант"); p.add_argument("--tip", default="")
    p.add_argument("--diametar", default=""); p.add_argument("--ulitsa", default=""); p.add_argument("--orientir", default="")
    p.add_argument("--sastoyanie", default=""); p.add_argument("--belezhka", default="")
    p.add_argument("--vapreki", action="store_true", help="записва и точка далеч от центъра на населеното място")
    p = sub.add_parser("potvardi", parents=[common, where, write]); p.add_argument("id"); p.add_argument("--sastoyanie", default="")
    p = sub.add_parser("promeni", parents=[common, write]); p.add_argument("id")
    p.add_argument("fields", nargs="+", metavar="поле=стойност")
    p = sub.add_parser("mesta", parents=[common]); p.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    if a.csv:
        os.environ["FIRE_SERVICE_VODA_CSV"] = a.csv
    try:
        {"masto": cmd_masto, "sluzhba": cmd_sluzhba, "blizo": cmd_blizo, "statistika": cmd_statistika,
         "eksport": cmd_eksport, "mesta": cmd_mesta, "dobavi": cmd_dobavi, "potvardi": cmd_potvardi, "promeni": cmd_promeni}[a.cmd](a, Store(a.csv))
    except Problem as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
