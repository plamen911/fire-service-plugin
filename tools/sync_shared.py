#!/usr/bin/env python3
"""
sync_shared.py — копира общия слой plugins/fire-service/shared/ във всеки скил като _shared/.

Защо: инсталираният скил вижда само собствената си папка, затова общите правила,
терминологията и скриптовете трябва да са копирани вътре. Източникът е един —
plugins/fire-service/shared/ — копията не се редактират на ръка.

    python3 tools/sync_shared.py          # обновява всички _shared/
    python3 tools/sync_shared.py --check  # само проверява (за CI); код 1 при разлика

Когато има личен ключ, преди копирането пресъздава shared/sluzhiteli/katalog.json от списъка
на служителите (`sluzhiteli.py --katalog`) – званията, длъжностите и звената, без имена; от
него уеб приложението пълни падащите си менюта. Без ключ файлът остава какъвто е.
"""
import argparse
import filecmp
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "plugins", "fire-service")
SHARED = os.path.join(PLUGIN, "shared")
SKILLS = os.path.join(PLUGIN, "skills")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def differs(a, b):
    cmp = filecmp.dircmp(a, b, ignore=["__pycache__", ".DS_Store"])
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return True
    # filecmp's shallow compare may miss same-size edits; compare contents explicitly
    for f in cmp.common_files:
        if not filecmp.cmp(os.path.join(a, f), os.path.join(b, f), shallow=False):
            return True
    return any(differs(os.path.join(a, d), os.path.join(b, d)) for d in cmp.common_dirs)


KATALOG = os.path.join(SHARED, "sluzhiteli", "katalog.json")


def katalog_json():
    """The catalogue built from the live staff list, or None without a personal key."""
    r = subprocess.run([sys.executable, "-B", os.path.join(SHARED, "scripts", "sluzhiteli.py"), "--katalog"],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 and r.stdout.strip().startswith("{") else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    stale = []
    fresh = katalog_json()
    current = open(KATALOG, encoding="utf-8").read() if os.path.exists(KATALOG) else ""
    if not a.check and fresh is not None and current != fresh:
        with open(KATALOG, "w", encoding="utf-8") as f:
            f.write(fresh)
        print("rebuilt shared/sluzhiteli/katalog.json")
    for name in sorted(os.listdir(SKILLS)):
        skill = os.path.join(SKILLS, name)
        if not os.path.isfile(os.path.join(skill, "SKILL.md")):
            continue
        dst = os.path.join(skill, "_shared")
        if a.check:
            if not os.path.isdir(dst) or differs(SHARED, dst):
                stale.append(name)
            continue
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(SHARED, dst, ignore=IGNORE)
        print(f"synced  {name}/_shared")
    if a.check:
        if stale:
            print("STALE _shared in: " + ", ".join(stale) + " — run: python3 tools/sync_shared.py")
            sys.exit(1)
        print("all _shared copies are in sync")


if __name__ == "__main__":
    main()
