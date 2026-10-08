#!/usr/bin/env python3
"""formulyar.json: every form, question and cause code is consistent. Run: python3 tests/test_formulyar.py"""
import json
import os
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
f = json.load(open(os.path.join(SKILL, "references", "formulyar.json"), encoding="utf-8"))
errors = []

for key, form in f["forms"].items():
    ids = [q["id"] for q in form["questions"]]
    if len(ids) != len(set(ids)):
        errors.append(f"{key}: повтарящ се id")
    for q in form["questions"]:
        if len(q["options"]) < 2:
            errors.append(f"{key}.{q['id']}: под 2 опции")
        d = q.get("default")
        if d is not None and d != [] and (d if isinstance(d, list) else [d]) and not set(d if isinstance(d, list) else [d]) <= set(q["options"]):
            errors.append(f"{key}.{q['id']}: default не е сред опциите")

codes = f["causes"]["codes"]
for key, form in f["forms"].items():
    for q in form["questions"]:
        for c, answer in q.get("by_cause", {}).items():
            if c not in codes or answer not in q["options"]:
                errors.append(f"{key}.{q['id']}: by_cause {c} → {answer} не е познат код или опция")
for key, order in f["causes"]["by_form"].items():
    if key not in f["forms"]:
        errors.append(f"causes.by_form: няма формуляр {key}")
    for c in order:
        if c not in codes:
            errors.append(f"causes.by_form.{key}: непознат код {c}")
    if f["causes"]["in_progress"] in order:
        errors.append(f"causes.by_form.{key}: съдържа „в процес“")
for c, d in f["causes"]["details"].items():
    if c not in codes or "default" not in d:
        errors.append(f"causes.details.{c}: непознат код или липсва default")
if set(f["forms"]) != set(f["causes"]["by_form"]):
    errors.append("causes.by_form трябва да покрива всички формуляри")

for key in ("sgrada", "mps", "postroika", "pole", "otpadatsi", "saorazhenie", "promishlen", "obsht"):
    if key not in f["forms"]:
        errors.append(f"липсва формуляр {key}")
# the area is „около N <unit>“ – a value that goes into the text as it is, never a range
for key, form in f["forms"].items():
    for q in form["questions"]:
        if q["id"] == "plosht":
            unit = q.get("number")
            if unit not in ("кв. м", "дка"):
                errors.append(f"{key}.plosht: липсва number (кв. м или дка)")
            for o in q["options"]:
                p = o.split()
                if not (len(p) >= 3 and p[0] == "около" and p[1].isdigit() and o.endswith(unit or "?")):
                    errors.append(f"{key}.plosht: „{o}“ не е „около N {unit}“")
# details may be given per form – the key must be a form
for c, d in f["causes"]["details"].items():
    for k in d:
        if k != "default" and k not in f["forms"]:
            errors.append(f"causes.details.{c}: непознат формуляр {k}")
# routing: the object classes of the incidents base go to the form meant for them
CLASSES = {
    "жилищни, администр.и др. непромишлени сгради-1": "sgrada", "транспортни средства-4": "mps",
    "спомагат, временни или паянтови постройки-3": "postroika", "промишлени обекти-2": "promishlen",
    "полски (извън урбаниз.тер-ии)-6": "pole", "горски-5": "pole", "стърнища-3": "pole",
    "сухи треви, паднала листна маса и храсти в урбаниз.територии-1": "pole", "отпадъци-4": "otpadatsi",
}
TEXT = {("други-10", "бали сено"): "otpadatsi", ("други-10", "суха трева и фургон"): "pole",
        ("други-10", "газова бутилка"): "obsht", ("съоръжения на открито-9", "пластмасов контейнер за отпадъци"): "otpadatsi",
        ("съоръжения на открито-9", "улично ел. табло"): "saorazhenie", ("съоръжения на открито-9", "дървена беседка"): "saorazhenie",
        ("открити площадки (терени) в урбаниз.територии-8", "складирани гуми"): "otpadatsi", ("", "цех за пелети"): "promishlen"}


def by_text(obj, fallback="obsht"):
    obj, best = " " + obj.lower() + " ", None
    for key, form in f["forms"].items():
        for w in form["object_words"]:
            i = obj.find(w)
            if i >= 0 and (best is None or i < best[0]):
                best = (i, key)
    return best[1] if best else fallback


def route(cls, obj=""):
    for c, fb in f["text_routed"]["classes"].items():
        if cls.lower().startswith(c):
            return by_text(obj, fb)
    for key, form in f["forms"].items():
        if any(s in cls.lower() for s in form["ucasulaty"]):
            return key
    return by_text(obj)


for cls, want in CLASSES.items():
    if route(cls) != want:
        errors.append(f"класът „{cls}“ отива във формуляр {route(cls)}, а трябва в {want}")
for (cls, obj), want in TEXT.items():
    if route(cls, obj) != want:
        errors.append(f"„{obj}“ ({cls or 'без клас'}) отива във формуляр {route(cls, obj)}, а трябва в {want}")
for c, fb in f["text_routed"]["classes"].items():
    if fb not in f["forms"]:
        errors.append(f"text_routed: няма формуляр {fb}")

if "барака" not in f.get("place_ignore", {}).get("values", []):
    errors.append("place_ignore трябва да съдържа „барака“")

print("\n".join(errors) or "OK")
sys.exit(1 if errors else 0)
