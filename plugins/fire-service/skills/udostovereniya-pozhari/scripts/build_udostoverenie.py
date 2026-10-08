#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_udostoverenie.py — попълва бланките на РДПБЗН – Плевен за:

  • "udostoverenie"  — УДОСТОВЕРЕНИЕ ЗА ВЪЗНИКНАЛО ПРОИЗШЕСТВИЕ до гражданин
                       (assets/udostoverenie_template.docx);
  • "pridruzhitelno" — придружително писмо до РУ МВР, прокуратура, застраховател и др.
                       със заверени копия на документите за произшествието
                       (assets/pridruzhitelno_template.docx).

Шаблоните са извлечени от подписани образци; променливите места са маркирани с
{{…}} и се пълнят тук. Форматът (бланка, шрифт, отстъпи, таблици) не се пипа.

Употреба:
    python3 build_udostoverenie.py data.json -o /mnt/user-data/outputs/Udostoverenie_....docx

data.json:
{
  "kind": "udostoverenie",                 // или "pridruzhitelno"
  "addressee": ["Г-ЖА МАРИЯ ПЕТРОВА", "ГР. ПЛЕВЕН", "ОБЩ. ПЛЕВЕН",
                "ЖК „…“, БЛ. …, ВХ. …, ЕТ. …, АП. …"],   // редовете след „ДО“
  "salutation": "УВАЖАЕМА Г-ЖО ПЕТРОВА,",
  "body": ["Уведомявам Ви, че …", "Произшествието е ликвидирано от …",
           "Настоящето удостоверение се издава да послужи при необходимост."],
  "attention": "Разследващ полицай Георги Георгиев",   // само "pridruzhitelno"; празно → редът отпада
  "reference": "На Ваш рег. № 000р-0000/20.05.2026 г.",  // само "pridruzhitelno"; празно → отпада
  "attachments": ["1. Телефонограма за произшествие № 00/16.05.2026 г. – 1 лист."],  // "pridruzhitelno"
  "director": {"label": "ДИРЕКТОР:", "rank": "КОМИСАР", "name": "Име Фамилия"},
                                           // по подразбиране – директорът от списъка на служителите
  "izgotvil": {"position": "инспектор IV ст.", "name": "Иван Петров", "date": "28.05.2026 г."},
                                           // izgotvil_position и ime от профила на потребителя
  "copies": ["деловодство", "Мария Петрова"],     // → „Екз. № 1 – деловодство“ …
  "year": "2026"                                     // по подразбиране — от izgotvil.date
}

Типографията следва _shared/conventions.md: „№ 4“ (с интервал) и тире „–“ (самостоятелното
„-“ между интервали и „—“ стават „–“; дефисът в думи и номера остава).
"""
import argparse
import copy
import json
import os
import re
import sys

from docx import Document
from docx.oxml.ns import qn

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_shared", "scripts"))
from docx_common import report, typo, typo_all  # noqa: E402  (the common typography rules and the final check)

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = {
    "udostoverenie": os.path.join(HERE, "..", "assets", "udostoverenie_template.docx"),
    "pridruzhitelno": os.path.join(HERE, "..", "assets", "pridruzhitelno_template.docx"),
}
# Placeholders: the director comes from the staff list (staff_director) or from data.json, the
# author from the user's profile. A placeholder left in the document means it was not given.
DEFAULT_DIRECTOR = {"label": "ДИРЕКТОР:", "rank": "[ЗВАНИЕ]", "name": "[Име Фамилия]"}
DEFAULT_IZGOTVIL = {"position": "[звание]", "name": "[Име Фамилия]"}


def staff_director():
    """The director of РДПБЗН – Плевен from the staff list (n8n), or None (no key, no answer)."""
    import importlib.util
    path = os.path.join(HERE, "..", "_shared", "scripts", "sluzhiteli.py")
    if not os.path.exists(path):
        return None
    try:
        spec = importlib.util.spec_from_file_location("sluzhiteli", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.direktor()
    except Exception:
        return None

PH_RE = re.compile(r"\{\{\w+\}\}")


def ptext(p):
    return "".join(t.text or "" for t in p.iter(qn("w:t")))


def set_text(p, text):
    """Задава текст на параграф, като пази формата на първия run с текст."""
    runs = p.findall(qn("w:r"))
    keep = next((r for r in runs if r.find(qn("w:t")) is not None), runs[0] if runs else None)
    if keep is None:
        keep = p.makeelement(qn("w:r"), {})
        p.append(keep)
    for r in runs:
        if r is not keep:
            p.remove(r)
    for ch in list(keep):
        if ch.tag in (qn("w:t"), qn("w:tab"), qn("w:br")):
            keep.remove(ch)
    t = keep.makeelement(qn("w:t"), {})
    t.text = typo(text)
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    keep.append(t)


def find_p(root, marker):
    for p in root.iter(qn("w:p")):
        if marker in ptext(p):
            return p
    raise SystemExit(f"Шаблонът няма маркер {marker}")


def ancestor(el, tag):
    while el is not None and el.tag != qn(tag):
        el = el.getparent()
    return el


def replace_marker(root, marker, value):
    p = find_p(root, marker)
    set_text(p, ptext(p).replace(marker, value))


def expand_paragraph(root, marker, lines):
    """Параграфът с маркера става len(lines) параграфа със същия формат."""
    p = find_p(root, marker)
    lines = lines or [""]
    prev = p
    for line in lines[1:]:
        q = copy.deepcopy(p)
        set_text(q, line)
        prev.addnext(q)
        prev = q
    set_text(p, lines[0])


def expand_row(root, marker, values, first_col=None):
    """Редът на таблицата с маркера се клонира за всяка стойност.
    first_col: текстът в първата колона на първия ред (напр. „ПРИЛОЖЕНИЕ:“); в
    следващите редове първата колона остава празна."""
    tr = ancestor(find_p(root, marker), "w:tr")
    values = values or []
    if not values:
        tr.getparent().remove(tr)
        return
    rows, prev = [tr], tr
    for _ in values[1:]:
        r = copy.deepcopy(tr)
        prev.addnext(r)
        rows.append(r)
        prev = r
    for i, (r, v) in enumerate(zip(rows, values)):
        p = next(q for q in r.iter(qn("w:p")) if marker in ptext(q))
        set_text(p, ptext(p).replace(marker, v))
        if first_col is not None and i > 0:
            tc0 = r.find(qn("w:tc"))
            for q in tc0.iter(qn("w:p")):
                if ptext(q).strip():
                    set_text(q, "")


def drop_row_if_empty(root, marker, value):
    if value:
        replace_marker(root, marker, value)
    else:
        tr = ancestor(find_p(root, marker), "w:tr")
        tr.getparent().remove(tr)


def build(data, out):
    kind = data.get("kind", "udostoverenie")
    if kind not in TEMPLATES:
        raise SystemExit(f"kind трябва да е една от {list(TEMPLATES)}")
    doc = Document(TEMPLATES[kind])
    body = doc.element.body

    izg = dict(DEFAULT_IZGOTVIL, **(data.get("izgotvil") or {}))
    dr = dict(staff_director() or DEFAULT_DIRECTOR, **(data.get("director") or {}))
    for what, got in (("director", dr), ("izgotvil", izg)):
        if "[" in got.get("name", ""):
            print(f'MISSING: {what} – подай го в data.json', file=sys.stderr)
    date = izg.get("date", "")
    m = re.search(r"(20\d\d)", date)
    year = str(data.get("year") or (m.group(1) if m else ""))

    replace_marker(body, "{{year}}", year)
    if kind == "udostoverenie":
        expand_paragraph(body, "{{addressee}}", data.get("addressee"))
    else:
        expand_row(body, "{{addressee}}", data.get("addressee"))
    replace_marker(body, "{{salutation}}", data.get("salutation", ""))
    expand_paragraph(body, "{{body}}", data.get("body"))
    if kind == "pridruzhitelno":
        drop_row_if_empty(body, "{{attention}}", data.get("attention", ""))
        drop_row_if_empty(body, "{{reference}}", data.get("reference", ""))
        expand_row(body, "{{attachment}}", data.get("attachments"), first_col="ПРИЛОЖЕНИЕ:")
    replace_marker(body, "{{director_label}}", dr["label"])
    replace_marker(body, "{{director_rank}}", dr["rank"])
    replace_marker(body, "{{director_name}}", dr["name"])
    replace_marker(body, "{{izgotvil_position}}", izg["position"])
    replace_marker(body, "{{izgotvil_name}}", izg["name"])
    replace_marker(body, "{{izgotvil_date}}", date)
    copies = data.get("copies") or ["деловодство"]
    replace_marker(body, "{{copies_count}}", str(len(copies)))
    expand_row(body, "{{copy}}", [f"Екз. № {i} – {c}" for i, c in enumerate(copies, 1)])

    left = PH_RE.findall("".join(t.text or "" for t in body.iter(qn("w:t"))))
    if left:
        raise SystemExit(f"Непопълнени полета: {left}")
    typo_all(doc)
    doc.save(out)
    report(out)
    print(f"✅ {out}")


def unit_name(u):
    """„РС ПБЗН - Плевен“ → „РСПБЗН – Плевен“; „У ПБЗН - Сторгозия“ → „У ПБЗН – Сторгозия“."""
    u = re.sub(r"\s*-\s*", " – ", u.strip())
    return re.sub(r"^РС ПБЗН", "РСПБЗН", u)


def plural(n, one, many):
    return one if n == 1 else many


def forces_sentence(forces):
    """Полето `forces` от телефонограмата → изречението за ликвидирането.
    „служ 3; 1 ПА; 1 - РС ПБЗН - Плевен;“ →
    „Произшествието е ликвидирано от екип на РСПБЗН – Плевен с 1 бр. пожарен автомобил и
    3 служители.“"""
    staff = re.search(r"служ\s*(\d+)", forces or "")
    trucks = re.search(r"(\d+)\s*ПА", forces or "")
    units = [unit_name(u) for u in re.findall(r"\d+\s*-\s*([^;]+)", forces or "")]
    if not units:
        return ""
    who = (f"екип на {units[0]}" if len(units) == 1
           else "екипи на " + ", ".join(units[:-1]) + " и " + units[-1])
    parts = []
    if trucks:
        n = int(trucks.group(1))
        parts.append(f"{n} бр. {plural(n, 'пожарен автомобил', 'пожарни автомобила')}")
    if staff:
        n = int(staff.group(1))
        parts.append(f"{n} {plural(n, 'служител', 'служители')}")
    tail = (" с " + " и ".join(parts)) if parts else ""
    return f"Произшествието е ликвидирано от {who}{tail}."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", nargs="?")
    ap.add_argument("-o", "--out")
    ap.add_argument("--forces", help="само отпечатва изречението за силите от полето `forces`")
    a = ap.parse_args()
    if a.forces is not None:
        print(forces_sentence(a.forces))
        return 0
    if not (a.data and a.out):
        ap.error("нужни са data.json и -o")
    build(json.load(open(a.data, encoding="utf-8")), os.path.abspath(a.out))


if __name__ == "__main__":
    sys.exit(main())
