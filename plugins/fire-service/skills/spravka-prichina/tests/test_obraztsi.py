#!/usr/bin/env python3
"""Tests for _shared/scripts/obraztsi.py on a local store. Run from the skill folder: python3 tests/test_obraztsi.py"""
import json
import os
import subprocess
import sys
import tempfile

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(SKILL, "_shared", "scripts", "obraztsi.py")
failures = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def run(store, *args):
    r = subprocess.run([sys.executable, SCRIPT, "--store", store, *args], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


if __name__ == "__main__":
    print("obraztsi.py")
    tmp = tempfile.mkdtemp()
    store, out = os.path.join(tmp, "store"), os.path.join(tmp, "out")
    code, _, err = run(store, "index", "spravka", "-o", out)
    check(code != 0 and "NOT_FOUND" in err, "index of an empty store")
    b = os.path.join(tmp, "Spravka_B_Pleven_2026-10-03_KS.md")
    a = os.path.join(tmp, "Spravka_A_Levski_2026-09-09_Palezh.md")
    for p, t in ((a, "# A\n\nТекст А.\n"), (b, "# B\n\nТекст Б.\n")):
        open(p, "w", encoding="utf-8").write(t)
    meta = ["--obekt", "склад | цех", "--prichina", "късо съединение", "--belezhka", "бележка", "--data", "2026-10-03"]
    code, o, err = run(store, "zapis", "spravka", b, *meta)
    check(code == 0 and json.loads(o)["index_changed"] is True, "first save creates the index")
    code, o, _ = run(store, "zapis", "spravka", a, "--obekt", "къща", "--prichina", "палеж", "--belezhka", "две огнища",
                     "--data", "2026-09-09")
    check(code == 0, "second save")
    code, o, _ = run(store, "index", "spravka", "-o", out)
    idx = open(json.loads(o)["file"], encoding="utf-8").read()
    rows = [ln for ln in idx.split("\n") if ln.startswith("| `")]
    check(len(rows) == 2 and "Spravka_A_" in rows[0] and "Spravka_B_" in rows[1], "rows sorted by file name")
    check("склад / цех" in rows[1] and rows[1].endswith("| 2026-10-03 |"), "cells cleaned, date last")
    before = idx
    code, o, _ = run(store, "zapis", "spravka", b, *meta)
    idx = open(os.path.join(store, "spravka", "INDEX.md"), encoding="utf-8").read()
    check(json.loads(o)["index_changed"] is False and idx == before, "saving the same file again changes nothing")
    code, o, _ = run(store, "zapis", "spravka", b, "--obekt", "склад", "--prichina", "техническа неизправност",
                     "--belezhka", "нова", "--data", "2026-10-03")
    idx = open(os.path.join(store, "spravka", "INDEX.md"), encoding="utf-8").read()
    check(idx.count("Spravka_B_") == 1 and "техническа неизправност" in idx, "new details replace the row")
    code, o, _ = run(store, "get", "spravka", os.path.basename(a), "-o", out)
    check(open(json.loads(o)["file"], encoding="utf-8").read() == "# A\n\nТекст А.\n", "get returns the stored text")
    code, o, _ = run(store, "spisak", "spravka")
    check(json.loads(o)["count"] == 3, "list: two templates and the index")
    check(run(store, "spisak", "eptz")[1].count('"count": 0') == 1, "kinds are separate")
    code, _, err = run(store, "get", "spravka", "Nyama.md", "-o", out)
    check(code != 0 and "NOT_FOUND" in err, "missing file")
    bad = os.path.join(tmp, "Справка.md")
    open(bad, "w", encoding="utf-8").write("x")
    code, _, err = run(store, "zapis", "spravka", bad, *meta)
    check(code != 0 and "BAD_INPUT" in err, "Cyrillic file name refused")
    code, _, err = run(store, "zapis", "spravka", a, "--obekt", "o", "--prichina", "p", "--belezhka", "b", "--data", "2026")
    check(code != 0 and "BAD_INPUT" in err, "year alone is not a date")
    print("\nALL PASS" if not failures else f"\n{len(failures)} FAILED")
    sys.exit(1 if failures else 0)
