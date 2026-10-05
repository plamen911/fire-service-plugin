#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
regs.py — нормативната база (Fire Safety Regulatory Documents) през n8n.

Файловете стоят в Google Drive на администратора; n8n ги чете и ги дава на всеки активен личен ключ
(`regs_url` в `_shared/incident_api.json`; ключът идва от `api_config.py`). Друг път към базата няма.

    python3 scripts/regs.py list                       # всички файлове (JSON: path, id, modified_at, size)
    python3 scripts/regs.py list --folder tier-a       # само една папка ("" = корена)
    python3 scripts/regs.py list --name 8121з-1006     # името съдържа текста
    python3 scripts/regs.py index                      # сваля текущия индекс (_INDEX_*.md, най-новия)
    python3 scripts/regs.py get _MAP_pg_sd.md          # сваля файл по име, път, част от името или Drive ID
    python3 scripts/regs.py get tier-a/…_2026_ed2026-02-27.md -o work

Свалените файлове отиват в папката от -o (по подразбиране `regs/` в текущата папка). Скриптът
отпечатва JSON {"file", "path", "id", "modified_at", "bytes", "link"} – после четеш файла `file`
(търси в него члена с Grep/Read, не го изсипвай целия в чата). `link` е адресът в Drive за
позоваването в отговора; отваря се само от хора с достъп до папката.

Грешки (на stderr, код ≠ 0):
    N8N_UNAVAILABLE: ...   — n8n не отговаря или върна грешка → опитай веднъж отново
    NOT_FOUND: ...         — няма такъв файл в базата
    AMBIGUOUS: ...         — името пасва на няколко файла; изброени са – подай по-точно име или ID
    UNSUPPORTED: ...       — файлът не е текстов (PDF оригинал) и не се сваля
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_shared", "scripts"))
import api_config  # noqa: E402  (addresses of n8n and the personal key)


def call(body):
    try:
        return api_config.post("regs_url", body)
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="ignore")[:200]
        if e.code == 415 or "UNSUPPORTED" in text:
            sys.exit("UNSUPPORTED: файлът не е текстов и не се сваля през n8n")
        if "File not found" in text or "NOT_FOUND" in text:
            sys.exit("NOT_FOUND: няма такъв файл в базата")
        sys.exit(f"N8N_UNAVAILABLE: HTTP {e.code} {text}")
    except (OSError, KeyError, ValueError) as e:
        sys.exit(f"N8N_UNAVAILABLE: {type(e).__name__}: {e}"[:300])


def listing():
    res = call({"action": "list"})
    if not isinstance(res, dict) or not isinstance(res.get("files"), list):
        sys.exit("N8N_UNAVAILABLE: unexpected response shape")
    return res["files"]


def norm(s):
    return (s or "").strip().lower()


def resolve(files, what):
    """One file by Drive ID, exact path, exact name, or a unique part of the path."""
    q = norm(what)
    for key in ("id", "path", "name"):
        hit = [f for f in files if norm(f.get(key)) == q or (key == "id" and f.get("id") == what)]
        if len(hit) == 1:
            return hit[0]
    hit = [f for f in files if q in norm(f.get("path"))]
    if len(hit) == 1:
        return hit[0]
    if not hit:
        sys.exit(f"NOT_FOUND: няма файл „{what}“ в базата")
    names = "\n".join("  " + f["path"] for f in hit[:30])
    sys.exit(f"AMBIGUOUS: „{what}“ пасва на {len(hit)} файла:\n{names}")


def download(f, out_dir):
    res = call({"action": "download", "id": f["id"]})
    if not isinstance(res, dict) or not isinstance(res.get("content"), str):
        sys.exit("N8N_UNAVAILABLE: unexpected response shape")
    os.makedirs(out_dir, exist_ok=True)
    safe = re.sub(r"[^\w.\-]+", "_", res.get("path") or f["path"], flags=re.UNICODE) or f["id"]
    target = os.path.join(out_dir, safe)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(res["content"])
    print(json.dumps({"file": target, "path": res.get("path") or f["path"], "id": f["id"],
                      "modified_at": res.get("modified_at") or f.get("modified_at"),
                      "bytes": len(res["content"].encode("utf-8")),
                      "link": f"https://drive.google.com/file/d/{f['id']}/view"},
                     ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="файловете в базата")
    p.add_argument("--folder", help='само тази папка ("" = корена)')
    p.add_argument("--name", help="името съдържа този текст")
    p = sub.add_parser("index", help="сваля текущия индекс (_INDEX_*.md)")
    p.add_argument("-o", "--output", default="regs", help="папка за свалените файлове (по подразбиране regs)")
    p = sub.add_parser("get", help="сваля един файл")
    p.add_argument("what", help="име, път, част от името или Drive ID")
    p.add_argument("-o", "--output", default="regs", help="папка за свалените файлове (по подразбиране regs)")
    a = ap.parse_args()

    files = listing()
    if a.cmd == "list":
        if a.folder is not None:
            files = [f for f in files if norm(f.get("folder")) == norm(a.folder)]
        if a.name:
            files = [f for f in files if norm(a.name) in norm(f.get("name"))]
        rows = [{"path": f["path"], "id": f["id"], "modified_at": f.get("modified_at"), "size": f.get("size")}
                for f in files]
        print(json.dumps({"count": len(rows), "files": rows}, ensure_ascii=False, indent=1))
    elif a.cmd == "index":
        idx = [f for f in files if f.get("folder", "") == "" and f.get("name", "").startswith("_INDEX_")]
        if not idx:
            sys.exit("NOT_FOUND: в корена на базата няма файл, започващ с _INDEX_")
        idx.sort(key=lambda f: (f.get("modified_at") or "", f.get("name") or ""))
        download(idx[-1], a.output)
    else:
        download(resolve(files, a.what), a.output)


if __name__ == "__main__":
    main()
