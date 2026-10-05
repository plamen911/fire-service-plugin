#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
obraztsi.py — образците (шаблоните): одобрени справки и експертизи, пазени в Google Drive
през n8n. Четат се от всеки с личен ключ; записва ги само администраторът.

    python3 _shared/scripts/obraztsi.py index spravka            # сваля INDEX.md – таблицата с образците
    python3 _shared/scripts/obraztsi.py spisak eptz              # файловете от този вид (JSON)
    python3 _shared/scripts/obraztsi.py get spravka Spravka_Avtokashta_Pleven_2026-10-03_Dve_Tehnicheski_Versii.md
    python3 _shared/scripts/obraztsi.py zapis spravka ФАЙЛ.md --obekt "автокъща, гуми на открито" \
        --prichina "две технически версии, неустановена" --belezhka "версии като абзаци; заключение без избор" \
        --data 2026-10-03

Видове: `spravka` (справки по чл. 20, ал. 3) и `eptz` (експертизи). Свалените файлове отиват в
папката от -o (по подразбиране `obraztsi/<вид>/`); скриптът отпечатва JSON с пътя – после
четеш файла. `zapis` качва файла (името му остава същото; повторен запис го заменя) и добавя
или обновява реда му в INDEX.md, подреден по име. `--store ПАПКА` работи с локална папка
вместо с n8n (тестове).

Грешки (на stderr, код ≠ 0):
    N8N_UNAVAILABLE: ...  — n8n не отговаря → опитай веднъж отново
    NOT_FOUND: ...        — няма такъв файл (при `index` – още няма записани образци)
    FORBIDDEN: ...        — записът е само за администратора
    BAD_INPUT: ...        — неправилно име, дата или празен файл
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import api_config  # noqa: E402  (addresses of n8n and the personal key)
KINDS = ("spravka", "eptz")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,150}\.md$")
INDEX = "INDEX.md"
HEADERS = {
    "spravka": ("# Образци – справки по чл. 20, ал. 3\n\n"
                "Одобрени справки, които служат за шаблон. Избери по причина и по вид обект.\n\n"
                "| Файл | Вид обект | Причина | Какво показва | Дата |\n|---|---|---|---|---|\n"),
    "eptz": ("# Индекс на базата знания – одобрени ЕПТЗ\n\n"
             "| Файл | Тип обект | Причина | Ключов механизъм/източник | Дата |\n|---|---|---|---|---|\n"),
}


class Missing(Exception):
    pass


class Remote:
    def _call(self, body):
        try:
            return api_config.post("samples_url", body, timeout=120)
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="ignore")[:300]
            if "NOT_FOUND" in text:
                raise Missing()
            if "FORBIDDEN" in text:
                sys.exit("FORBIDDEN: само администраторът може да записва образци")
            sys.exit(f"N8N_UNAVAILABLE: HTTP {e.code} {text}")
        except (OSError, KeyError, ValueError) as e:
            sys.exit(f"N8N_UNAVAILABLE: {type(e).__name__}: {e}"[:300])

    def list(self, kind):
        return self._call({"action": "list", "kind": kind}).get("files", [])

    def get(self, kind, name):
        r = self._call({"action": "get", "kind": kind, "name": name})
        return r["text"], r.get("link")

    def put(self, kind, name, text):
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return self._call({"action": "put", "kind": kind, "name": name, "text": text, "sha256": sha})


class Local:
    def __init__(self, root):
        self.root = root

    def _path(self, kind, name):
        return os.path.join(self.root, kind, name)

    def list(self, kind):
        d = os.path.join(self.root, kind)
        names = sorted(n for n in os.listdir(d) if n.endswith(".md")) if os.path.isdir(d) else []
        return [{"name": n, "size": os.path.getsize(os.path.join(d, n))} for n in names]

    def get(self, kind, name):
        try:
            with open(self._path(kind, name), encoding="utf-8") as f:
                return f.read(), None
        except FileNotFoundError:
            raise Missing()

    def put(self, kind, name, text):
        os.makedirs(os.path.join(self.root, kind), exist_ok=True)
        with open(self._path(kind, name), "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return {"ok": True, "kind": kind, "name": name}


def cell(text):
    return re.sub(r"\s+", " ", (text or "").replace("|", "/")).strip()


def index_with_row(index_text, kind, name, row):
    """INDEX.md with the row of `name` added or replaced, table rows sorted by file name."""
    lines = (index_text if index_text is not None else HEADERS[kind]).rstrip("\n").split("\n")
    is_row = [bool(re.match(r"^\|\s*`[^`]+\.md`\s*\|", ln)) for ln in lines]
    sep = max((i for i, ln in enumerate(lines) if re.match(r"^\|\s*:?-{3,}", ln)), default=None)
    if sep is None:
        sys.exit("BAD_INPUT: INDEX.md няма таблица – поправи го на ръка")
    rows = [ln for ln, r in zip(lines, is_row) if r and f"`{name}`" not in ln] + [row]
    rows.sort(key=lambda ln: re.match(r"^\|\s*`([^`]+)`", ln).group(1).lower())
    first = min([i for i, r in enumerate(is_row) if r], default=sep + 1)
    last = max([i for i, r in enumerate(is_row) if r], default=sep)
    return "\n".join(lines[:first] + rows + lines[last + 1:]) + "\n"


def save_local(text, out_dir, name):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", help="локална папка вместо n8n (тестове)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("spisak", "index", "get", "zapis"):
        p = sub.add_parser(cmd)
        p.add_argument("kind", choices=KINDS)
        if cmd == "get":
            p.add_argument("name")
        if cmd in ("index", "get"):
            p.add_argument("-o", "--out", help="папка за сваления файл (по подразбиране obraztsi/<вид>)")
        if cmd == "zapis":
            p.add_argument("file", help="файлът с образеца (.md); името му е името в базата")
            p.add_argument("--obekt", required=True, help="вид/тип обект")
            p.add_argument("--prichina", required=True, help="причина")
            p.add_argument("--belezhka", required=True, help="какво показва образецът / ключов механизъм")
            p.add_argument("--data", required=True, help="дата на пожара ГГГГ-ММ-ДД")
    a = ap.parse_args()
    store = Local(a.store) if a.store else Remote()

    if a.cmd == "spisak":
        files = store.list(a.kind)
        print(json.dumps({"kind": a.kind, "count": len(files), "files": files}, ensure_ascii=False, indent=1))
        return
    if a.cmd in ("index", "get"):
        name = INDEX if a.cmd == "index" else a.name
        if not NAME_RE.match(name):
            sys.exit("BAD_INPUT: името е .md файл с латински букви, цифри, „_“, „-“ и „.“")
        try:
            text, link = store.get(a.kind, name)
        except Missing:
            sys.exit("NOT_FOUND: още няма записани образци от този вид" if a.cmd == "index"
                     else f"NOT_FOUND: няма образец „{name}“")
        path = save_local(text, a.out or os.path.join("obraztsi", a.kind), name)
        print(json.dumps({"file": path, "kind": a.kind, "name": name, "bytes": len(text.encode("utf-8")), "link": link},
                         ensure_ascii=False))
        return
    # zapis
    name = os.path.basename(a.file)
    if not NAME_RE.match(name) or name == INDEX:
        sys.exit("BAD_INPUT: името на файла е .md с латински букви, цифри, „_“, „-“ и „.“ (не INDEX.md)")
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$", a.data):
        sys.exit("BAD_INPUT: --data е пълната дата на пожара, ГГГГ-ММ-ДД")
    with open(a.file, encoding="utf-8") as f:
        text = f.read()
    if not text.strip():
        sys.exit("BAD_INPUT: файлът е празен")
    saved = store.put(a.kind, name, text)
    try:
        index_text, _ = store.get(a.kind, INDEX)
    except Missing:
        index_text = None
    row = f"| `{name}` | {cell(a.obekt)} | {cell(a.prichina)} | {cell(a.belezhka)} | {a.data} |"
    new_index = index_with_row(index_text, a.kind, name, row)
    if new_index != index_text:
        store.put(a.kind, INDEX, new_index)
    print(json.dumps({"ok": True, "kind": a.kind, "name": name, "link": saved.get("link"),
                      "updated_by": saved.get("updated_by"), "index_changed": new_index != index_text,
                      "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
