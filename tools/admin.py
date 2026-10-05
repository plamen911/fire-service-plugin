#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
admin.py — действията на администратора: ключове на колеги, списъкът на служителите и
файловете зад n8n. Иска администраторски личен ключ (виж
plugins/fire-service/shared/scripts/api_config.py). Същото може и от телефона, през конектора
Fire Service: инструментите `keys`, `staff_update` и `samples_save`.

Ключове на колеги
    python3 tools/admin.py key add "Име Фамилия"            # нов ключ + готовият адрес за конектора (показва се веднъж)
    python3 tools/admin.py key add "Име Фамилия" --replace  # спира старите му ключове и дава нов
    python3 tools/admin.py key list                         # кой има ключ
    python3 tools/admin.py key revoke "Име Фамилия"         # спира ключовете му
    python3 tools/admin.py key revoke --id 4                # спира един ключ по номера му от key list

Списък на служителите (основното копие е в n8n)
    python3 tools/admin.py staff get -o staff.csv           # сваля целия списък
    python3 tools/admin.py staff publish staff.csv          # качва целия списък (ново поименно разписание)
    python3 tools/admin.py staff set "Име Фамилия" email=ivan@example.bg zvanie="Инспектор"
    python3 tools/admin.py staff add zveno="РСПБЗН – Кнежа" zaemana_dlazhnost="ПОЖАРНИКАР" \
        zvanie="Младши инспектор" ime="Иван Георгиев Петров" ime_kratko="Иван Петров"

Файлове (Google Drive през n8n): видове spravka, eptz, raioni, admin
    python3 tools/admin.py files list raioni
    python3 tools/admin.py files get raioni naseleni_mesta.csv -o .
    python3 tools/admin.py files put raioni naseleni_mesta.csv      # нова таблица на районите на действие
    python3 tools/admin.py files put admin backup.json --name n8n_workflow.json

Как се добавя колега: 1) има ли го в списъка на служителите (`staff get`) – ако не, `staff add`;
2) `key add "Име Фамилия"` – името точно както е в колоната ime_kratko; 3) дай му адреса от
отговора – той го слага в Customize → Connectors → Add custom connector („No sign-in“) и
добавя плъгина от Customize → Plugins → Add marketplace.
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plugins", "fire-service", "shared", "scripts"))
import api_config  # noqa: E402


def call(url_field, body):
    try:
        return api_config.post(url_field, body, timeout=120)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode(errors='ignore')[:400]}")
    except (OSError, ValueError) as e:
        sys.exit(f"N8N_UNAVAILABLE: {type(e).__name__}: {e}"[:300])


def show(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def pairs(items):
    out = {}
    for item in items:
        k, sep, v = item.partition("=")
        if not sep or not k:
            sys.exit(f"BAD_INPUT: „{item}“ – очаква се поле=стойност")
        out[k.strip()] = v.strip()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="area", required=True)

    key = sub.add_parser("key").add_subparsers(dest="cmd", required=True)
    p = key.add_parser("add"); p.add_argument("user"); p.add_argument("--replace", action="store_true")
    p.add_argument("--admin", action="store_true", help="ключът е администраторски")
    key.add_parser("list")
    p = key.add_parser("revoke"); p.add_argument("user", nargs="?"); p.add_argument("--id", type=int, help="номерът на ключа от key list")

    staff = sub.add_parser("staff").add_subparsers(dest="cmd", required=True)
    p = staff.add_parser("get"); p.add_argument("-o", "--out")
    p = staff.add_parser("publish"); p.add_argument("file")
    p = staff.add_parser("set"); p.add_argument("name"); p.add_argument("fields", nargs="+", metavar="поле=стойност")
    p = staff.add_parser("add"); p.add_argument("fields", nargs="+", metavar="поле=стойност")

    files = sub.add_parser("files").add_subparsers(dest="cmd", required=True)
    p = files.add_parser("list"); p.add_argument("kind")
    p = files.add_parser("get"); p.add_argument("kind"); p.add_argument("name"); p.add_argument("-o", "--out", default=".")
    p = files.add_parser("put"); p.add_argument("kind"); p.add_argument("file"); p.add_argument("--name")
    a = ap.parse_args()

    if a.area == "key":
        if a.cmd == "add":
            show(call("admin_url", {"action": "key_add", "user": a.user, "replace": a.replace, "admin": a.admin}))
        elif a.cmd == "list":
            show(call("admin_url", {"action": "key_list"}))
        else:
            if a.id is None and not a.user:
                sys.exit("дай име или --id НОМЕР (от key list)")
            show(call("admin_url", {"action": "key_revoke", "id": a.id} if a.id is not None else {"action": "key_revoke", "user": a.user}))
    elif a.area == "staff":
        if a.cmd == "get":
            res = call("staff_url", {})
            if a.out:
                with open(a.out, "w", encoding="utf-8", newline="") as f:
                    f.write(res["csv"])
                show({"file": a.out, "rows": res.get("rows"), "updated_at": res.get("updated_at"), "updated_by": res.get("updated_by")})
            else:
                sys.stdout.write(res["csv"])
        elif a.cmd == "publish":
            with open(a.file, encoding="utf-8") as f:
                show(call("staff_url", {"action": "publish", "csv": f.read()}))
        elif a.cmd == "set":
            show(call("staff_url", {"action": "update", "name": a.name, "set": pairs(a.fields)}))
        else:
            show(call("staff_url", {"action": "add", "row": pairs(a.fields)}))
    else:
        if a.cmd == "list":
            show(call("samples_url", {"action": "list", "kind": a.kind}))
        elif a.cmd == "get":
            res = call("samples_url", {"action": "get", "kind": a.kind, "name": a.name})
            path = os.path.join(a.out, a.name)
            os.makedirs(a.out, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(res["text"])
            show({"file": path, "link": res.get("link")})
        else:
            with open(a.file, encoding="utf-8") as f:
                text = f.read()
            show(call("samples_url", {"action": "put", "kind": a.kind, "name": a.name or os.path.basename(a.file),
                                      "text": text, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}))


if __name__ == "__main__":
    main()
