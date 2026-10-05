#!/usr/bin/env python3
"""
check_public.py — пази хранилището чисто: то е публично и в него не бива да има лични данни
и тайни. Пуска се от validate.py (и в CI) върху всички файлове, които git следи или би следил.

Търси: лични ключове и хешове, имейли, телефони, ЕГН, регистрационни номера на МПС, IBAN,
идентификатори на файлове в Google Drive и имена на хора. Истинските имена ги няма тук, за да
се сравнява с тях – затова име се приема само ако е в списъка FICTIONAL по-долу (измислените
хора от примерите и тестовете). С личен ключ (FIRE_SERVICE_KEY) проверката сверява и със
списъка на служителите от n8n.

    python3 tools/check_public.py            # код 1 при находка
"""
import html
import os
import re
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plugins", "fire-service", "shared", "scripts"))

# Invented people used in examples, templates and tests: common first names with surnames that nobody in
# the real staff list has (trees and shrubs), plus the generic "Иван Петров" kind of name in the instructions.
# A full name outside these lists is a finding.
FIRST = set("""иван мария георги петър стоян димитър николай елена тодор васил христо ангел бранимир красимир
красимира мариян мариан нов админ тест""".split())
LAST = set("""дъбов липов яворов кестенов брезов тополов тополова смърчев елхов малинов къпинов черешов вишнев
орехов лешников бадемов лозев лозева дренов глогов шипков буков ясенов ружев
петров петрова георгиев стоянов новаков админов тестов непознат""".split())

# Authors of the literature the skills cite, historical figures in street names and the like.
ALLOWED_NAMES = set()   # e.g. the author of a cited book, if the pattern ever catches one

PATTERNS = {
    "personal key": re.compile(r"\bfs_[0-9A-Za-z_-]{20,}"),
    "hash or long hex": re.compile(r"\b[0-9a-f]{40,}\b"),
    "token in an address": re.compile(r"[?&](key|token)=[A-Za-z0-9_-]{12,}"),
    "e-mail": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}"),
    "mobile phone": re.compile(r"(?<!\d)(?:\+359|0)8[789]\d[ \-]?\d{3}[ \-]?\d{3}(?!\d)"),
    "ЕГН": re.compile(r"(?<![\d.])\d{10}(?![\d.])"),
    "car plate": re.compile(r"(?<![А-ЯA-Z])[АВЕКМНОРСТУХABEKMHOPCTYX]{1,2}\s?\d{4}\s?[АВЕКМНОРСТУХABEKMHOPCTYX]{2}(?![А-ЯA-Zа-я])"),
    "Drive file id": re.compile(r"(?<![A-Za-z0-9_-])1[A-Za-z0-9_-]{32}(?![A-Za-z0-9_-])"),
}
ALLOWED = {
    "e-mail": {"noreply@anthropic.com", "ivan@example.bg"},
    # the account of РДПБЗН – Плевен for experts' fees: a requisite of the institution, printed on every сметка
    "IBAN": {"BG96UBBS80023112509310"},
}
IBAN = re.compile(r"\bBG\d{2}[A-Z]{4}[0-9A-Z]{14}\b")
# three capitalised Cyrillic words whose last two look like a patronymic and a surname; or name + surname
NAME3 = re.compile(r"\b([А-Я][а-я]+) ([А-Я][а-я]+(?:ов|ев|ин|ски|ова|ева|ина|ска)) ([А-Я][а-я]+(?:ов|ев|ин|ски|ова|ева|ина|ска))\b")
SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".woff", ".woff2")


def files():
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split("\n")
    return [f for f in out if f and not f.lower().endswith(SKIP_EXT)]


def text_of(path):
    full = os.path.join(ROOT, path)
    if path.lower().endswith((".docx", ".xlsx")):
        with zipfile.ZipFile(full) as z:
            return "\n".join(html.unescape(re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", "ignore")))
                             for n in z.namelist() if n.endswith((".xml", ".rels")))
    try:
        with open(full, encoding="utf-8") as f:
            return html.unescape(f.read())
    except (UnicodeDecodeError, OSError):
        return ""


def staff_names():
    """Names from the live staff list – only when a personal key is at hand (the administrator's check)."""
    try:
        import api_config
        import sluzhiteli
        if not api_config.has_key():
            return []
        _, rows = sluzhiteli.load()
    except BaseException:  # noqa: BLE001  (no network, no key: the pattern checks still run)
        return []
    names = set()
    for r in rows:
        for k in ("ime", "ime_kratko"):
            if r.get(k) and len(r[k].split()) >= 2:
                names.add(r[k].strip())
    return sorted(names)


def main():
    findings = []
    fictional_ok = lambda first, last: first.lower() in FIRST and last.lower() in LAST
    staff = [n for n in staff_names() if not fictional_ok(n.split()[0], n.split()[-1])]
    for path in files():
        if path == "tools/check_public.py":
            continue
        text = text_of(path)
        low = text.lower()
        for label, rx in PATTERNS.items():
            for m in rx.finditer(text):
                if m.group(0) not in ALLOWED.get(label, ()):
                    findings.append((path, label, m.group(0)[:60]))
        for m in IBAN.finditer(text):
            if m.group(0) not in ALLOWED["IBAN"]:
                findings.append((path, "IBAN", m.group(0)))
        for m in NAME3.finditer(text):
            if not fictional_ok(m.group(1), m.group(3)) and m.group(0) not in ALLOWED_NAMES:
                findings.append((path, "full name", m.group(0)))
        for name in staff:
            if name.lower() in low:
                findings.append((path, "staff member", name))
    for path, label, what in sorted(set(findings)):
        print(f"✗ {path}: {label}: {what}")
    print(f"{len(set(findings))} находки" if findings else "✓ няма лични данни и тайни"
          + (f" (сверено и с {len(staff)} имена от списъка на служителите)" if staff else " (без сверка със списъка на служителите – няма ключ)"))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
