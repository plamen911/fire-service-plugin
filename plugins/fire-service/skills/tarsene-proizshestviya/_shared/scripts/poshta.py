#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
poshta.py — изпраща готови документи по и-мейл през n8n (от Gmail на администратора). Работи
отвсякъде, където работят скриптовете – без браузър и без свързан Gmail в разговора.

    python3 _shared/scripts/poshta.py --do az --tema "План-конспект – ноември" Plan.docx Otchet.docx
    python3 _shared/scripts/poshta.py --do ivan@example.bg --tema "…" --tekst "…" a.docx      # няколко --do = няколко получатели
    python3 _shared/scripts/poshta.py --do az --tema "…" a.docx --dry-run     # само показва какво би изпратил

Кой до кого може: всеки с личен ключ – само до собствения си адрес от списъка на служителите
(`--do az`); администраторът – до всеки адрес (най-много 10). Файлове: docx, xlsx, pdf, md, txt, csv,
kml, svg, png, jpg; общо до 7 MB. В края на писмото сървърът добавя кой го е изпратил.
Без ключ спира с NO_KEY – тогава се изпраща от Gmail на потребителя, ако е свързан в разговора.
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import api_config  # noqa: E402

MAX_BYTES = 7 * 1024 * 1024
TYPES = ("docx", "xlsx", "pdf", "md", "txt", "csv", "kml", "svg", "png", "jpg", "jpeg")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", metavar="ФАЙЛ")
    ap.add_argument("--do", action="append", required=True, metavar="АДРЕС", help="получател; „az“ = собственият адрес")
    ap.add_argument("--tema", required=True)
    ap.add_argument("--tekst", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    atts, total = [], 0
    for path in a.files:
        name = os.path.basename(path)
        if name.rsplit(".", 1)[-1].lower() not in TYPES:
            sys.exit(f"BAD_INPUT: {name} – позволени са {', '.join(TYPES)}")
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as e:
            sys.exit(f"NO_DATA: {e}")
        total += len(raw)
        atts.append({"name": name, "base64": base64.b64encode(raw).decode()})
    if total > MAX_BYTES:
        sys.exit(f"BAD_INPUT: файловете са {total / 1048576:.1f} MB – най-много {MAX_BYTES // 1048576} MB общо")
    if not atts and not a.tekst.strip():
        sys.exit("BAD_INPUT: писмото е празно – дай файлове или --tekst")
    body = {"to": ["me" if t.strip().lower() in ("az", "аз", "me") else t.strip() for t in a.do], "subject": a.tema,
            "text": a.tekst, "attachments": atts, "dry_run": a.dry_run}
    try:
        with urllib.request.urlopen(api_config.request("mail_url", body), timeout=180) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="ignore")
        try:
            msg = str(json.loads(raw).get("error") or raw)
        except ValueError:
            msg = raw
        if e.code in (401, 403) and "UNAUTHORIZED" in msg:
            sys.exit(f"KEY_REJECTED: n8n не приема личния ключ – {msg}"[:300])
        sys.exit(msg[:400] if msg[:1].isupper() and ":" in msg[:20] else f"N8N_UNAVAILABLE: HTTP {e.code} {msg}"[:300])
    except (OSError, ValueError) as e:
        sys.exit(f"N8N_UNAVAILABLE: {type(e).__name__}: {e}"[:300])
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        names = ", ".join(f["ime"] for f in res.get("faylove") or []) or "без прикачени файлове"
        print(("Проба – нищо не е изпратено. " if res.get("dry_run") else "Изпратено. ")
              + f'До: {", ".join(res.get("do") or [])} | Тема: {res.get("tema")} | {names}')


if __name__ == "__main__":
    main()
