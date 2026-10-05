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

if "барака" not in f.get("place_ignore", {}).get("values", []):
    errors.append("place_ignore трябва да съдържа „барака“")

print("\n".join(errors) or "OK")
sys.exit(1 if errors else 0)
